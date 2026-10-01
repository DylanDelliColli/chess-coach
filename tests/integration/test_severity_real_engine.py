"""Severity against a real Stockfish: real positions, real evaluations, no mocks.

The engine binary is the one ``Config`` resolves to, launched by the real
``EngineService``, and every figure in the assertions is the engine's own output
at the release's own depth. Where a fixture claims a move hung a piece, the test
plays the engine's own reply and asks the board whether the piece is gone, so
"hanging piece" is evidence rather than a description.

Measured on this host with Stockfish 19 at depth 18, ``Threads=2``; the numbers
in the comments are that measurement and the assertions are written as bounds,
not as equalities, so a different build of the same engine cannot make them lie.
"""

from __future__ import annotations

import os
from pathlib import Path

import chess
import pytest

from src.chessleak.config import Config
from src.chessleak.engine import EngineService, EvalResult
from src.chessleak.severity import BLUNDER, INACCURACY, OK, cp_to_winprob, move_severity

pytestmark = pytest.mark.integration

#: The release's real-journey depth (Config.analysis_depth). Twelve positions at
#: this depth is about four seconds on this host, so the suite can afford it.
DEPTH = 18

#: 1.e4 e5 2.Bc4 Nf6, white to move. Measured: +18, engine's best 3.Nc3.
ITALIAN_FEN = "rnbqkb1r/pppp1ppp/5n2/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 2 3"
#: 3.Qh5?? hangs the queen; the engine answers 3...Nxh5 and is a pawn up.
HANG_THE_QUEEN = "d1h5"

#: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.Ng5, black to move. Measured: +18 for white.
TWO_KNIGHTS_FEN = "rnbqkb1r/pppp1ppp/2n2n2/4p1N1/2B1P3/8/PPPP1PPP/RNBQK2R b KQkq - 5 4"
#: 4...Nh5?? hangs the knight on h5; the engine answers 5.Qxh5.
HANG_THE_KNIGHT = "f6h5"

#: 1.e4 c6 2.d4 d5 3.Nc3 dxe4 4.Nxe4 Nf6 5.Nxf6+ gxf6, black to move. This is the
#: habitual small leak the book trigger exists for: measured +38 for white, so a
#: 53 centipawn loss for black, worth a 0.052 win-probability drop.
CARO_KANN_FEN = "rnbqkb1r/pp2pppp/2p2N2/8/3P4/8/PPP2PPP/R1BQKBNR b KQkq - 0 5"
LEAVE_THE_PAWN = "g7f6"

#: White to move, Qd8# is the only mate in one.
MATE_IN_ONE_FEN = "7k/6pp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"

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


@pytest.fixture
def engine(engine_path: str, tmp_path: Path):
    """A real engine with a real sqlite cache in this test's own tmp_path."""
    with EngineService(engine_path, DEPTH, tmp_path / "evalcache.sqlite") as service:
        yield service


def material(board: chess.Board, color: chess.Color) -> int:
    """Piece values on the board, one side's total."""
    return sum(
        PIECE_VALUES[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.color == color
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
    assert chess.QUEEN not in [p.piece_type for p in punished.piece_map().values()]
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
    """
    before = engine.analyse(ITALIAN_FEN)
    assert before.best_move is not None
    best = before.best_move

    after = play(ITALIAN_FEN, best)
    severity = move_severity(before, engine.analyse(after.fen()), "white")

    assert severity.klass == OK
    assert severity.winprob_drop == pytest.approx(0.0, abs=1e-9)
    assert severity.cp_loss <= 10, f"the best move cost {severity.cp_loss} cp"


# -- both sides --------------------------------------------------------------


def test_real_black_player_hanging_piece_is_a_blunder(engine: EngineService) -> None:
    """Black who hangs a piece loses win probability, from black's point of view.

    4...Nh5?? walks the knight onto h5, where 5.Qxh5 wins it. Both arguments are
    white's point of view, exactly as ``engine.py`` returns them, so this test is
    the one that fails if the conversion to the player's side is missing: black
    would then read as winning.
    """
    before = engine.analyse(TWO_KNIGHTS_FEN)
    after = play(TWO_KNIGHTS_FEN, HANG_THE_KNIGHT)
    after_evaluation = engine.analyse(after.fen())

    assert san_of(TWO_KNIGHTS_FEN, HANG_THE_KNIGHT) == "Nh5"
    assert san_of(after.fen(), after_evaluation.best_move or "") == "Qxh5"
    punished = after.copy(stack=False)
    punished.push_uci(after_evaluation.best_move or "")
    assert chess.KNIGHT not in [
        p.piece_type for p in punished.piece_map().values() if p.color == chess.BLACK
    ]

    severity = move_severity(before, after_evaluation, "black")

    assert severity.klass == BLUNDER
    assert severity.winprob_drop >= 0.30
    assert severity.winprob_drop == pytest.approx(
        as_player(before, chess.BLACK) - as_player(after_evaluation, chess.BLACK), abs=1e-9
    )
    assert severity.winprob_drop == pytest.approx(0.457, abs=0.02)


def test_real_black_player_improving_move_is_not_a_drop(engine: EngineService) -> None:
    """Black playing the engine's best move has no drop at all.

    The measured POV trap: on a black-to-move board ``score.relative`` is ``+38``
    where ``score.white()`` is ``-38``, so a run that read the relative score
    would report this move as a 76 centipawn loss for the player who improved.
    """
    before = engine.analyse(CARO_KANN_FEN)
    assert before.best_move is not None
    best = before.best_move

    after = play(CARO_KANN_FEN, best)
    after_evaluation = engine.analyse(after.fen())
    severity = move_severity(before, after_evaluation, "black")

    assert severity.klass == OK
    assert severity.winprob_drop == 0.0
    assert severity.cp_loss == 0, (
        f"the engine's own move for black read as a {severity.cp_loss} cp loss"
    )
    # The same two evaluations read as *white's* are not evidence of a black gain
    # either: the drop is signed by the player's side, once.
    assert severity.winprob_drop == max(
        0.0,
        as_player(before, chess.BLACK) - as_player(after_evaluation, chess.BLACK),
    )


# -- the small habitual leak, and what it is worth ---------------------------


def test_real_habitual_leak_is_a_book_flag_but_not_a_severity_event(engine: EngineService) -> None:
    """A 53 centipawn leak leaves the book band and still classifies ``ok``.

    This is the behaviour the product is built on - recurring small deviations are
    habitual leaks worth surfacing - measured against the operator's own
    thresholds: 53 centipawns is a 0.052 win-probability drop, below the 0.07
    inaccuracy line. Open question Q3 on the release bead is exactly whether that
    is the scale the operator wants; this test is the evidence either way.
    """
    before = engine.analyse(CARO_KANN_FEN)
    after = play(CARO_KANN_FEN, LEAVE_THE_PAWN)
    after_evaluation = engine.analyse(after.fen())

    assert san_of(CARO_KANN_FEN, LEAVE_THE_PAWN) == "gxf6"
    gap = -(before.cp or 0) - -(after_evaluation.cp or 0)

    assert gap > 30, f"the leak must be outside the 30 cp book band, measured {gap}"
    assert 40 <= gap <= 90, f"the fixture is a small leak, measured {gap} cp"

    severity = move_severity(before, after_evaluation, "black")

    assert severity.cp_loss == gap
    assert severity.klass in (OK, INACCURACY)
    assert severity.klass == OK, (
        "with win_prob_k = 0.004 a 53 cp error is below the 0.07 inaccuracy line; "
        f"it classified {severity.klass!r} with a drop of {severity.winprob_drop:.3f}"
    )
    assert severity.winprob_drop == pytest.approx(0.052, abs=0.01)


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


def test_real_terminal_position_after_the_move_is_a_full_blunder(engine: EngineService) -> None:
    """Mating inside the window is a finished position, and scores as the record says.

    The engine answers the position after Qd8# from the board, with no search:
    ``mate = 0, cp = None`` and no best move. ``move_severity`` short-circuits to
    a whole pawn of win probability without needing one, which is the frozen
    contract in the design record.
    """
    before = engine.analyse(MATE_IN_ONE_FEN)
    assert before.mate == 1 and before.best_move == "d1d8"

    mated = play(MATE_IN_ONE_FEN, before.best_move or "")
    assert mated.is_checkmate()
    after_evaluation = engine.analyse(mated.fen())

    assert (after_evaluation.cp, after_evaluation.mate, after_evaluation.best_move) == (
        None,
        0,
        None,
    )

    severity = move_severity(before, after_evaluation, "white")

    assert severity.winprob_drop == 1.0
    assert severity.klass == BLUNDER


def test_real_mate_score_scores_as_a_whole_win(engine: EngineService) -> None:
    """A mate for the player is win probability 1.0, so giving it up is a blunder.

    The mirror of the line above: from the same mating position, a quiet move
    instead of Qd8# throws the whole pawn of win probability away, not just the
    centipawn gap.
    """
    before = engine.analyse(MATE_IN_ONE_FEN)
    assert before.mate == 1

    walked_away = play(MATE_IN_ONE_FEN, "d1h5")  # Qh5: legal, and gives up the mate
    after_evaluation = engine.analyse(walked_away.fen())
    assert after_evaluation.mate is None, "the fixture only works if the mate is gone"

    severity = move_severity(before, after_evaluation, "white")

    assert severity.winprob_drop == pytest.approx(1.0 - as_player(after_evaluation, chess.WHITE))
    assert severity.winprob_drop >= 0.45
    assert severity.klass == BLUNDER