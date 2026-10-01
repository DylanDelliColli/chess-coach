"""The eval cache: which position is one cache entry, and what never reaches the engine.

Only the engine *process* is replaced here, because this is a unit test and the
Prime Directive puts real composition in ``tests/integration/``. Everything this
unit owns is real: the sqlite cache on disk, ``position_key`` as the cache key,
the hit/miss counters, the lock that serialises engine access, and the real
python-chess types the engine protocol hands back (``PovScore``, ``Cp``,
``Mate``), because the white-POV rule is a property of those types.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path

import chess
import chess.engine as ce
import pytest

from src.chessleak.config import position_key
from src.chessleak.engine import DEFAULT_ENGINE_OPTIONS, EngineService, EvalResult

pytestmark = pytest.mark.unit

#: The start position, and the same position with different move counters (a
#: knight out and back leaves the board untouched and burns halfmoves).
START_FEN = chess.STARTING_FEN
START_LATE_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 4 40"

#: White to move, Qd8# is the only mate in one.
WHITE_MATE_IN_ONE = "7k/6pp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"
#: Black to move, the mirror image: Qd1# mates.
BLACK_MATE_IN_ONE = "3q2k1/5ppp/8/8/8/8/6PP/7K b - - 0 1"
#: Black to move and already mated: white has just played Qd8#.
WHITE_ALREADY_MATED = "3Q3k/6pp/8/8/8/8/5PPP/6K1 b - - 1 1"
#: Black to move with no legal move and no check: a draw, not a mate.
STALEMATE = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def key(fen: str) -> str:
    """The cache key the service derives from a FEN string.

    Keyed on the board python-chess builds rather than on the literal string, so
    a fixture FEN that spells the en passant field differently still finds its
    entry (the design record pins ``board.fen()``'s ``en_passant="legal"``
    normalisation as part of the key).
    """
    return position_key(chess.Board(fen).fen())


class FakeEngine:
    """Stands in for ``SimpleEngine``: canned answers, and a record of the calls.

    A reply is ``(score, first_pv_line)`` where the score is relative to the
    side to move, exactly as python-chess builds it
    (``PovScore(score, board.turn)``; see ``chess/engine.py``), and a ``None``
    principal variation means the engine returned no ``pv`` at all.
    """

    def __init__(self, replies: dict[str, tuple[ce.Score, list[str] | None]]) -> None:
        self.replies = replies
        self.path: str | None = None
        self.calls: list[tuple[str, int]] = []
        self.configured: list[tuple[str, str]] = []
        self.live = 0
        self.max_live = 0
        self.quit_calls = 0

    def analyse(self, board: chess.Board, limit: ce.Limit) -> dict:
        self.calls.append((board.fen(), limit.depth))
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        try:
            score, pv = self.replies[position_key(board.fen())]
            info: dict = {
                "score": ce.PovScore(score, board.turn),
                "depth": limit.depth,
            }
            if pv is not None:
                info["pv"] = [board.parse_uci(move) for move in pv]
            return info
        finally:
            self.live -= 1

    def configure(self, options: Mapping[str, str]) -> None:
        self.configured = list(options.items())

    def quit(self) -> None:
        self.quit_calls += 1


def install_engine(monkeypatch: pytest.MonkeyPatch, replies: dict) -> FakeEngine:
    """Replace the engine process factory and return the engine it will hand out."""
    fake = FakeEngine(replies)

    def fake_popen_uci(path: str, **kwargs: object) -> FakeEngine:
        fake.path = path
        return fake

    monkeypatch.setattr(ce.SimpleEngine, "popen_uci", staticmethod(fake_popen_uci))
    return fake


def service(tmp_path: Path, depth: int = 8, **kwargs: object) -> EngineService:
    """An EngineService over a throwaway cache file, with no real engine path needed."""
    kwargs.setdefault("stockfish_path", "unused-while-stubbed")
    cache = tmp_path / "evalcache.sqlite"
    return EngineService(kwargs.pop("stockfish_path"), depth, cache, **kwargs)


def test_cache_hit_skips_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The same position analysed twice runs the engine once (the bead's named test).

    Repeated opening positions are the reason this cache exists: 4,634 distinct
    position keys against 4,738 full FENs in one real month, so a run that
    re-encounters a position must not pay for it twice.
    """
    fake = install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), ["g1f3", "g1h3"])})

    with service(tmp_path) as eng:
        first = eng.analyse(START_FEN)
        second = eng.analyse(START_FEN)

    assert len(fake.calls) == 1, "the engine ran twice for one position and depth"
    assert (eng.misses, eng.hits) == (1, 1)
    assert second == first
    assert first == EvalResult(cp=31, mate=None, best_move="g1f3", depth=8)


def test_cache_key_is_the_position_not_the_move_counters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two routes to one position share one entry; the counters are not in the key."""
    fake = install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), ["g1f3"])})

    with service(tmp_path) as eng:
        eng.analyse(START_FEN)
        again = eng.analyse(START_LATE_FEN)

    assert (eng.misses, eng.hits) == (1, 1)
    assert len(fake.calls) == 1
    assert again.cp == 31


def test_depth_is_part_of_the_cache_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A deeper search of the same position is a different answer, so a miss."""
    fake = install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), ["g1f3"])})

    with service(tmp_path, depth=8) as shallow:
        shallow.analyse(START_FEN)
        shallow.analyse(START_FEN)
        with service(tmp_path, depth=12) as deeper:
            deeper.analyse(START_FEN)

    assert (deeper.misses, deeper.hits) == (1, 0), "a different depth must not read a shallower row"
    assert (shallow.misses, shallow.hits) == (1, 1)
    assert len(fake.calls) == 2


def test_scores_are_white_pov_whatever_the_side_to_move(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A black-to-move score is negated once, here, and nowhere else.

    python-chess returns the side-to-move point of view, so ``Cp(30)`` on a black
    board is ``-30`` for white. Reading the relative score instead would look
    correct on every white-to-move fixture and flip the sign on every black ply,
    which is exactly the bug the PRD names.
    """
    fake = install_engine(
        monkeypatch,
        {
            key(BLACK_MATE_IN_ONE): (ce.Cp(30), ["d8d1"]),
            key(WHITE_MATE_IN_ONE): (ce.Mate(1), ["d1d8"]),
        },
    )

    with service(tmp_path) as eng:
        black_cp = eng.analyse(BLACK_MATE_IN_ONE)
        white_mate = eng.analyse(WHITE_MATE_IN_ONE)

    assert fake.calls[0][0].split()[1] == "b"
    assert black_cp.cp == -30, "black-to-move centipawns must be negated for white"
    assert black_cp.mate is None
    assert black_cp.best_move == "d8d1"
    assert white_mate.mate == 1 and white_mate.cp is None, "cp and mate are exclusive"


def test_terminal_position_never_reaches_the_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A finished game is decided by the board, so no engine is launched for it.

    ``severity.move_severity`` short-circuits a terminal evaluation instead of
    needing a best move, which is what makes ``best_move=None`` here safe.
    """
    fake = install_engine(monkeypatch, {})

    with service(tmp_path) as eng:
        mated = eng.analyse(WHITE_ALREADY_MATED)
        drawn = eng.analyse(STALEMATE)
        assert eng.engine_running is False, "a terminal position must not launch the engine"
        assert (eng.misses, eng.hits) == (2, 0)
        # Terminal answers are cached too, so a recurring finish is free as well.
        assert eng.analyse(WHITE_ALREADY_MATED) == mated
        assert (eng.misses, eng.hits) == (2, 1)

    assert mated == EvalResult(cp=None, mate=0, best_move=None, depth=8)
    assert drawn == EvalResult(cp=0, mate=None, best_move=None, depth=8)
    assert fake.calls == []


def test_best_move_is_none_when_the_engine_returns_no_pv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No principal variation means no best move, and that is not an error."""
    install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), None)})

    with service(tmp_path) as eng:
        result = eng.analyse(START_FEN)

    assert result == EvalResult(cp=31, mate=None, best_move=None, depth=8)


def test_cache_survives_a_new_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A second service over the same file is served from disk, engine untouched."""
    first_engine = install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), ["g1f3"])})
    with service(tmp_path) as writer:
        written = writer.analyse(START_FEN)
    assert writer.engine_running is False, "closing the service quits the engine"
    assert first_engine.quit_calls == 1

    second_engine = install_engine(monkeypatch, {})
    with service(tmp_path) as reader:
        read = reader.analyse(START_FEN)
        assert reader.engine_running is False, "a cache hit must not launch the engine"
        assert (reader.misses, reader.hits) == (0, 1)

    assert read == written
    assert second_engine.calls == [], "the engine was launched for a cached position"


def test_engine_options_default_and_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Threads/Hash default to the design record's, and a caller can replace them."""
    fake = install_engine(monkeypatch, {key(START_FEN): (ce.Cp(31), ["g1f3"])})
    with service(tmp_path) as eng:
        eng.analyse(START_FEN)
    # UCI options are configured on the launched process, because popen_uci
    # hands every extra keyword to the subprocess rather than to the engine.
    assert dict(fake.configured) == dict(DEFAULT_ENGINE_OPTIONS) == {"Threads": "2", "Hash": "128"}

    with service(tmp_path, options={"Threads": "1", "Hash": "32"}) as custom:
        assert custom.options == {"Threads": "1", "Hash": "32"}


def test_unused_service_launches_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A run that hits the cache all the way through starts no process to quit."""
    fake = install_engine(monkeypatch, {})
    with service(tmp_path) as eng:
        assert eng.engine_running is False
    assert fake.quit_calls == 0


def _one_ply_positions(count: int) -> list[chess.Board]:
    """``count`` distinct positions, one per legal first move of either side."""
    positions: list[chess.Board] = []
    for board in (chess.Board(), chess.Board()):
        for move in board.legal_moves:
            after = board.copy(stack=False)
            after.push(move)
            positions.append(after)
            if len(positions) == count:
                return positions
    raise AssertionError("not enough distinct first-move positions")


def test_analysis_is_serialised(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """One engine, one caller at a time: UCI is a single conversation."""
    boards = _one_ply_positions(20)
    replies = {
        position_key(board.fen()): (ce.Cp(20), [next(iter(board.legal_moves)).uci()])
        for board in boards
    }
    fake = install_engine(monkeypatch, replies)
    fens = [board.fen() for board in boards]

    errors: list[BaseException] = []

    def worker(share: list[str]) -> None:
        try:
            for fen in share:
                eng.analyse(fen)
        except BaseException as exc:  # pragma: no cover - only on a real failure
            errors.append(exc)

    with service(tmp_path) as eng:
        shares = [fens[index::4] for index in range(4)]
        threads = [threading.Thread(target=worker, args=(share,)) for share in shares]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert errors == []
    assert len(fake.calls) == 20, "every distinct position must have reached the engine"
    assert fake.max_live == 1, "the engine was used by more than one caller at a time"
    assert (eng.misses, eng.hits) == (20, 0)


def test_invalid_fen_is_rejected_before_the_cache_is_touched(tmp_path: Path) -> None:
    """A malformed FEN fails as a bad position, not as a cache miss."""
    with service(tmp_path) as eng:
        with pytest.raises(ValueError):
            eng.analyse("this is not a fen")
        assert (eng.misses, eng.hits) == (0, 0)


def test_non_positive_depth_is_rejected(tmp_path: Path) -> None:
    """A depth of zero would key every position to a nonsense row."""
    with pytest.raises(ValueError):
        service(tmp_path, depth=0)
