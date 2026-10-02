"""Severity: the win-probability curve, the one perspective conversion, the classes.

Everything here is arithmetic and real types. ``EvalResult`` is the real class
``engine.py`` returns, and the sign rule is exercised against real python-chess
colour values rather than a stand-in, because the sign rule is the bug the PRD
names: an engine score is always *white's* point of view, and converting it to
the player's happens exactly once, in :func:`to_my_pov`.

The class boundaries are **centipawn** bands - 50 / 100 / 200, ``ok`` below the
first - ruled by the operator on 2026-10-02. They supersede the operator's
2026-06-05 win-probability thresholds (0.07 / 0.15 / 0.30 at
``win_prob_k = 0.004``), which on the real curve meant roughly 70 / 155 / 347 cp
and so called almost nothing a mistake. Win probability is still computed, still
carried on :class:`Severity` and still shown by the report; it is a display
figure now, not the classifier, which is why the tests below pin the bands in
centipawns and pin ``k``'s effect on the *drop* separately from the class.
"""

from __future__ import annotations

import chess
import chess.engine as ce
import pytest

from src.chessleak.config import DEFAULT_WIN_PROB_K, Config
from src.chessleak.engine import EvalResult
from src.chessleak.severity import (
    BLUNDER,
    BLUNDER_CP,
    INACCURACY,
    INACCURACY_CP,
    MISTAKE,
    MISTAKE_CP,
    OK,
    Severity,
    classify_cp_loss,
    cp_to_winprob,
    move_severity,
    to_my_pov,
)

pytestmark = pytest.mark.unit

DEPTH = 18

#: What ``engine.py`` answers a checkmated position with, from either side:
#: ``mate = 0`` because the side to move there is the one that is mated, and no
#: centipawn value because a finished position has no engine line to read.
MATED = EvalResult(cp=None, mate=0, best_move=None, depth=DEPTH)
#: And what it answers a drawn one with: an even position, again with no move in it.
DRAWN = EvalResult(cp=0, mate=None, best_move=None, depth=DEPTH)

#: A quiet opening evaluation and a hanging-piece one, white's point of view.
QUIET_WHITE = EvalResult(cp=25, mate=None, best_move="g1f3", depth=DEPTH)
QUIET_WHITE_BLACK = EvalResult(cp=25, mate=None, best_move="g8f6", depth=DEPTH)
LOST_WHITE = EvalResult(cp=-948, mate=None, best_move="f6h5", depth=DEPTH)


def eval_of_cp(cp: int, *, best_move: str | None = "g1f3", mate: int | None = None) -> EvalResult:
    """A white-perspective evaluation, built the way ``engine.py`` returns one."""
    return EvalResult(cp=cp, mate=mate, best_move=best_move, depth=DEPTH)


def loss_of_cp(cp_loss: int) -> Severity:
    """A severity for a move that gave up exactly ``cp_loss`` centipowns.

    The loss is built the way ``engine.py`` produces it - the position before the
    move is even and the position after it is ``cp_loss`` down - so the tests
    below read as a table of centipawn loss against the class it earns, without
    repeating that pair of evaluations at every line.
    """
    return move_severity(eval_of_cp(0), eval_of_cp(-cp_loss), chess.WHITE)


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

#: The operator's ruling of 2026-10-02, written out as centipawns against the
#: class each one earns: the band is inclusive at the class it opens, so 50 is
#: already an inaccuracy and 200 is already a blunder.
RULED_BANDS = [
    (0, OK),
    (1, OK),
    (49, OK),
    (50, INACCURACY),
    (51, INACCURACY),
    (99, INACCURACY),
    (100, MISTAKE),
    (101, MISTAKE),
    (199, MISTAKE),
    (200, BLUNDER),
    (201, BLUNDER),
    (900, BLUNDER),
]


@pytest.mark.parametrize(("cp_loss", "expected"), RULED_BANDS)
def test_every_centipawn_loss_earns_the_ruled_class(cp_loss: int, expected: str) -> None:
    """A move is classified by its centipawn loss, at the exact edges.

    Both edges of every band are in the table - 49/50, 99/100, 199/200 - because
    a boundary probed from one side only does not say which class owns the value
    sitting on it. The three numbers are the operator's, not derived: they are
    the bands a chess player recognises when they read their own report, which
    is why the ruled 50/100/200 replaced the earlier win-probability thresholds
    (0.07/0.15/0.30 at ``k = 0.004``, about 70/155/347 cp on the real curve).
    """
    severity = loss_of_cp(cp_loss)

    assert severity.cp_loss == cp_loss, "the loss is the figure the band is read from"
    assert severity.klass == expected, (
        f"{cp_loss} cp classified {severity.klass!r}, not {expected!r} "
        f"(drop {severity.winprob_drop:.3f})"
    )


def test_the_constants_are_the_ruled_centipawns() -> None:
    """The named constants are 50/100/200, so a caller can read the band itself."""
    assert (INACCURACY_CP, MISTAKE_CP, BLUNDER_CP) == (50, 100, 200)


def test_a_negative_loss_is_ok_because_an_improvement_is_not_a_mistake() -> None:
    """A centipawn *gain* is never a mistake, in any band and at any size.

    ``move_severity`` clamps the loss at zero, so a real run cannot reach this;
    the clamp is a guard on the average ``cluster.py`` builds, and a caller that
    classifies its own figure should get the same answer from the same rule.
    """
    for cp_loss in (-1, -30, -200, -10_000):
        classified = classify_cp_loss(cp_loss)
        assert classified == OK, f"{cp_loss} cp classified {classified!r}"


def test_classify_cp_loss_is_the_whole_of_the_band_rule() -> None:
    """The boundary function reads centipawns, with nothing else in it."""
    assert classify_cp_loss(0) == OK
    assert classify_cp_loss(INACCURACY_CP - 1) == OK
    assert classify_cp_loss(INACCURACY_CP) == INACCURACY
    assert classify_cp_loss(MISTAKE_CP) == MISTAKE
    assert classify_cp_loss(BLUNDER_CP) == BLUNDER
    assert classify_cp_loss(50_000) == BLUNDER


def test_a_hundred_centipawn_loss_is_a_mistake() -> None:
    """The specific claim the ruling makes about a number players know.

    Under the superseded win-probability thresholds a 100 centipawn error was an
    *inaccuracy* (about 159 cp was the mistake line) and a blunder needed roughly
    347 cp, so real games reported almost nothing as a mistake. 30 cp is still
    ``ok``, which is what the book trigger exists to surface: a small habitual
    leak is a deviation, not a severity event.
    """
    assert loss_of_cp(100).klass == MISTAKE
    assert loss_of_cp(30).klass == OK


def test_the_win_probability_loss_is_still_computed_alongside_the_class() -> None:
    """The report still shows "Win% lost", and it is still the loss curve.

    The ruling moved the *classification* into centipawns; the win-probability
    figure is unchanged and still carried, because the report shows it and
    ``Config.win_prob_k`` is still what shapes it.
    """
    severity = loss_of_cp(120)

    assert severity.winprob_drop == pytest.approx(cp_to_winprob(0) - cp_to_winprob(-120))
    assert severity.klass == MISTAKE
    assert 0.0 <= severity.winprob_drop <= 1.0


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


# -- the mate cases the centipawn bands cannot express -----------------------


def test_walking_away_from_a_mate_is_a_blunder_at_zero_centipawns() -> None:
    """A mate score has no centipawn value, so the bands alone would call this ``ok``.

    This is the one case the operator's centipawn ruling cannot reach on its own:
    the move gives up a proved mate in one, ``cp_loss`` is 0 because neither
    evaluation carries a centipawn figure, and 0 cp is ``ok``. Giving up the
    whole game is a blunder by itself, in the same spirit as the terminal
    short-circuit.
    """
    mate_in_one = EvalResult(cp=None, mate=1, best_move="d1d8", depth=DEPTH)

    severity = move_severity(mate_in_one, eval_of_cp(30), chess.WHITE)

    assert severity.cp_loss == 0
    assert severity.klass == BLUNDER
    assert severity.winprob_drop == pytest.approx(1.0 - cp_to_winprob(30))


def test_keeping_the_mate_is_never_a_blunder_however_long_it_takes() -> None:
    """Mate in four after mate in five is still a win; the distance is not read.

    The design record decides that distance deliberately: mate in 1 and mate in
    12 are both a win, so a player who walks a forced mate closer to the move is
    not punished for it. The rule watches for the mate appearing or disappearing,
    never for its size.
    """
    before = EvalResult(cp=None, mate=5, best_move="d1d8", depth=DEPTH)
    after = EvalResult(cp=None, mate=4, best_move="d1d8", depth=DEPTH)

    severity = move_severity(before, after, chess.WHITE)

    assert severity.klass == OK
    assert severity.cp_loss == 0


def test_walking_into_mate_from_an_ordinary_position_is_a_blunder() -> None:
    """The mirror of walking away from one: mate against the player after the move."""
    mated = EvalResult(cp=None, mate=-1, best_move=None, depth=DEPTH)

    severity = move_severity(eval_of_cp(30), mated, chess.WHITE)

    assert severity.klass == BLUNDER


def test_a_player_already_being_mated_has_not_lost_anything_new() -> None:
    """Mated in two becoming mated in one is not a mistake the player made.

    The engine's distance preference cuts both ways: the player was already lost
    before the move, so the move cost them nothing the centipawn bands could
    see, and reporting it as a blunder would put a position in the ranking that
    the player could not have saved.
    """
    before = EvalResult(cp=None, mate=-2, best_move="a7a6", depth=DEPTH)
    after = EvalResult(cp=None, mate=-1, best_move="a7a6", depth=DEPTH)

    severity = move_severity(before, after, chess.WHITE)

    assert severity.klass == OK
    assert severity.winprob_drop == pytest.approx(0.0)


@pytest.mark.parametrize("colour", [chess.WHITE, chess.BLACK])
def test_a_move_that_delivers_mate_is_the_win_it_is(colour: chess.Color) -> None:
    """``mate = 0`` after the move means the *opponent* was mated, so the player won.

    The position after the player's own move always has the opponent to move, and
    ``engine.py`` answers a checkmate as ``mate = 0`` from either side because the
    side to move is the one that is mated - so the value itself cannot say whose
    win it is, and the short-circuit that read it as a whole pawn of loss read
    every checkmate the player delivered as the largest error in the window.
    A player who mates, with the engine's own best move on the board, has lost
    nothing.
    """
    # A mate score for the player is what the engine says about the position the
    # move was played from; the board answers the position it reached.
    mate_for_me = EvalResult(cp=None, mate=1, best_move="d1d8", depth=DEPTH)
    if colour == chess.BLACK:
        mate_for_me = EvalResult(cp=None, mate=-1, best_move="d1d8", depth=DEPTH)

    severity = move_severity(mate_for_me, MATED, colour)

    assert severity.cp_loss == 0
    assert severity.winprob_drop == 0.0
    assert severity.klass == OK


def test_delivering_mate_from_a_won_position_is_not_a_blunder() -> None:
    """The centipawn gap a mated board leaves behind must not be read as a loss.

    ``mate = 0`` carries no centipawn figure, so a position worth +900 before
    the move reads as 0 after it - and 900 cp of "loss" is a blunder under the
    operator's bands. The move was mate: the game is over in the player's favour,
    which is why the branch reads the finish rather than the arithmetic. A mate in
    one is not the largest leak in the window.
    """
    winning = EvalResult(cp=900, mate=None, best_move="d1d8", depth=DEPTH)

    severity = move_severity(winning, MATED, chess.WHITE)

    assert severity.cp_loss == 0
    assert severity.winprob_drop == 0.0
    assert severity.klass == OK


def test_a_draw_after_the_move_is_not_a_whole_pawn_of_loss() -> None:
    """A drawn position is worth half the game, not none of it.

    ``engine.py`` answers stalemate, insufficient material, the seventy-five-move
    rule and fivefold repetition as ``cp = 0, mate = None, best_move = None``, and
    a draw handed over from a clear advantage is a real mistake - but it is a
    mistake of the size the centipawn figure says, not a total loss of the game.
    """
    severity = move_severity(eval_of_cp(120), DRAWN, chess.WHITE)

    assert severity.klass == MISTAKE
    assert severity.cp_loss == 120
    assert severity.winprob_drop == pytest.approx(cp_to_winprob(120) - cp_to_winprob(0))
    assert severity.winprob_drop < 0.5


def test_a_draw_handed_over_from_nothing_is_not_a_loss() -> None:
    """A draw taken from an even position costs the player nothing measurable."""
    severity = move_severity(eval_of_cp(12), DRAWN, chess.WHITE)

    assert severity.klass == OK
    assert severity.winprob_drop == pytest.approx(cp_to_winprob(12) - cp_to_winprob(0))


def test_a_finished_position_after_the_move_still_needs_no_best_move() -> None:
    """Both finishes are scored without a best move in the second argument.

    This is what the terminal short-circuit was for, and it holds whichever way
    the position finished: ``engine.py`` reports ``best_move = None`` for a
    checkmate and for a draw, and neither may need one guessed or raised over.
    """
    for terminal in (MATED, DRAWN):
        severity = move_severity(QUIET_WHITE, terminal, chess.WHITE)
        assert isinstance(severity, Severity)
        assert severity.winprob_drop < 1.0, "the player did not lose the whole game"


def test_a_terminal_position_still_needs_no_best_move_in_the_first_argument() -> None:
    """A terminal first argument is scored without raising or guessing a move."""
    terminal = EvalResult(cp=0, mate=None, best_move=None, depth=DEPTH)

    severity = move_severity(terminal, eval_of_cp(0), chess.WHITE)

    assert severity.klass == OK
    assert severity.winprob_drop == 0.0


# -- configuration -----------------------------------------------------------


def test_the_slope_moves_the_displayed_drop_and_not_the_class() -> None:
    """``k`` still shapes the win-probability figure; the class comes from centipawns.

    Under the superseded win-probability thresholds the class of a move was a
    function of ``k``, because the thresholds were themselves drops. Since the
    operator's 2026-10-02 ruling the two are independent: a steeper curve makes
    the same error look bigger in the report without reclassifying it, which is
    the display-only role ``Config.win_prob_k`` now has.
    """
    mistake = eval_of_cp(-150)

    at_default = move_severity(eval_of_cp(0), mistake, chess.WHITE)
    at_four_times = move_severity(eval_of_cp(0), mistake, chess.WHITE, k=0.016)

    assert at_default.klass == at_four_times.klass == MISTAKE
    assert at_four_times.winprob_drop > at_default.winprob_drop
    assert at_default.winprob_drop == pytest.approx(cp_to_winprob(0) - cp_to_winprob(-150))
    assert at_four_times.winprob_drop == pytest.approx(
        cp_to_winprob(0, k=0.016) - cp_to_winprob(-150, k=0.016)
    )
    assert Config().win_prob_k == DEFAULT_WIN_PROB_K

    # A centipawn loss in the same band classifies the same way on either curve.
    for k in (DEFAULT_WIN_PROB_K, 0.016):
        for cp_loss, expected in RULED_BANDS:
            severity = move_severity(eval_of_cp(0), eval_of_cp(-cp_loss), chess.WHITE, k=k)
            assert severity.klass == expected, f"{cp_loss} cp at k={k}"


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
