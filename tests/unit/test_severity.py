"""Severity: the win-probability curve, the one perspective conversion, the classes.

Everything here is arithmetic and real types. ``EvalResult`` is the real class
``engine.py`` returns, and the sign rule is exercised against real python-chess
colour values rather than a stand-in, because the sign rule is the bug the PRD
names: an engine score is always *white's* point of view, and converting it to
the player's happens exactly once, in :func:`to_my_pov`.

Thresholds are the operator's written values (0.07 / 0.15 / 0.30 win-probability
drop at ``win_prob_k = 0.004``) held as named constants, because open question Q3
on the release bead asks whether the conventional centipawn bands (50/100/200)
should replace them. If the answer is "centipawns", these constants and the tests
that pin them change; nothing structural does. :func:`test_scale_is_the_operators_scale`
records what the current scale means in centipawns.
"""

from __future__ import annotations

import math

import chess
import chess.engine as ce
import pytest

from src.chessleak.config import DEFAULT_WIN_PROB_K, Config
from src.chessleak.engine import EvalResult
from src.chessleak.severity import (
    BLUNDER,
    BLUNDER_DROP,
    INACCURACY,
    INACCURACY_DROP,
    MISTAKE,
    MISTAKE_DROP,
    OK,
    Severity,
    cp_to_winprob,
    move_severity,
    to_my_pov,
)

pytestmark = pytest.mark.unit

DEPTH = 18

#: A quiet opening evaluation and a hanging-piece one, white's point of view.
QUIET_WHITE = EvalResult(cp=25, mate=None, best_move="g1f3", depth=DEPTH)
QUIET_WHITE_BLACK = EvalResult(cp=25, mate=None, best_move="g8f6", depth=DEPTH)
LOST_WHITE = EvalResult(cp=-948, mate=None, best_move="f6h5", depth=DEPTH)


def eval_of_cp(cp: int, *, best_move: str | None = "g1f3", mate: int | None = None) -> EvalResult:
    """A white-perspective evaluation, built the way ``engine.py`` returns one."""
    return EvalResult(cp=cp, mate=mate, best_move=best_move, depth=DEPTH)


def cp_for_drop(drop: float, k: float = DEFAULT_WIN_PROB_K) -> float:
    """The centipawn value whose win probability is ``drop`` below an even game.

    An even position (``cp = 0``) wins with probability 0.5, so the value wanted
    is the logistic inverse of ``0.5 - drop``. Used to land test evaluations on a
    named boundary without hard-coding a number the engine has to reproduce.
    """
    target = 0.5 - drop
    return math.log(target / (1.0 - target)) / k


# -- the curve ---------------------------------------------------------------


def test_cp_to_winprob_monotonic_and_symmetric() -> None:
    """The curve rises with the centipawn value and is symmetric about even."""
    values = [-800, -400, -200, -100, -50, 0, 50, 100, 200, 400, 800]

    probabilities = [cp_to_winprob(cp) for cp in values]

    assert all(0.0 <= p <= 1.0 for p in probabilities), probabilities
    assert probabilities == sorted(probabilities), "not monotonic in cp"
    assert cp_to_winprob(0) == pytest.approx(0.5)
    for cp, probability in zip(values, probabilities, strict=True):
        assert probability + cp_to_winprob(-cp) == pytest.approx(1.0), (
            f"not symmetric at {cp} cp: {probability} + {cp_to_winprob(-cp)}"
        )


def test_cp_to_winprob_saturates_instead_of_overflowing() -> None:
    """An evaluation far outside the scale gives 1.0 or 0.0, not an OverflowError.

    ``math.exp(-k * cp)`` overflows for a mate-adjacent centipawn value, and this
    module runs inside the report path where an exception would lose the run.
    """
    assert cp_to_winprob(1_000_000) == 1.0
    assert cp_to_winprob(-1_000_000) == 0.0
    assert cp_to_winprob(200_000_000) == 1.0
    assert cp_to_winprob(-200_000_000) == 0.0


def test_cp_to_winprob_takes_the_configured_slope() -> None:
    """``k`` is the slope; ``Config.win_prob_k`` is its default."""
    assert DEFAULT_WIN_PROB_K == 0.004
    assert cp_to_winprob(100) == pytest.approx(cp_to_winprob(100, k=DEFAULT_WIN_PROB_K))
    # A steeper curve moves further from even for the same centipawn value.
    assert cp_to_winprob(100, k=0.02) > cp_to_winprob(100, k=0.004) > 0.5


# -- the perspective conversion ---------------------------------------------


def test_to_my_pov_negates_for_black_and_keeps_the_move() -> None:
    """Black's view is white's negated; the best move does not change hands."""
    white = eval_of_cp(120, best_move="g1f3")

    black = to_my_pov(white, chess.BLACK)

    assert black.cp == -120
    assert black.best_move == "g1f3", "the engine move is a move, not a side"
    assert black.depth == DEPTH


def test_to_my_pov_negates_a_mate_count() -> None:
    """``mate`` counts plies, so it flips with the point of view: +1 becomes -1."""
    white_mates_in_one = EvalResult(cp=None, mate=1, best_move="d1d8", depth=DEPTH)

    black_view = to_my_pov(white_mates_in_one, "black")

    assert black_view.mate == -1
    assert black_view.cp is None, "a mate score has no centipawn value"


def test_to_my_pov_accepts_the_colour_either_way_a_caller_holds_it() -> None:
    """``chess.Color``, ``True``/``False`` and ``"white"``/``"black"`` all work.

    ``fetch.GameRecord.my_color`` is chess.com's own string and ``pgnio`` works in
    ``chess.Color``, so the conversion has to take either without a caller
    translating at every call site.
    """
    evaluation = eval_of_cp(80)

    assert to_my_pov(evaluation, "white") == evaluation
    assert to_my_pov(evaluation, "WHITE") == evaluation
    assert to_my_pov(evaluation, chess.WHITE) == evaluation
    assert to_my_pov(evaluation, True) == evaluation
    assert to_my_pov(evaluation, "black").cp == -80
    assert to_my_pov(evaluation, "  black ").cp == -80
    assert to_my_pov(evaluation, chess.BLACK).cp == -80
    assert to_my_pov(evaluation, False).cp == -80


def test_to_my_pov_rejects_a_colour_it_cannot_name() -> None:
    """A colour nobody can classify is an error, not a guess."""
    with pytest.raises(ValueError, match="colour"):
        to_my_pov(eval_of_cp(10), "purple")


def test_to_my_pov_leaves_a_finished_position_alone() -> None:
    """A mated position is mate zero from either side's point of view."""
    mated = EvalResult(cp=None, mate=0, best_move=None, depth=DEPTH)

    assert to_my_pov(mated, chess.BLACK).mate == 0
    assert to_my_pov(mated, chess.WHITE).mate == 0


# -- the classes -------------------------------------------------------------


def test_classification_thresholds() -> None:
    """A drop of 0.07 is an inaccuracy, 0.15 a mistake, 0.30 a blunder.

    Each boundary is probed from both sides at one centipawn resolution, so the
    test states which class a value on the boundary gets rather than how close
    to it a sample happened to land.
    """
    thresholds = [
        (INACCURACY_DROP, INACCURACY, OK),
        (MISTAKE_DROP, MISTAKE, INACCURACY),
        (BLUNDER_DROP, BLUNDER, MISTAKE),
    ]

    for threshold, at_threshold, below_threshold in thresholds:
        boundary = cp_for_drop(threshold)
        assert boundary != math.floor(boundary), (
            f"{threshold} lands on a whole centipawn; the probe below would "
            f"compare a value with itself"
        )
        worse = math.floor(boundary)  # further from even, so a larger drop
        better = math.ceil(boundary)

        assert move_severity(eval_of_cp(0), eval_of_cp(worse), chess.WHITE).klass == at_threshold
        assert (
            move_severity(eval_of_cp(0), eval_of_cp(better), chess.WHITE).klass == below_threshold
        )


def test_scale_is_the_operators_scale() -> None:
    """What the operator's written thresholds mean in centipawns, for Q3.

    With ``win_prob_k = 0.004``, a blunder needs roughly a 3.5-pawn loss and a
    100 centipawn error is an inaccuracy. That is the finding open question Q3 on
    the release bead asks about; this test is the evidence, so changing a
    threshold forces a decision here rather than a silent drift.
    """
    scale = {
        50: OK,
        100: INACCURACY,
        200: MISTAKE,
        350: BLUNDER,
    }

    for centipawns, expected in scale.items():
        severity = move_severity(eval_of_cp(0), eval_of_cp(-centipawns), chess.WHITE)
        assert severity.klass == expected, (
            f"{centipawns} cp classified {severity.klass!r}, not {expected!r} "
            f"(drop {severity.winprob_drop:.3f})"
        )


def test_severity_reports_the_centipawn_loss_and_the_drop() -> None:
    """``cp_loss`` is the centipawn difference; ``winprob_drop`` is the loss curve."""
    severity = move_severity(eval_of_cp(40), eval_of_cp(-360), chess.WHITE)

    assert isinstance(severity, Severity)
    assert severity.cp_loss == 400
    assert severity.winprob_drop == pytest.approx(cp_to_winprob(40) - cp_to_winprob(-360))
    assert severity.klass == BLUNDER
    assert 0.0 <= severity.winprob_drop <= 1.0


def test_a_move_that_holds_the_position_is_ok() -> None:
    """Replaying the engine's own best move costs nothing."""
    severity = move_severity(QUIET_WHITE, eval_of_cp(25), chess.WHITE)

    assert severity.klass == OK
    assert severity.winprob_drop == pytest.approx(0.0)
    assert severity.cp_loss == 0


def test_a_move_that_improves_is_never_a_drop() -> None:
    """An improvement reads as zero, never as a negative or positive drop.

    The engine is not omniscient, so a player's move can beat its own best line.
    A negative drop would poison the cluster average; a positive one would mean
    the sign rule is broken.
    """
    severity = move_severity(eval_of_cp(-30), eval_of_cp(60), chess.WHITE)

    assert severity.winprob_drop == 0.0
    assert severity.klass == OK
    assert severity.cp_loss == 0


# -- the sign rule, from both sides -----------------------------------------


def test_a_black_player_who_loses_a_piece_loses_win_probability() -> None:
    """White's evaluation improving is Black's evaluation falling.

    The evaluation is white-perspective in both arguments, exactly as
    ``engine.py`` returns it, so this test fails if the conversion is applied
    twice or not at all: with the sign left alone, a black player who hangs a
    queen would read as a *gain*.
    """
    best = eval_of_cp(-10, best_move="d7d5")
    after_blunder = eval_of_cp(880, best_move="h7h5")

    for evaluation in (move_severity(best, after_blunder, "black"),):
        assert evaluation.klass == BLUNDER
        assert evaluation.winprob_drop == pytest.approx(
            cp_to_winprob(10) - cp_to_winprob(-880), abs=0.01
        )
        assert evaluation.cp_loss == 890


def test_a_black_player_who_improves_has_no_drop() -> None:
    """The mirror image: Black improving reads as zero, not as a mistake.

    This is the exact failure the PRD names. With the conversion applied inside
    ``move_severity`` twice (once here, once in the caller), Black's improving
    move would read as a fall in win probability and be reported as a mistake.
    """
    best = eval_of_cp(20)  # white is slightly better
    after = eval_of_cp(-60)  # white got worse, so Black got better

    severity = move_severity(best, after, "black")

    assert severity.winprob_drop == 0.0
    assert severity.klass == OK
    assert severity.cp_loss == 0


def test_both_colours_agree_on_a_hanging_piece() -> None:
    """The same position scored for each side gives the same class.

    Mirrored evaluations, one per colour, are the same story told twice: a
    player who hangs a piece loses win probability whichever piece is theirs.
    """
    as_white = move_severity(eval_of_cp(10), eval_of_cp(-900), chess.WHITE)
    as_black = move_severity(eval_of_cp(-10), eval_of_cp(900), chess.BLACK)

    assert as_white.klass == as_black.klass == BLUNDER
    assert as_white.winprob_drop == pytest.approx(as_black.winprob_drop, abs=0.01)
    assert as_white.cp_loss == as_black.cp_loss


# -- mate and terminal positions --------------------------------------------


def test_a_mate_score_for_the_player_is_a_full_win() -> None:
    """A mate score maps to +/-1.0, inside ``move_severity`` rather than the curve.

    ``cp_to_winprob`` is centipawn-only by contract; a mate score has no
    centipawn value, so the mapping belongs where the colour is known.
    """
    mate_for_me = EvalResult(cp=None, mate=1, best_move="d1d8", depth=DEPTH)

    severity = move_severity(mate_for_me, eval_of_cp(-30), chess.WHITE)

    assert severity.winprob_drop == pytest.approx(1.0 - cp_to_winprob(-30))
    assert severity.klass == BLUNDER


def test_mated_scores_as_whole_a_win_of_zero() -> None:
    """Mate against the player is win probability 0.0, so the drop is total."""
    mated = EvalResult(cp=None, mate=-1, best_move=None, depth=DEPTH)

    severity = move_severity(eval_of_cp(30), mated, chess.WHITE)

    assert severity.winprob_drop == pytest.approx(cp_to_winprob(30))
    assert severity.klass == BLUNDER


def test_a_terminal_position_after_the_move_is_a_blunder() -> None:
    """A finished position short-circuits without needing a best move.

    ``engine.py`` answers checkmate as ``mate = 0, cp = None`` and a draw as
    ``cp = 0``, and reports ``best_move = None`` in both cases. Scoring it as a
    whole pawn of win probability keeps the record's frozen contract: the
    position after the player's move is over, so nothing can be recovered.
    """
    checkmated = EvalResult(cp=None, mate=0, best_move=None, depth=DEPTH)
    drawn = EvalResult(cp=0, mate=None, best_move=None, depth=DEPTH)

    for terminal in (checkmated, drawn):
        severity = move_severity(QUIET_WHITE, terminal, chess.WHITE)
        assert severity.winprob_drop == 1.0
        assert severity.klass == BLUNDER
        assert severity.cp_loss == 25


def test_a_terminal_position_still_needs_no_best_move_in_the_first_argument() -> None:
    """A terminal first argument is scored without raising or guessing a move."""
    terminal = EvalResult(cp=0, mate=None, best_move=None, depth=DEPTH)

    severity = move_severity(terminal, eval_of_cp(0), chess.WHITE)

    assert severity.klass == OK
    assert severity.winprob_drop == 0.0


# -- configuration -----------------------------------------------------------


def test_the_slope_is_configurable_without_touching_the_thresholds() -> None:
    """``k`` moves the curve; the class boundaries stay where the operator put them.

    The same centipawn loss reads as a bigger fall on a steeper curve, which is
    how Q3's "keep the win-probability thresholds and lower ``k``" answer would be
    applied: these constants do not move, ``Config.win_prob_k`` does.
    """
    hundred_cp = eval_of_cp(-100)

    at_default = move_severity(eval_of_cp(0), hundred_cp, chess.WHITE)
    at_four_times = move_severity(eval_of_cp(0), hundred_cp, chess.WHITE, k=0.016)

    assert at_default.klass == INACCURACY
    assert at_four_times.klass == BLUNDER
    assert at_four_times.winprob_drop > at_default.winprob_drop
    assert Config().win_prob_k == DEFAULT_WIN_PROB_K

    # The centipawn value that sits on the boundary moves with the slope, so the
    # class a run reports does not drift when only k changes.
    for k in (DEFAULT_WIN_PROB_K, 0.016):
        boundary = round(cp_for_drop(BLUNDER_DROP, k=k))
        at_boundary = move_severity(eval_of_cp(0), eval_of_cp(boundary), chess.WHITE, k=k)
        assert at_boundary.klass == BLUNDER


# -- the real python-chess score types ---------------------------------------


def test_the_curve_matches_the_real_pov_score_sign_rule() -> None:
    """A real ``PovScore`` and a real ``EvalResult`` describe the same game.

    python-chess >= 1.10 hands ``SimpleEngine.analyse`` a side-to-move
    ``PovScore``, which is why ``engine.py`` reads ``.white()`` and why the
    conversion to the player's side is done once, here. Building the same score
    twice - once read white's way and once relative - is the measured trap.
    """
    board = chess.Board(chess.STARTING_FEN)
    board.push_uci("e2e4")
    assert board.turn == chess.BLACK, "the fixture needs a black-to-move board"

    # The engine's raw "score cp" is the side to move's, which is the shape the
    # UCI parser hands python-chess: a black-to-move board where white is +35
    # carries a side-to-move score of -35. Reading .relative() therefore returns
    # -35 and reading .white() returns +35, which is the sign rule the whole
    # release depends on. (The constructor's first argument is the score in the
    # second argument's point of view, so "white is +35 on a black-to-move
    # board" is PovScore(Cp(-35), BLACK), not PovScore(Cp(35), BLACK).)
    score = ce.PovScore(ce.Cp(-35), board.turn)

    assert score.white().score() == 35, "the fixture must read +35 as white"
    assert score.relative.score() == -35, "the side-to-move read sign-flips it"

    white = EvalResult(cp=score.white().score(), mate=None, best_move="g8f6", depth=DEPTH)

    assert to_my_pov(white, "black").cp == score.relative.score()
