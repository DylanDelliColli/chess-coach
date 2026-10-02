"""Stockfish over UCI, behind a persistent cache keyed by position.

The release's pipeline asks one engine the same questions thousands of times:
opening FENs genuinely recur across a player's games (4,634 distinct position
keys in one real month, against 4,738 full FENs). Two properties of this module
carry the release:

* **Scores are white's point of view, always.** python-chess reports the
  side-to-move point of view, so the same evaluation reads ``+30`` from a
  white-to-move board and ``-30`` from a black-to-move one. Every score read
  here goes through ``info["score"].white()``, once, and the conversion to the
  player's perspective happens later in ``severity.to_my_pov``. Reading the
  relative score instead is silently correct on every white-to-move fixture and
  sign-flipped on every black ply, which is the failure the PRD names.
* **The cache is keyed by position, not by FEN string.** ``position_key`` drops
  the halfmove clock and fullmove number, so the same board reached by
  transposition at a different move count is one entry, not two - and the engine is
  searched on that same counter-free position, because Stockfish takes its
  ``rule50`` from the FEN it is handed and a different clock is a different search
  (see :func:`_search_position`).
* **A score is a property of its position, not of what was searched before
  it.** Stockfish carries its transposition table across searches, and
  python-chess's ``SimpleEngine`` sends no ``ucinewgame``, so an unreset engine
  answers the same position differently depending on the order it was asked:
  measured on this host, 58 of 60 real opening positions scored differently
  between the two search orders at depth 12. Every search here is therefore
  preceded by a ``ucinewgame``, and the frozen options pin one thread, because a
  multi-threaded search is not reproducible within one analysis either. The book
  band is 30 cp: an order artefact of that size decides a finding, and this tool
  exists to tell someone which of their habits to fix.

The engine process is launched lazily, on the first cache miss, so a run whose
positions are all cached never starts a process. The cache is a real sqlite file
at ``cache_path`` (one per worker; concurrent writers to one file is how
``database is locked`` happens).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine

from .config import DEFAULT_ANALYSIS_DEPTH, Config, position_key

__all__ = [
    "DEFAULT_ENGINE_OPTIONS",
    "EngineError",
    "EngineService",
    "EvalResult",
]


class EngineError(RuntimeError):
    """The engine answered something this module cannot turn into an evaluation."""


#: Passed to Stockfish at launch. One thread, because reproducibility is worth
#: more here than the wall clock: measured on this host at ``Threads=2``, the same
#: position at depth 18 came back as +1, 0, +13 and -2 cp with two different best
#: moves across four separate processes. ``Hash`` is 128 MB, which is also what
#: keeps three workers running engines at once inside this host's memory. A caller
#: who wants the speed passes ``options={"Threads": "4"}`` and forfeits
#: reproducibility knowingly.
DEFAULT_ENGINE_OPTIONS: dict[str, str] = {"Threads": "1", "Hash": "128"}

#: Sent to the engine before every search, so that a position's score does not
#: depend on the positions searched before it in the same process. UCI has no
#: command for "forget part of the hash", and this is the one that means "start
#: from nothing": the transposition table is the channel an earlier position uses
#: to answer for a later one.
_RESET_LINE = "ucinewgame"

#: sqlite3's own busy timeout, in seconds, for a cache file someone else holds.
_SQLITE_BUSY_TIMEOUT = 10.0

_CREATE_EVALS = """
CREATE TABLE IF NOT EXISTS evaluations (
    position  TEXT    NOT NULL,
    depth     INTEGER NOT NULL,
    cp        INTEGER,
    mate      INTEGER,
    best_move TEXT,
    PRIMARY KEY (position, depth)
)
"""


@dataclass(frozen=True)
class EvalResult:
    """One engine evaluation of one position, in white's point of view.

    ``cp`` and ``mate`` are mutually exclusive: a mate score has no centipawn
    value and a centipawn score has no mate count. ``best_move`` is the engine's
    first move in UCI, and is ``None`` on a terminal position, where there is no
    move to play. ``depth`` is the depth the analysis was asked for, which is
    also the cache key, so a cached answer is indistinguishable from a fresh one.
    """

    cp: int | None
    mate: int | None
    best_move: str | None
    depth: int


class EngineService:
    """One Stockfish process for a run, with evaluations cached on disk.

    :param stockfish_path: the engine binary; defaults to what ``Config`` resolves.
    :param depth: the search depth every analysis asks for.
    :param cache_path: the sqlite cache file; defaults to
        ``<cache_dir>/evalcache.sqlite``.
    :param options: UCI options for the process, replacing
        :data:`DEFAULT_ENGINE_OPTIONS` when given. The defaults make a run
        reproducible rather than fast, so passing your own may cost that.

    Use it as a context manager so the process is always quit::

        with EngineService(path, depth, cache) as engine:
            best = engine.analyse(fen)

    ``hits`` and ``misses`` count calls answered from the cache and by the
    engine; the report header prints their ratio as the run's cache hit rate.
    Engine access is serialised: UCI is one conversation, so concurrent callers
    take a turn. The counters are plain attributes guarded by that same lock.
    """

    def __init__(
        self,
        stockfish_path: str | Path | None = None,
        depth: int = DEFAULT_ANALYSIS_DEPTH,
        cache_path: str | Path | None = None,
        *,
        options: Mapping[str, str] | None = None,
    ) -> None:
        config = Config()
        path = stockfish_path if stockfish_path is not None else config.stockfish_path
        self.stockfish_path = str(path)
        if depth < 1:
            raise ValueError(f"depth must be at least 1, got {depth!r}")
        self.depth = int(depth)
        cache = cache_path if cache_path is not None else config.evalcache_path
        self.cache_path = Path(cache).expanduser()
        if options is None:
            self.options: dict[str, str] = dict(DEFAULT_ENGINE_OPTIONS)
        else:
            self.options = dict(options)

        self.hits = 0
        self.misses = 0

        self._lock = threading.Lock()
        self._engine: chess.engine.SimpleEngine | None = None
        self._conn: sqlite3.Connection | None = None

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> EngineService:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"EngineService(stockfish_path={self.stockfish_path!r}, depth={self.depth}, "
            f"cache_path={str(self.cache_path)!r}, hits={self.hits}, misses={self.misses}, "
            f"engine_running={self.engine_running})"
        )

    # -- engine and cache state ---------------------------------------------

    @property
    def engine_running(self) -> bool:
        """Whether a Stockfish process is currently launched.

        False for a service that has not needed the engine yet, which is what a
        run whose positions are all cached looks like from start to finish.
        """
        return self._engine is not None

    @property
    def cache_hit_rate(self) -> float:
        """``hits / (hits + misses)``, or 0.0 when nothing was analysed."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def close(self) -> None:
        """Quit the engine, if one was launched, and close the cache file.

        Safe to call twice, and safe to call on a service that never launched an
        engine or never opened the cache. Stockfish also exits when its stdin
        closes, so a forgotten service cannot outlive the process that launched
        it, but only closing frees those threads during a long run.
        """
        with self._lock:
            engine, self._engine = self._engine, None
            conn, self._conn = self._conn, None
        if engine is not None:
            engine.quit()
        if conn is not None:
            conn.close()

    # -- analysis ------------------------------------------------------------

    def analyse(self, fen: str) -> EvalResult:
        """Evaluate a position, from the cache when it can and from Stockfish when not.

        ``fen`` is a full FEN as ``board.fen()`` writes it; the cache key is its
        ``position_key``, so move counters do not split one position into two
        entries - and neither do they move the answer, because the search itself
        is done on the counters cleared (see :func:`_search_position`). A malformed
        FEN raises ``ValueError`` before anything is cached. Raises
        :class:`EngineError` if the engine answers without a score.

        Two calls for one position and depth answer identically, in one process
        or two, and whether or not a hundred other positions were searched around
        it first. That is this service's own doing — a ``ucinewgame`` before
        every search, one thread by default — and callers rely on it: the cache
        freezes the first answer and replays it, and the report quotes the number.
        """
        board = chess.Board(fen)
        key = position_key(board.fen())

        with self._lock:
            cached = self._read(key)
            if cached is not None:
                self.hits += 1
                return cached
            self.misses += 1
            result = self._evaluate(board)
            self._write(key, result)
            return result

    # -- internals -----------------------------------------------------------

    def _evaluate(self, board: chess.Board) -> EvalResult:
        """One position, decided by the board if the game is over, else by the engine."""
        terminal = _terminal_result(board, self.depth)
        if terminal is not None:
            return terminal

        # The board the engine is asked about is the board the key names, so the
        # answer a cache row freezes is a property of the position.
        board = _search_position(board)

        engine = self._engine_handle()
        # ucinewgame before the search, not after the last one: a stale
        # transposition table is an earlier position's opinion of this one, and
        # the engine answers with it. Both lines go out under self._lock, so no
        # other caller can slip a position in between the reset and the search.
        # SimpleEngine has no public ucinewgame, and its game= argument would
        # block forever on a position that is not a game, so the line goes out on
        # the protocol directly.
        engine.protocol.send_line(_RESET_LINE)
        info = engine.analyse(board, chess.engine.Limit(depth=self.depth))
        score = info.get("score")
        if score is None:
            raise EngineError(f"engine returned no score for {board.fen()}: {info!r}")

        pov_white = getattr(score, "white", None)
        if pov_white is None:
            raise EngineError(
                f"engine returned {score!r}, which is not a PovScore; without .white() there "
                f"is no white point of view to read for {board.fen()}"
            )
        # The one place the side-to-move score becomes white's. severity.py's
        # to_my_pov() is the one place it becomes the player's.
        white = pov_white()

        pv = info.get("pv") or ()
        best_move = pv[0].uci() if len(pv) else None
        if white.is_mate():
            # A mate score has no centipawn value, and the two are exclusive.
            return EvalResult(cp=None, mate=white.mate(), best_move=best_move, depth=self.depth)
        return EvalResult(cp=white.score(), mate=None, best_move=best_move, depth=self.depth)

    def _engine_handle(self) -> chess.engine.SimpleEngine:
        """The engine process, launched on first use and reused after that."""
        if self._engine is None:
            # popen_uci takes no options (its extra keywords go to the
            # subprocess), so UCI options are configured once the handshake is
            # done, which is how python-chess's own examples do it.
            engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
            try:
                engine.configure(self.options)
            except Exception:
                engine.quit()
                raise
            self._engine = engine
        return self._engine

    def _connection(self) -> sqlite3.Connection:
        """The cache file, opened and migrated on first use."""
        if self._conn is None:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            # One connection shared by the caller's threads, hence
            # check_same_thread=False: every use is under self._lock.
            conn = sqlite3.connect(
                self.cache_path, timeout=_SQLITE_BUSY_TIMEOUT, check_same_thread=False
            )
            conn.execute(_CREATE_EVALS)
            conn.commit()
            self._conn = conn
        return self._conn

    def _read(self, key: str) -> EvalResult | None:
        sql = "SELECT cp, mate, best_move FROM evaluations WHERE position = ? AND depth = ?"
        row = self._connection().execute(sql, (key, self.depth)).fetchone()
        if row is None:
            return None
        cp, mate, best_move = row
        return EvalResult(cp=cp, mate=mate, best_move=best_move, depth=self.depth)

    def _write(self, key: str, result: EvalResult) -> None:
        conn = self._connection()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO evaluations (position, depth, cp, mate, best_move)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, self.depth, result.cp, result.mate, result.best_move),
            )


def _search_position(board: chess.Board) -> chess.Board:
    """The position as the engine is asked about it: the key, with no move counters.

    ``position_key`` is the first four FEN fields and Stockfish reads its
    ``rule50`` out of the halfmove clock, so a board handed over with its counters
    is a *different search* from the same board reached at another move count:
    measured on this host at depth 12, one real opening position scored cp
    43/34/38/30/33/38/37 across halfmove 0/1/2/3/4/10/49, with the best move
    changing from ``...d6`` to ``...Nxe4`` at halfmove 4. The cache key has always
    been the position without the counters, so the row it froze held whichever
    clock arrived first, and a score was a property of a route rather than of a
    position. Searching the counter-free board makes the promise true instead of
    merely documented: the board sent to the engine *is* the key, so transposition
    reuse costs nothing and no cache row can disagree with another.

    An opening window sits nowhere near the fifty-move rule, so clearing the clock
    is free; and it is cleared here rather than in ``analyse``, after
    ``_terminal_result`` has read the real clock, so the seventy-five-move rule is
    still answered from the board.
    """
    position = board.copy(stack=False)
    position.halfmove_clock = 0
    position.fullmove_number = 1
    return position


def _terminal_result(board: chess.Board, depth: int) -> EvalResult | None:
    """The evaluation of a finished position, or ``None`` if the game is still on.

    A position with no legal move, or one that is objectively drawn, needs no
    engine: the answer is in the board. Only claims-based endings (the fifty-move
    and threefold rules) are excluded, because the player need never make the
    claim and the game continues.
    """
    if board.is_checkmate():
        # Mated now: from either side's point of view this is mate zero, which
        # is why the design record can leave the sign out of the contract.
        return EvalResult(cp=None, mate=0, best_move=None, depth=depth)
    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
    ):
        return EvalResult(cp=0, mate=None, best_move=None, depth=depth)
    return None
