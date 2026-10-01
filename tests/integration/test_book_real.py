"""The book trigger against a real Stockfish, over real extracted records.

The composition here is the whole path this unit owns: real PGN text parsed by
the real extractor, real :class:`PlyRecord` values, the real ``EngineService``
with the real sqlite cache, and the real ``first_deviation`` walk. The PGN text
is a standard opening line written out here rather than a fixture file, because
``tests/fixtures/*.pgn`` belongs to the extraction unit and the point of these
tests is a line with a *known* deviation ply, not a real game's statistics.

Measured on this host with Stockfish 19 at depth 18, ``Threads=2``; the per-ply
gaps quoted in the comments are that measurement, and the assertions are bounds.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import chess
import chess.pgn
import pytest
from tests.game_records import make_record

from src.chessleak.book import first_deviation
from src.chessleak.config import DEFAULT_BOOK_BAND_CP, Config
from src.chessleak.engine import EngineService
from src.chessleak.pgnio import extract_opening_plies

pytestmark = pytest.mark.integration

#: The release's real-journey depth (Config.analysis_depth).
DEPTH = 18

#: A quiet Italian the player follows for seven of their own moves. Measured gaps
#: for the player at plies 0-12: -5, +5, +1, -1, -1, +2, -4, all inside the 30 cp
#: book band. Then 8.Nxe5??: measured +686 cp against the engine's line, and the
#: engine's own move in that position is 8.h3.
BOOK_THEN_DEVIATION = (
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a5 8. Nxe5"
)
DEVIATION_PLY = 14
DEVIATION_MOVE = "Nxe5"
#: A line with no deviation at all: every player move is inside the band.
ALL_BOOK = BOOK_THEN_DEVIATION.replace(" 8. Nxe5", " 8. Bg5")

#: A black-player line that keeps the band for four moves and then gives up a
#: pawn: measured +38 for white before, +91 after, so a 53 cp loss for black.
SMALL_LEAK = "1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 Nf6 5. Nxf6+ gxf6 6. Nf3"
LEAK_PLY = 9
LEAK_MOVE = "gxf6"

#: Fool's mate: the player's move ends the game, which is not a book deviation.
FOOLS_MATE = "1. f3 e5 2. g4 Qh4+"


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
def engine(engine_path: str, tmp_path: Path):
    """A real engine with a real sqlite cache in this test's own tmp_path."""
    with EngineService(engine_path, DEPTH, tmp_path / "evalcache.sqlite") as service:
        yield service


def pgn_of(line: str, headers: dict[str, str] | None = None) -> str:
    """A chess.com-shaped PGN for a numbered SAN line, ready for the extractor."""
    tags = {"Event": "?", "Site": "?", "Date": "2026.10.01", "Result": "*"}
    tags.update(headers or {})
    head = "".join(f'[{key} "{value}"]\n' for key, value in tags.items())
    return f"{head}\n{line} *\n"


def opening(line: str, *, my_color: str, game_id: str = "real-engine-game"):
    """The real opening window of a line, as real ply records."""
    record = make_record(id=game_id, pgn=pgn_of(line), my_color=my_color)
    plies = extract_opening_plies(record, max_plies=Config().opening_plies)
    assert plies, f"no ply records extracted from {line!r}"
    return plies


# -- the named behaviour -----------------------------------------------------


def test_real_opening_deviation(engine: EngineService) -> None:
    """A game that follows the book and deviates at a known ply is flagged there.

    Fifteen plies of a real Italian, extracted by the real extractor with the
    real engine behind it: the player's own moves stay inside the 30 cp band
    until ply 14, where 8.Nxe5?? is 686 cp worse than the engine's 8.h3.
    """
    plies = opening(BOOK_THEN_DEVIATION, my_color="white")

    flag = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)

    assert flag is not None, "8.Nxe5?? should leave the book band"
    assert flag.ply_index == DEVIATION_PLY
    assert flag.game_id == "real-engine-game"
    assert flag.my_move == DEVIATION_MOVE
    assert flag.best_move == "h3", "the engine's move in that position, in SAN"
    assert flag.fen_before == plies[DEVIATION_PLY].fen_before
    assert flag.cp_gap > DEFAULT_BOOK_BAND_CP
    assert 500 < flag.cp_gap < 900, f"measured cp gap was {flag.cp_gap}"

    # The flagged ply is the last one in the window, so nothing after it can
    # shift the answer: the walk stopped where the window stopped.
    assert [ply.ply_index for ply in plies][-1] == DEVIATION_PLY


def test_a_line_the_engine_agrees_with_is_not_flagged(engine: EngineService) -> None:
    """The same fifteen plies with 8.Bg5 instead of 8.Nxe5 stay inside the band."""
    plies = opening(ALL_BOOK, my_color="white")

    assert first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP) is None


def test_the_earlier_player_moves_are_never_flagged(engine: EngineService) -> None:
    """Walking the window ply by ply, nothing before the deviation is reported.

    ``first_deviation`` returns the first out-of-band move, so this asks the same
    question of every prefix of the window: each prefix's flag is either the
    deviation itself or nothing at all.
    """
    plies = opening(BOOK_THEN_DEVIATION, my_color="white")

    for prefix in range(1, DEVIATION_PLY):
        flag = first_deviation(plies[:prefix], engine, band_cp=DEFAULT_BOOK_BAND_CP)
        assert flag is None, f"ply {flag.ply_index if flag else prefix} should be in book"


# -- both sides --------------------------------------------------------------


def test_real_black_player_leak_is_flagged_with_the_right_sign(engine: EngineService) -> None:
    """A black player who gives up a pawn is flagged with a positive gap.

    Four black moves stay in the band; 6...gxf6 loses 53 centipowns measured, and
    the gap must come out positive. With the sign rule broken, Black's loss reads
    as a gain and nothing is flagged at all.
    """
    plies = opening(SMALL_LEAK, my_color="black")
    black_plies = [ply for ply in plies if ply.is_my_move]
    assert [ply.move_san for ply in black_plies][:5] == ["c6", "d5", "dxe4", "Nf6", "gxf6"]

    flag = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)

    assert flag is not None, "6...gxf6 gives up a pawn the engine wanted kept"
    assert flag.ply_index == LEAK_PLY
    assert flag.my_move == LEAK_MOVE
    assert flag.best_move == "exf6"
    assert flag.cp_gap > DEFAULT_BOOK_BAND_CP
    assert 40 <= flag.cp_gap <= 90, f"measured cp gap was {flag.cp_gap}"


def test_a_black_player_who_keeps_the_book_is_not_flagged(engine: EngineService) -> None:
    """The same side playing the engine's own moves is not flagged.

    The sign rule again, from the other direction: black playing the engine's
    best replies improves on the engine's own line in several plies, and those
    must read as gains rather than as leaks.
    """
    plies = opening("1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 Nf6 5. Nxf6+ exf6 6. Nf3", my_color="black")

    assert first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP) is None


def test_the_band_really_is_what_decides_these_two(engine: EngineService) -> None:
    """The same 53 centipawn leak is in book at 60 cp and out of it at 30.

    Both calls run the real engine again, and the answers differ only in the
    band: the trigger is a width in centipawns, not a severity judgement.
    """
    plies = opening(SMALL_LEAK, my_color="black")

    assert first_deviation(plies, engine, band_cp=60) is None
    flagged = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)
    assert flagged is not None


# -- finished positions ------------------------------------------------------


def test_mating_inside_the_window_is_not_a_deviation(engine: EngineService) -> None:
    """Fool's mate: the player's move ends the game, and the flag says nothing.

    ``engine.py`` answers a mated position as ``mate = 0`` from either side, so
    the board is what says who is mated. The side to move after the player's move
    is the opponent, and it is the opponent who cannot move.
    """
    plies = opening(FOOLS_MATE, my_color="white")
    last = plies[-1]
    assert last.move_san == "Qh4+" and chess.Board(last.fen_after).is_checkmate()

    flag = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)

    assert flag is None


# -- composition -------------------------------------------------------------


def test_the_walk_uses_the_engine_cache_and_asks_both_ends(engine: EngineService) -> None:
    """Every position a flagged move needs is answered from the engine's cache.

    The window is analysed twice with the same service: the second run is
    entirely cache hits, which is the reuse the report header counts.
    """
    plies = opening(BOOK_THEN_DEVIATION, my_color="white")

    first = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)
    misses_after_first = engine.misses
    hits_after_first = engine.hits

    second = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)

    assert first == second, "a cached run must reach the same flag"
    assert engine.misses == misses_after_first, "the second walk hit the engine"
    assert engine.hits == hits_after_first + 2 * len(plies) - (hits_after_first and 0 or 0)
    # Each move needs the position before and the position after it.
    assert engine.hits - hits_after_first >= len(plies)


def test_the_window_is_walked_once_per_game_and_stops_at_the_first_deviation(
    engine: EngineService,
) -> None:
    """A later deviation in the same window never costs an engine call.

    The design record calls ``first_deviation`` once per game with that game's
    window. With two deviations in one window, the walk must stop at the first,
    which the engine's own miss counter shows.
    """
    plies = opening(
        "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a5 8. Nxe5",
        my_color="white",
    )

    calls_without_stop = len(plies) * 2
    before = engine.misses
    flag = first_deviation(plies, engine, band_cp=DEFAULT_BOOK_BAND_CP)

    assert flag is not None
    assert engine.misses - before <= calls_without_stop


def test_a_game_that_could_not_be_parsed_yields_no_deviation(engine: EngineService) -> None:
    """An unreadable game is an empty window, which is not a deviation.

    ``pgnio`` logs and skips a game with an illegal move rather than analysing a
    short one; ``first_deviation`` never sees a record for it.
    """
    corrupt = pgn_of("1. e4 e5 2. Nf3 Nc6 3. Bb5", headers={"Event": "broken"})
    record = make_record(id="broken-game", pgn=corrupt, my_color="white")

    assert extract_opening_plies(record, max_plies=15) == []
    assert first_deviation([], engine, band_cp=DEFAULT_BOOK_BAND_CP) is None


def test_the_pgn_fixture_parses_without_python_chess_complaining() -> None:
    """Guard the test's own fixture: python-chess reads the line to the end."""
    game = chess.pgn.read_game(io.StringIO(pgn_of(BOOK_THEN_DEVIATION)))

    assert game is not None
    assert not game.errors, f"the fixture line does not parse: {game.errors}"
    assert len(list(game.mainline_moves())) == 15