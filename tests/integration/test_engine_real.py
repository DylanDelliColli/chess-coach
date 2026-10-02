"""Real Stockfish over UCI, behind the real EngineService, against a real sqlite file.

No mock, no stub and no fixture answer anywhere in this file: the engine binary
is launched from the path ``Config`` resolves to, the cache is a real database
in ``tmp_path``, and every assertion is checked against the engine's own output
(where a move is claimed to mate, the move is played and the board is asked).

Two engine searches of one position must give the same answer, and the tests
here take the service's own defaults rather than options of their own, because
that is the guarantee the rest of the release quotes: one thread, and a fresh
transposition table before every position. The order tests are what hold it in
place.
"""

from __future__ import annotations

import os
from pathlib import Path

import chess
import pytest

from src.chessleak.config import Config
from src.chessleak.engine import EngineService, EvalResult

pytestmark = pytest.mark.integration

#: White to move, Qd8# is the only mate in one.
WHITE_MATE_IN_ONE = "7k/6pp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"
#: Black to move, the mirror image: Qd1# mates.
BLACK_MATE_IN_ONE = "3q2k1/5ppp/8/8/8/8/6PP/7K b - - 0 1"

#: The start position, and the same position reached with different move counters.
START_FEN = chess.STARTING_FEN
START_LATE_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 4 40"

#: Deep enough to see a mate in one, shallow enough to keep the suite quick.
MATE_DEPTH = 10

#: Three positions along one real opening line (1. e4 c5 2. Nf3 Nc6 3. d4 cxd4
#: 4. Nxd4 Nf6 5. Nc3), written out so the order tests name the positions they
#: compare rather than re-deriving them from a PGN.
ORDER_POSITIONS = (
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "r1bqkb1r/pp1ppppp/2n5/2p5/4P3/5N2/PPPP1PPP/R1BQKB1R w KQkq - 2 3",
    "r1bqkb1r/1p1ppppp/p1n2n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6",
)
#: The depth the order tests search at. Shallow enough that six positions cost
#: about a second; deep enough that the carry-over a reset removes is plainly
#: visible. Measured here at depth 12 without the reset: 58 of 60 positions from
#: six real opening lines scored differently between the two search orders, and
#: at depth 18 the same 58 of 60. No assertion quotes any of those numbers: what
#: is asserted is that the two orders now agree.
ORDER_DEPTH = 12


@pytest.fixture(scope="module")
def engine_path() -> str:
    """The engine binary this repository's config resolves to."""
    path = Config.from_env().stockfish_path
    if not os.path.exists(path):
        pytest.fail(
            f"no Stockfish binary at {path!r}: run scripts/get_stockfish.sh, or point "
            f"CHESSLEAK_STOCKFISH_PATH at an existing binary"
        )
    return path


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    """A real sqlite file, thrown away with the test's tmp_path.

    Caches are per worker by convention: three workers writing one file is how
    ``database is locked`` happens.
    """
    return tmp_path / "evalcache.sqlite"


def test_mate_in_one(engine_path: str, cache_path: Path) -> None:
    """The engine's answer to a known mate in one is the mating move itself.

    White to move, so ``mate == 1`` holds under either point of view, which is
    why the black-side test below exists as well.
    """
    board = chess.Board(WHITE_MATE_IN_ONE)

    with EngineService(engine_path, MATE_DEPTH, cache_path) as engine:
        result = engine.analyse(WHITE_MATE_IN_ONE)

    assert result.mate == 1, f"expected mate in one, got {result!r}"
    assert result.cp is None, "a mate score has no centipawn value"
    assert result.best_move == "d1d8"
    assert result.depth == MATE_DEPTH

    after = board.copy(stack=False)
    after.push_uci(result.best_move or "")
    assert after.is_checkmate(), f"{result.best_move} does not mate"
    assert not list(after.legal_moves)


def test_mate_in_one_black_to_move_is_white_pov(engine_path: str, cache_path: Path) -> None:
    """Black mates in one, so from white's side it is mated: ``mate == -1``.

    python-chess reports the side-to-move point of view, so the raw answer here
    is ``+1``; the frozen contract is white's, and this test fails the moment
    anything reads the relative score instead.
    """
    board = chess.Board(BLACK_MATE_IN_ONE)
    assert board.turn == chess.BLACK

    with EngineService(engine_path, MATE_DEPTH, cache_path) as engine:
        result = engine.analyse(BLACK_MATE_IN_ONE)

    assert result.mate == -1, f"expected a white-POV mate in one, got {result!r}"
    assert result.best_move == "d8d1"

    after = board.copy(stack=False)
    after.push_uci(result.best_move or "")
    assert after.is_checkmate(), f"{result.best_move} does not mate"


def test_start_position_evaluates_and_picks_a_legal_move(
    engine_path: str, cache_path: Path
) -> None:
    """An ordinary position: a centipawn score and a move that is legal here."""
    board = chess.Board(START_FEN)

    with EngineService(engine_path, 12, cache_path) as engine:
        result = engine.analyse(START_FEN)

    assert result.mate is None
    assert isinstance(result.cp, int) and -100 < result.cp < 100, f"odd start position: {result!r}"
    assert result.best_move is not None
    move = chess.Move.from_uci(result.best_move)
    assert move in board.legal_moves, f"{result.best_move} is not legal in the start position"


def test_cache_persists_to_disk(engine_path: str, cache_path: Path) -> None:
    """A second run of the program reads the first run's answer off the disk.

    This is the speedup the whole pipeline rests on: the CLI opens one service
    per run and re-encounters positions across games, and a second invocation
    over an unchanged cache must not launch the engine at all.
    """
    with EngineService(engine_path, MATE_DEPTH, cache_path) as first:
        written = first.analyse(WHITE_MATE_IN_ONE)
        assert first.engine_running is True, "a cache miss must launch the engine"
        assert (first.misses, first.hits) == (1, 0)

    assert cache_path.exists(), f"the cache file was not written at {cache_path}"

    with EngineService(engine_path, MATE_DEPTH, cache_path) as second:
        read = second.analyse(WHITE_MATE_IN_ONE)
        assert second.engine_running is False, "a cache hit must not launch the engine"
        assert (second.misses, second.hits) == (0, 1)

    assert read == written
    assert read == EvalResult(cp=None, mate=1, best_move="d1d8", depth=MATE_DEPTH)


def test_transposed_position_is_one_cache_entry(engine_path: str, cache_path: Path) -> None:
    """Two FEN strings for one position are one entry, not two.

    The same board reached at a different move number has a different ``board.fen()``;
    keying the cache on it would re-analyse every transposition.
    """
    with EngineService(engine_path, 12, cache_path) as engine:
        first = engine.analyse(START_FEN)
        second = engine.analyse(START_LATE_FEN)

    assert (engine.misses, engine.hits) == (1, 1)
    assert first == second


def test_run_of_a_real_opening_reuses_cached_positions(engine_path: str, cache_path: Path) -> None:
    """Twenty plies of a real opening: the transposed lines collapse into hits.

    Mirrors what the CLI does over one game's opening window, at a depth that
    keeps the suite quick, and asserts the hit rate the report header prints.
    """
    openings = (
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7",
        "1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Nf3 Nc6 5. Bb5 a6 6. Ba4 Nf6 7. O-O Be7",
    )

    with EngineService(engine_path, 10, cache_path) as engine:
        seen: set[str] = set()
        for line in openings:
            board = chess.Board()
            for token in line.split():
                if token.rstrip(".").isdigit():
                    continue
                seen.add(board.fen())
                board.push(board.parse_san(token))
        for fen in sorted(seen):
            result = engine.analyse(fen)
            assert result.best_move is not None or result.mate == 0

        total = engine.hits + engine.misses
        # The two lines share their start position and reach the same middlegame
        # by transposition, so the second line is mostly hits.
        assert engine.hits > 0, f"no reuse at all: {engine.hits} hits, {engine.misses} misses"
        assert engine.hits / total > 0.4, f"cache hit rate {engine.hits / total:.2f} is too low"


def _analyse_in_order(
    engine_path: str, cache_path: Path, fens: tuple[str, ...]
) -> dict[str, EvalResult]:
    """Analyse these positions, in this order, in a service of their own.

    Each call gets its own cache file, so every position is a genuine engine
    search and never a cache hit: the question is what the engine answers, not
    what the disk already knew.
    """
    with EngineService(engine_path, ORDER_DEPTH, cache_path) as engine:
        results = {fen: engine.analyse(fen) for fen in fens}
        assert engine.engine_running is True, "the engine must actually have been searched"
        assert (engine.misses, engine.hits) == (len(fens), 0)
    return results


def test_a_position_scores_the_same_in_either_search_order(
    engine_path: str, tmp_path: Path
) -> None:
    """What was searched first must not change the score of what comes next.

    This is the property the whole report rests on. Stockfish keeps its hash
    between searches unless it is told otherwise, and python-chess's
    ``SimpleEngine`` does not tell it, so the position in the middle of a run once
    carried whatever the position before it had left behind: tens of centipawns,
    measured, against a book band of 30. ``EngineService`` sends ``ucinewgame``
    before every position, so a position's score is a property of that position.

    Two services, two orders over the same three positions, no numbers quoted:
    the engine decides both times and the two answers must agree.
    """
    forward = _analyse_in_order(engine_path, tmp_path / "forward.sqlite", ORDER_POSITIONS)
    backward = _analyse_in_order(
        engine_path, tmp_path / "backward.sqlite", tuple(reversed(ORDER_POSITIONS))
    )

    for fen in ORDER_POSITIONS:
        assert forward[fen] == backward[fen], (
            f"{fen} scored {forward[fen]} in one search order and {backward[fen]} in the "
            f"other; a score that depends on the order cannot be quoted or compared"
        )
        assert forward[fen].cp is not None, f"expected a centipawn score for {fen}"


def test_a_position_scores_the_same_in_a_fresh_process(engine_path: str, tmp_path: Path) -> None:
    """Two runs over the same positions agree, which is what the cache assumes.

    The eval cache freezes the first run's answer and replays it for the next
    month, so the answer has to be the one a later process would have computed.
    That also pins the default of one thread: a multi-threaded search is not
    reproducible even within a single process.
    """
    first = _analyse_in_order(engine_path, tmp_path / "first.sqlite", ORDER_POSITIONS)
    again = _analyse_in_order(engine_path, tmp_path / "again.sqlite", ORDER_POSITIONS)

    assert first == again
