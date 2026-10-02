"""Severity against a real Stockfish: real positions, real evaluations, no mocks.

The engine binary is the one ``Config`` resolves to, launched by the real
``EngineService``, and every figure in the assertions is the engine's own output
at the release's own depth. Where a fixture claims a move hung a piece, the test
plays the engine's own reply and asks the board whether the piece is gone, so
"hanging piece" is evidence rather than a description.

Measured on this host with Stockfish 19 at depth 18; the numbers in the comments
are that measurement and the assertions are written as bounds, not as equalities,
so a different build of the same engine cannot make them lie. Spot checks on
2026-10-02 (the severity band's move to centipowns) found some of the recorded
figures a few centipawns out - the Italian reads +2 rather than +18 and the
Caro-Kann leak 73 cp rather than 56 - which is the reason for the bounds. Where a
figure decides a class, the difference is recorded at the fixture.

The search itself is the service's default: one thread, and a ``ucinewgame``
before every position. Both are there for the same reason, which is that a test
whose assertions *are* measurements needs a search that answers the same way
twice. Multi-threaded search is not reproducible even within one analysis (on
this host the same position at depth 18 came back as +1, 0, +13 and -2 cp with
two different best moves across four processes), and an engine that is not reset
between positions carries its transposition table from one into the next, which
moves a score by tens of centipawns. ``ENGINE_OPTIONS`` below spells the default
out rather than inheriting it, so what this file measures is visible in the file.
"""

from __future__ import annotations

import os
from pathlib import Path

import chess
import pytest

from src.chessleak.config import Config
from src.chessleak.engine import EngineService, EvalResult
from src.chessleak.severity import (
    BLUNDER,
    INACCURACY,
    INACCURACY_CP,
    MISTAKE,
    OK,
    cp_to_winprob,
    move_severity,
)

pytestmark = pytest.mark.integration

#: The operator's centipawn bands, ruled 2026-10-02, written out here rather
#: than imported. The tests below check real engine numbers against this copy of
#: the rule, so they cannot be satisfied by a ``severity.py`` that classifies
#: however it likes: ``ok`` under 50, inaccuracy from 50, mistake from 100,
#: blunder from 200.
RULED_CP_BANDS = ((200, BLUNDER), (100, MISTAKE), (50, INACCURACY))


def band_of(cp_loss: int) -> str:
    """The class the ruled bands give a centipawn loss, restated for this file."""
    for threshold, klass in RULED_CP_BANDS:
        if cp_loss >= threshold:
            return klass
    return OK


#: The release's real-journey depth (Config.analysis_depth). Twelve positions at
#: this depth is about four seconds on this host, so the suite can afford it.
DEPTH = 18

#: 1.e4 e5 2.Bc4 Nf6, white to move. Measured: +18, engine's best 3.Nc3.
ITALIAN_FEN = "rnbqkb1r/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3"
#: 3.Qh5?? hangs the queen; the engine answers 3...Nxh5 and is a pawn up.
HANG_THE_QUEEN = "d1h5"

#: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.Ng5, black to move. Measured: +23, engine's best
#: 4...d5. The b8 knight is on c6 in this position, so rank 8 starts "r1bqkb1r": a
#: FEN that also keeps a knight on b8 holds 33 pieces, and Stockfish refuses such
#: a position outright ("CRITICAL ERROR: ... More than 32 pieces on the board")
#: and exits, which killed the engine mid-test instead of failing an assertion.
TWO_KNIGHTS_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 5 4"
#: 4...Nh5?? hangs the knight on h5; the engine answers 5.Qxh5.
HANG_THE_KNIGHT = "f6h5"
#: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.O-O, black to move. Measured: +17 for white,
#: the engine's best 4...Nf6. 4...Qh4?? walks the queen onto h4, where the
#: knight on f3 takes it and nothing defends it; the engine answers 5.Nxh4.
HANG_THE_QUEEN_BLACK_FEN = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1 b kq - 5 4"
HANG_THE_QUEEN_BLACK = "d8h4"

#: 1.e4 c6 2.d4 d5 3.Nc3 dxe4 4.Nxe4 Nf6 5.Nxf6+ gxf6, black to move. This is the
#: habitual small leak the book trigger exists for: 56 centipawns of loss as U5
#: measured it (+37 for white before, +93 after), 73 on the 2026-10-02
#: re-measurement (+16 and +89). Both are outside the 30 cp book band and both are
#: an inaccuracy under the operator's 2026-10-02 centipawn bands; under the
#: superseded 2026-06-05 win-probability thresholds the same loss was a 0.055-0.072
#: drop and stayed ``ok``.
CARO_KANN_FEN = "rnbqkb1r/pp2pppp/2p2N2/8/3P4/8/PPP2PPP/R1BQKBNR b KQkq - 0 5"
LEAVE_THE_PAWN = "g7f6"

#: The same opening with the quiet mainline move as the leak: 2.Nf3 measured
#: costs 49 centipawns of the engine's line (51 on the 2026-10-02
#: re-measurement), the smallest leak this file could find that is still outside
#: the 30 cp book band. It sits within a centipawn or two of the ruled 50 cp
#: inaccuracy line - where the superseded 2026-06-05 thresholds put it at about
#: 72 cp - so the test that uses it checks the class against the band rather than
#: against a fixed label.
QUIET_LEAK_FEN = ITALIAN_FEN
QUIET_LEAK_MOVE = "g1f3"

#: 3.Bb5, the Ruy Lopez, in the same position: measured 130 centipawns of loss
#: against the engine's line, identical across three repeats and after a warm
#: transposition table on this host. It is a real mistake-band fixture rather than
#: a synthetic one, and a revealing one: 130 cp is a move any player would call
#: reasonable, which is the whole point of the ruled bands over the win-probability
#: scale that called the same 130 cp an inaccuracy (its mistake line was ~159 cp).
MISTAKE_LEAK_MOVE = "c4b5"

#: White to move, Qd8# is the only mate in one. Both sides keep a queen, so the
#: position is level apart from the mate - which is what makes the mate worth a
#: whole pawn of win probability against a half one. (A position that is already a
#: queen up cannot show that: there the mate is only the 0.025 between 0.975 and
#: 1.0, and the old fixture of this file measured exactly that.)
MATE_IN_ONE_FEN = "3q3k/6pp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}


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


#: The options this file searches with, which are the service's own defaults:
#: one thread, so every measurement above is reproducible. See the module
#: docstring.
ENGINE_OPTIONS = {"Threads": "1", "Hash": "128"}


@pytest.fixture
def engine(engine_path: str, tmp_path: Path):
    """A real engine with a real sqlite cache in this test's own tmp_path."""
    with EngineService(
        engine_path, DEPTH, tmp_path / "evalcache.sqlite", options=ENGINE_OPTIONS
    ) as service:
        yield service


def material(board: chess.Board, color: chess.Color) -> int:
    """Piece values on the board, one side's total, kings excluded."""
    return sum(
        PIECE_VALUES[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.color == color and piece.piece_type in PIECE_VALUES
    )


def play(fen: str, *moves: str) -> chess.Board:
    """The board reached by playing UCI moves from a FEN."""
    board = chess.Board(fen)
    for move in moves:
        board.push_uci(move)
    return board


def san_of(fen: str, uci: str) -> str:
    """The SAN of a UCI move in the position it was chosen in."""
    return chess.Board(fen).san(chess.Move.from_uci(uci))


def as_player(evaluation: EvalResult, color: chess.Color) -> float:
    """The evaluation's win probability from one side's point of view."""
    assert evaluation.cp is not None
    if color == chess.WHITE:
        return cp_to_winprob(evaluation.cp)
    return 1.0 - cp_to_winprob(evaluation.cp)


def _mirror(evaluation: EvalResult) -> EvalResult:
    """The same evaluation with white and black exchanged, still white's score."""
    cp = None if evaluation.cp is None else -evaluation.cp
    mate = None if evaluation.mate is None else -evaluation.mate
    return EvalResult(cp=cp, mate=mate, best_move=evaluation.best_move, depth=DEPTH)


# -- the named behaviour -----------------------------------------------------


def test_real_blunder_detected(engine: EngineService) -> None:
    """A real hanging piece in the opening is classified ``blunder``.

    3.Qh5?? leaves the queen attacked by the knight on f6 with nothing defending
    it. The engine's own answer, 3...Nxh5, is the proof: it is a capture, and
    after it plays, the queen is off the board and white is a full queen down.
    """
    before = engine.analyse(ITALIAN_FEN)
    after = play(ITALIAN_FEN, HANG_THE_QUEEN)
    after_evaluation = engine.analyse(after.fen())

    assert before.cp is not None and before.cp > 0, "the fixture must start level-ish"
    assert san_of(ITALIAN_FEN, HANG_THE_QUEEN) == "Qh5"
    assert after_evaluation.best_move == "f6h5", (
        "the fixture's premise is that the queen hangs; the engine's answer is "
        f"{after_evaluation.best_move!r}"
    )
    assert san_of(after.fen(), after_evaluation.best_move or "") == "Nxh5"

    punished = after.copy(stack=False)
    punished.push_uci(after_evaluation.best_move or "")
    assert chess.QUEEN not in [
        p.piece_type for p in punished.piece_map().values() if p.color == chess.WHITE
    ], "white's queen is the one that was hanging; black still has its own"
    assert material(punished, chess.BLACK) - material(punished, chess.WHITE) >= 900

    severity = move_severity(before, after_evaluation, "white")

    assert severity.klass == BLUNDER, (
        f"hanging the queen should be a blunder, got {severity.klass!r} with a "
        f"drop of {severity.winprob_drop:.3f}"
    )
    assert severity.winprob_drop >= 0.30
    assert severity.cp_loss >= 900
    assert severity.winprob_drop == pytest.approx(
        as_player(before, chess.WHITE) - as_player(after_evaluation, chess.WHITE), abs=1e-9
    )


def test_real_quiet_best_move_is_ok(engine: EngineService) -> None:
    """Playing the engine's own best move in the same position costs nothing.

    The other half of the acceptance: the same position, the same engine, the
    best move rather than the blunder, and the classification is ``ok``.

    "Costs nothing" is a scale, not an identity. The engine scores a position by
    the value of its own best line at that depth, and the position *after* that
    line is searched independently, so the two can differ by a few centipawns -
    measured 11 cp for 3.Nc3 in the Italian. What has to hold is that the move is
    nowhere near the 50 centipawn inaccuracy line, and that the clamp at zero is
    what keeps an improvement from being reported as a gain.
    """
    before = engine.analyse(ITALIAN_FEN)
    assert before.best_move is not None
    best = before.best_move

    after = play(ITALIAN_FEN, best)
    after_evaluation = engine.analyse(after.fen())
    severity = move_severity(before, after_evaluation, "white")

    assert severity.klass == OK
    assert severity.cp_loss < INACCURACY_CP, (
        f"the engine's own best move cost {severity.cp_loss} cp, at or above the "
        f"{INACCURACY_CP} cp inaccuracy line"
    )
    assert severity.winprob_drop == pytest.approx(
        as_player(before, chess.WHITE) - as_player(after_evaluation, chess.WHITE), abs=1e-9
    )
    assert severity.cp_loss <= 20, f"the best move cost {severity.cp_loss} cp"


# -- both sides --------------------------------------------------------------


def test_real_black_player_hanging_piece_is_a_blunder(engine: EngineService) -> None:
    """Black who hangs a piece loses win probability, from black's point of view.

    4...Qh4?? puts the queen where the knight on f3 takes it. Both arguments are
    white's point of view, exactly as ``engine.py`` returns them, so this test is
    the one that fails if the conversion to the player's side is missing: black
    would then read as winning.
    """
    before = engine.analyse(HANG_THE_QUEEN_BLACK_FEN)
    after = play(HANG_THE_QUEEN_BLACK_FEN, HANG_THE_QUEEN_BLACK)
    after_evaluation = engine.analyse(after.fen())

    assert san_of(HANG_THE_QUEEN_BLACK_FEN, HANG_THE_QUEEN_BLACK) == "Qh4"
    assert san_of(after.fen(), after_evaluation.best_move or "") == "Nxh4"
    punished = after.copy(stack=False)
    punished.push_uci(after_evaluation.best_move or "")
    assert chess.QUEEN not in [
        p.piece_type for p in punished.piece_map().values() if p.color == chess.BLACK
    ], "the engine's own answer takes the queen, so the hang is real"
    assert material(punished, chess.WHITE) - material(punished, chess.BLACK) >= 900

    severity = move_severity(before, after_evaluation, "black")

    assert severity.klass == BLUNDER
    assert severity.winprob_drop >= 0.30
    assert severity.winprob_drop == pytest.approx(
        as_player(before, chess.BLACK) - as_player(after_evaluation, chess.BLACK), abs=1e-9
    )
    assert severity.winprob_drop == pytest.approx(0.462, abs=0.02)


def test_real_black_player_improving_move_is_not_a_drop(engine: EngineService) -> None:
    """Black playing the engine's best move has no drop at all.

    The measured POV trap: on a black-to-move board ``score.relative`` is ``+38``
    where ``score.white()`` is ``-38``, so a run that read the relative score
    would report this move as a 76 centipawn loss for the player who improved.
    Measured 2 centipawns here, which is the engine's own noise (see
    test_real_quiet_best_move_is_ok), nowhere near the 50 centipawn line.
    """
    before = engine.analyse(CARO_KANN_FEN)
    assert before.best_move is not None
    best = before.best_move

    after = play(CARO_KANN_FEN, best)
    after_evaluation = engine.analyse(after.fen())
    severity = move_severity(before, after_evaluation, "black")

    assert severity.klass == OK
    assert severity.cp_loss < INACCURACY_CP
    assert severity.cp_loss <= 20, (
        f"the engine's own move for black read as a {severity.cp_loss} cp loss"
    )
    # The same two evaluations read as *white's* are not evidence of a black gain
    # either: the drop is signed by the player's side, once.
    # The player's win probability is 1 - the white figure, and move_severity
    # reaches the same number by negating the centipowns first; the two routes
    # agree to sixteen digits and no further.
    assert severity.winprob_drop == pytest.approx(
        max(
            0.0,
            as_player(before, chess.BLACK) - as_player(after_evaluation, chess.BLACK),
        ),
        abs=1e-9,
    )


# -- the small habitual leak, and what it is worth ---------------------------


def test_real_habitual_leak_is_a_book_flag_and_its_class_is_the_ruled_band(
    engine: EngineService,
) -> None:
    """A habitual small leak leaves the book band; its class is the band's answer.

    1.e4 e5 2.Bc4 Nf6, white to move: the engine plays 3.Nc3 (measured +2 for
    white), and the mainline 2.Nf3 leaves the position at -47 - a 49 centipawn
    leak, outside the 30 cp book band. This is the behaviour the product is built
    on: recurring small deviations are habitual leaks worth surfacing.

    What the class *is* depends on the operator's 2026-10-02 ruling and on the
    number the engine actually returns, and this fixture sits on the line: 49 cp
    is measured one centipawn below the 50 cp inaccuracy band, where the
    superseded 2026-06-05 win-probability thresholds put it at about 72 cp. So
    the assertion is the class the ruled bands give the measured loss, read
    against :func:`band_of` in this file rather than against ``severity.py``'s own
    constants. Hard-coding "ok" here would assert a coin flip: a real engine's
    figure for a position moves by a few centipawns, and 50 is an inaccuracy.
    """
    before = engine.analyse(QUIET_LEAK_FEN)
    after = play(QUIET_LEAK_FEN, QUIET_LEAK_MOVE)
    after_evaluation = engine.analyse(after.fen())

    assert san_of(QUIET_LEAK_FEN, QUIET_LEAK_MOVE) == "Nf3"
    gap = (before.cp or 0) - (after_evaluation.cp or 0)

    assert gap > 30, f"the leak must be outside the 30 cp book band, measured {gap}"
    assert 30 <= gap <= 60, f"the fixture is a small leak, measured {gap} cp"

    severity = move_severity(before, after_evaluation, "white")

    assert severity.cp_loss == gap
    assert severity.klass == band_of(gap), (
        f"a {gap} cp leak classified {severity.klass!r}; the ruled bands give "
        f"{band_of(gap)!r} below, 50 is an inaccuracy, 100 a mistake"
    )
    assert severity.klass in (OK, INACCURACY), (
        f"the fixture is a small leak, so the band can only answer {OK!r} or "
        f"{INACCURACY!r}, not {severity.klass!r}"
    )
    assert severity.winprob_drop == pytest.approx(0.049, abs=0.015)


def test_real_engine_classes_follow_the_ruled_centipawn_bands(engine: EngineService) -> None:
    """Every real position in this file is classified by its own centipawn loss.

    The bands are checked against the real engine's numbers at the release's
    depth rather than against synthetic ones: a hanging queen is 900+ centipowns
    of real loss, the engine's own best move is a handful, and the two small leaks
    sit either side of the inaccuracy line. :func:`band_of` is this file's own
    copy of the operator's 2026-10-02 rule, so the assertion cannot be satisfied
    by a ``severity.py`` that classifies the way it likes.

    The mate positions are not in the table: giving up a mate is a blunder by
    itself, with no centipawn loss to read, and the two tests above cover that
    case directly.
    """
    cases = [
        (ITALIAN_FEN, HANG_THE_QUEEN, "white"),
        (TWO_KNIGHTS_FEN, HANG_THE_KNIGHT, "black"),
        (HANG_THE_QUEEN_BLACK_FEN, HANG_THE_QUEEN_BLACK, "black"),
        (CARO_KANN_FEN, LEAVE_THE_PAWN, "black"),
        (ITALIAN_FEN, MISTAKE_LEAK_MOVE, "white"),
        (QUIET_LEAK_FEN, QUIET_LEAK_MOVE, "white"),
    ]

    seen: set[str] = set()
    for fen, uci, color in cases:
        before = engine.analyse(fen)
        after = play(fen, uci)
        severity = move_severity(before, engine.analyse(after.fen()), color)
        seen.add(severity.klass)

        assert severity.klass == band_of(severity.cp_loss), (
            f"{san_of(fen, uci)} costs {severity.cp_loss} cp and classified "
            f"{severity.klass!r}; the ruled bands give {band_of(severity.cp_loss)!r}"
        )

    # The engine's own best move in two of the same positions, for the ``ok`` end
    # of the table: the best move in a position the fixture already scores as an
    # inaccuracy has to stay ``ok``, or the band would be reading something other
    # than the player's error.
    for fen, color in ((ITALIAN_FEN, "white"), (CARO_KANN_FEN, "black")):
        before = engine.analyse(fen)
        assert before.best_move is not None
        severity = move_severity(before, engine.analyse(play(fen, before.best_move).fen()), color)
        seen.add(severity.klass)
        assert severity.klass == band_of(severity.cp_loss) == OK

    assert len(seen) >= 2, f"the fixtures must cover more than one class, saw {seen}"
    assert {BLUNDER, MISTAKE, INACCURACY, OK} <= seen, f"the table missed a class, saw {seen}"


def test_a_real_mistake_band_error_is_a_mistake(engine: EngineService) -> None:
    """3.Bb5 in the Italian costs 130 centipawns and is classified ``mistake``.

    The middle of the ruled bands, on a real engine's own numbers: the losing a
    piece fixture above is far past 200 cp, and the best-move fixtures are far
    below 50, so without this the mistake band would only ever be pinned against
    synthetic evaluations.

    It is also the clearest statement of what the operator's ruling changed. The
    same 130 centipawns is a 0.127 win-probability drop, which on the superseded
    2026-06-05 scale is an *inaccuracy* (that scale needed about 159 cp for a
    mistake). The move is the same move either way; the label now matches what a
    chess player would call it.
    """
    before = engine.analyse(ITALIAN_FEN)
    after = play(ITALIAN_FEN, MISTAKE_LEAK_MOVE)
    severity = move_severity(before, engine.analyse(after.fen()), "white")

    assert san_of(ITALIAN_FEN, MISTAKE_LEAK_MOVE) == "Bb5"
    assert severity.klass == MISTAKE, (
        f"measured {severity.cp_loss} cp of loss, which the ruled bands give "
        f"{band_of(severity.cp_loss)!r}"
    )
    assert severity.klass == band_of(severity.cp_loss)
    assert 0.0 <= severity.winprob_drop <= 1.0, "the report's Win% lost is still computed"


def test_the_pieces_of_a_drop_add_up(engine: EngineService) -> None:
    """The reported drop is exactly the two win probabilities, in the player's view.

    Checked over every fixture position in this file rather than once, so a sign
    that leaks in one direction cannot hide behind another.
    """
    cases = [
        (ITALIAN_FEN, HANG_THE_QUEEN, "white"),
        (TWO_KNIGHTS_FEN, HANG_THE_KNIGHT, "black"),
        (CARO_KANN_FEN, LEAVE_THE_PAWN, "black"),
    ]

    for fen, uci, color in cases:
        before = engine.analyse(fen)
        after = play(fen, uci)
        after_evaluation = engine.analyse(after.fen())
        player = chess.WHITE if color == "white" else chess.BLACK

        severity = move_severity(before, after_evaluation, color)

        expected = max(0.0, as_player(before, player) - as_player(after_evaluation, player))
        assert severity.winprob_drop == pytest.approx(expected, abs=1e-9), color

        # The same figure in the other colour is the mirror image, never a new
        # number: negating the evaluations negates the drop's direction.
        mirrored = move_severity(
            _mirror(before),
            _mirror(after_evaluation),
            "black" if color == "white" else "white",
        )
        assert mirrored.winprob_drop == pytest.approx(expected, abs=1e-9), color


# -- mates and finished positions -------------------------------------------


@pytest.mark.parametrize("color", ["white", "black"])
def test_real_delivered_mate_is_the_win_it_is(engine: EngineService, color: str) -> None:
    """Mating inside the window is a finished position, and it is the player's win.

    The engine answers the position after Qd8# from the board, with no search:
    ``mate = 0, cp = None`` and no best move. The side to move in that position is
    the opponent, so the mate zero is the *player's* mate - the two sides are
    run through the same assertions, because a delivered mate reads as
    ``mate = 0`` from either side and that is exactly what used to turn it into a
    hundred percent loss.

    The move played is the engine's own best move in both cases, which is what
    makes this the wrong-way-round verdict rather than a close call: the player
    found the engine's line and ended the game in it.
    """
    fen = MATE_IN_ONE_FEN if color == "white" else chess.Board(MATE_IN_ONE_FEN).mirror().fen()

    before = engine.analyse(fen)
    assert before.best_move is not None
    expected_mate = 1 if color == "white" else -1
    assert before.mate == expected_mate

    mated = play(fen, before.best_move)
    assert mated.is_checkmate()
    assert mated.turn != chess.Board(fen).turn, "the opponent is the side to move after the move"
    after_evaluation = engine.analyse(mated.fen())

    assert (after_evaluation.cp, after_evaluation.mate, after_evaluation.best_move) == (
        None,
        0,
        None,
    )

    severity = move_severity(before, after_evaluation, color)

    assert severity.cp_loss == 0
    assert severity.winprob_drop == 0.0
    assert severity.klass == OK


def test_real_a_position_still_ends_the_window_without_a_best_move(engine: EngineService) -> None:
    """A finish is scored from the board's own answer, with no move to ask for.

    The property the terminal short-circuit was written for, kept on the corrected
    reading: ``engine.py`` reports ``best_move = None`` for a checkmate and for a
    draw, and ``move_severity`` scores both without needing one.
    """
    before = engine.analyse(MATE_IN_ONE_FEN)
    mated = play(MATE_IN_ONE_FEN, before.best_move or "")
    after_evaluation = engine.analyse(mated.fen())
    assert after_evaluation.best_move is None

    severity = move_severity(before, after_evaluation, "white")

    assert severity.winprob_drop < 1.0, "the player delivered this mate, not received it"
    assert severity.klass != BLUNDER


def test_real_mate_score_scores_as_a_whole_win(engine: EngineService) -> None:
    """A mate for the player is win probability 1.0, so giving it up is a blunder.

    The mirror of the line above: from the same mating position, a quiet move
    instead of Qd8# throws the whole pawn of win probability away, not just the
    centipawn gap. This is the direction that stays a blunder, and it is the one
    a report must not lose when the delivered-mate case above is repaired.

    The class here is the mate rule's verdict rather than the centipawn bands'
    (measured 0 cp of loss after Qh5 - a mate score has no centipawn value, so
    the bands alone would read this as ``ok``). That is the one case the ruled
    bands cannot reach, and it is a real engine's answer rather than a fixture's.
    """
    before = engine.analyse(MATE_IN_ONE_FEN)
    assert before.mate == 1

    walked_away = play(MATE_IN_ONE_FEN, "d1h5")  # Qh5: legal, and gives up the mate
    after_evaluation = engine.analyse(walked_away.fen())
    assert after_evaluation.mate is None, "the fixture only works if the mate is gone"
    # Qh5 walks away from a mate in one and leaves an ordinary, roughly level
    # position. The band is 40 cp rather than a tight one: before the engine sent
    # `ucinewgame` between positions, this number came out of whatever was left in
    # the transposition table by the mate search above, so a tight bound only held
    # by accident. What this test is about is that *giving up the mate* costs the
    # whole of the win probability, which the assertions below pin.
    assert abs(after_evaluation.cp or 0) <= 40, (
        f"the fixture needs Qh5 to leave the position roughly level, measured {after_evaluation.cp}"
    )

    severity = move_severity(before, after_evaluation, "white")

    assert severity.winprob_drop == pytest.approx(1.0 - as_player(after_evaluation, chess.WHITE))
    assert severity.winprob_drop >= 0.45
    assert severity.cp_loss < INACCURACY_CP, (
        f"the fixture leaves no centipawn loss to read, measured {severity.cp_loss}"
    )
    assert severity.klass == BLUNDER
