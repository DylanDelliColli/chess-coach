"""Severity: the win-probability curve, the one perspective conversion, the classes.

This module answers one question about one move: *how much win probability did the
player throw away?* Everything else in the release is arranged so that the question
has one answer rather than two, which comes down to two rules.

* **Scores arrive as white's point of view, always.** ``engine.py`` reads
  ``info["score"].white()`` and hands back :class:`~chessleak.engine.EvalResult`
  values that mean the same thing whichever side is to move. :func:`to_my_pov` is
  the *only* place a score becomes the player's, and it is a public helper because
  ``book.py`` needs the same conversion: a black player whose move improves reads
  as a fall in win probability if the conversion is applied twice, and never gets
  flagged at all if it is applied not at all. Both are the failure the PRD names.
* **A move is scored by two evaluations, both in white's point of view.**
  ``eval_best`` is the position *before* the move, which is the engine's own line
  at its best; ``eval_after`` is the position *after* it. The loss is the distance
  between them in the player's currency, never the score of the position alone.

Thresholds are the operator's written values - a win-probability drop of
``INACCURACY_DROP`` / ``MISTAKE_DROP`` / ``BLUNDER_DROP`` at ``win_prob_k = 0.004`` -
held as named constants because open question **Q3** on the release bead asks
whether the conventional centipawn bands (50/100/200) should replace them. If the
answer is "centipawns", these constants and the tests that pin them change;
nothing structural does. :func:`test_scale_is_the_operators_scale` records what
the current scale means in centipawns, so a change of threshold forces a decision
there rather than a silent drift.

Nothing here imports ``engine.py``'s service, and nothing here talks to an engine:
:func:`move_severity` takes two evaluations that were produced elsewhere, so it is
testable arithmetic and it cannot half-run an analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import DEFAULT_WIN_PROB_K
from .engine import EvalResult

__all__ = [
    "BLUNDER",
    "BLUNDER_DROP",
    "INACCURACY",
    "INACCURACY_DROP",
    "MISTAKE",
    "MISTAKE_DROP",
    "OK",
    "Severity",
    "classify_drop",
    "cp_to_winprob",
    "move_severity",
    "to_my_pov",
]

#: The four classes, as the design record spells them. They are strings because
#: ``cluster.py`` counts them and ``report.py`` prints them, and a string is what
#: both of those want; the constants exist so no module retypes the literals.
OK = "ok"
INACCURACY = "inaccuracy"
MISTAKE = "mistake"
BLUNDER = "blunder"

#: Win-probability drop at which a move stops being ``ok``, in the operator's
#: written scale. **Q3** on the release bead asks whether conventional centipawn
#: bands (50/100/200) should replace these; do not move them on your own
#: judgement. With ``win_prob_k = 0.004`` these read as roughly 72 cp, 159 cp and
#: 347 cp, which is the finding Q3 turns on.
INACCURACY_DROP = 0.07
MISTAKE_DROP = 0.15
BLUNDER_DROP = 0.30

#: ``exp(x)`` overflows a double a little past 709, and by then
#: ``1 / (1 + exp(-x))`` is 1.0 (or 0.0) to far more digits than a report shows.
#: Beyond this the curve is saturated, so the function returns the saturated value
#: instead of raising OverflowError inside the run. Mate-adjacent centipawn values
#: and a centipawn field read from a corrupt cache row both reach it.
_SATURATION = 700.0


def cp_to_winprob(cp: int, k: float = DEFAULT_WIN_PROB_K) -> float:
    """The probability that a position worth ``cp`` centipawns is won.

    ``cp_to_winprob(0)`` is 0.5 and the curve is symmetric about it, so a position
    and its mirror image win with probabilities that add to one. ``k`` is the
    slope: a larger ``k`` saturates sooner, which is how a centipawn loss turns
    into a bigger win-probability drop. The default is ``Config.win_prob_k``.

    Centipawns only, by contract: a mate score has no centipawn value, and the
    mate-to-win-probability mapping lives in :func:`move_severity`, where the
    colour is known.

    :raises ValueError: if ``k`` is not positive. A flat or inverted curve would
        make every classification a silent lie, and the run should hear about it.
    """
    if not k > 0:
        raise ValueError(f"win probability slope k must be positive, got {k!r}")

    scaled = k * cp
    if scaled >= _SATURATION:
        return 1.0
    if scaled <= -_SATURATION:
        return 0.0
    return 1.0 / (1.0 + math.exp(-scaled))


def to_my_pov(evaluation: EvalResult, my_color: object) -> EvalResult:
    """The same evaluation read as the player's, given the player's colour.

    Black's point of view is white's negated, and nothing else: the best move
    stays a move (a move is not a side), the depth stays the depth, and a mated
    position stays mated - ``engine.py`` answers it as ``mate = 0`` from either
    side, so negating zero would only give ``-0``.

    ``my_color`` is accepted in every form a caller actually holds it: chess.com's
    ``"white"``/``"black"`` string (``fetch.GameRecord.my_color``), the
    ``chess.WHITE``/``chess.BLACK`` constants, the booleans those are, and ``0`` /
    ``1`` for a colour read out of JSON. Case and surrounding space are ignored.
    Anything else is an error rather than a guess, because guessing wrong signs
    half a player's game backwards.

    This is the single conversion in the release. ``book.py`` imports it rather
    than re-deriving the negation, and a caller must not apply it a second time to
    an evaluation it has already passed through here.
    """
    black = _is_black(my_color)

    cp = evaluation.cp
    mate = evaluation.mate
    if black:
        if cp is not None:
            cp = -cp
        if mate is not None and mate != 0:
            # A mate score counts plies to mate, so it flips with the point of
            # view; mate 0 is a finished position and flips to -0, i.e. to itself.
            mate = -mate

    return EvalResult(
        cp=cp,
        mate=mate,
        best_move=evaluation.best_move,
        depth=evaluation.depth,
    )


def _is_black(my_color: object) -> bool:
    """Whether ``my_color`` names black, or raise ``ValueError`` naming the value."""
    if isinstance(my_color, str):
        color = my_color.strip().lower()
        if color == "white":
            return False
        if color == "black":
            return True
    elif isinstance(my_color, bool):
        # chess.WHITE is True and chess.BLACK is False, so this covers both the
        # constants and a plain boolean read out of JSON.
        return not my_color
    elif isinstance(my_color, int) and my_color in (0, 1):
        return bool(my_color)
    raise ValueError(
        f"unknown colour {my_color!r}: expected 'white'/'black', chess.WHITE/chess.BLACK, or 0/1"
    )


def is_terminal(evaluation: EvalResult) -> bool:
    """Whether an evaluation describes a position that is over.

    ``engine.py`` answers a finished position from the board without searching:
    checkmate as ``mate = 0, cp = None`` and a draw as ``cp = 0``, both with
    ``best_move = None`` throughout, and both of those are detected here.

    A mate score that is *not* ``mate = 0`` is not a finished position. It is the
    engine saying "the other side mates in n", and a record may carry it without
    a move (nothing is left to play in the window once the mate is on the board),
    so ``best_move is None`` alone would call a mated player a finished position
    and score their opponent's win as a whole pawn of loss instead of the mate
    score it is. The design record offers ``mate == 0 or best_move is None`` as
    the detection rule; this narrows the second half to the records that really
    mean a finished position, so the record's own answer set is matched exactly.
    """
    return evaluation.mate == 0 or (evaluation.mate is None and evaluation.best_move is None)


def _winprob(evaluation: EvalResult, k: float) -> float:
    """The win probability of an evaluation already in the player's point of view.

    A mate score is a whole pawn of win probability in one direction or the other
    (the distance is deliberately ignored: mate in 1 and mate in 12 are both a
    win for v1, and open question Q3's sibling decision on distance is not this
    release's to make). A finished position carries no evaluation of its own -
    the board answered it, not the engine - so it scores as the even game it is
    worth no information about, which is what keeps a terminal first argument from
    inventing a drop. A terminal *second* argument is the short-circuit in
    :func:`move_severity`, not this branch.
    """
    if evaluation.mate is not None and evaluation.mate != 0:
        return 1.0 if evaluation.mate > 0 else 0.0
    return cp_to_winprob(evaluation.cp or 0, k)


def _cp(evaluation: EvalResult) -> int:
    """The evaluation as a centipawn figure, with nothing to convert worth 0.

    A mate score and a finished position have no centipawn value, so both
    contribute zero to the centipawn loss. The centipawn figure is the one field
    of :class:`Severity` the report shows in the units a chess player reads, and
    it is a difference of two figures rather than a win probability, so it cannot
    be a clamp away.
    """
    return int(evaluation.cp or 0)


def classify_drop(winprob_drop: float) -> str:
    """The class a win-probability drop falls in, at the operator's thresholds.

    The boundaries are inclusive at the class they open, so a drop of exactly
    ``INACCURACY_DROP`` is an inaccuracy. A drop is never negative: callers clamp
    it before asking, because a move that improved is a zero, not a mistake.
    """
    if winprob_drop >= BLUNDER_DROP:
        return BLUNDER
    if winprob_drop >= MISTAKE_DROP:
        return MISTAKE
    if winprob_drop >= INACCURACY_DROP:
        return INACCURACY
    return OK


@dataclass(frozen=True)
class Severity:
    """How much a single move cost, in both of the units the release reports.

    ``cp_loss`` is the centipawn difference between the engine's line and the
    move actually played, ``winprob_drop`` the same loss on the win-probability
    curve, and ``klass`` the label the report shows. ``cp_loss`` and
    ``winprob_drop`` are both non-negative: an improving move reads as zero,
    because the engine is not omniscient and a negative figure would poison the
    average ``cluster.py`` builds.
    """

    cp_loss: int
    winprob_drop: float
    klass: str


def move_severity(
    eval_best: EvalResult,
    eval_after: EvalResult,
    my_color: object,
    *,
    k: float = DEFAULT_WIN_PROB_K,
) -> Severity:
    """Score one move, given the position before it and the position after it.

    Both arguments are **white's point of view**, exactly as ``engine.py`` returns
    them; the conversion to the player's side happens here, once. ``eval_best`` is
    the position before the move (the engine's own line) and ``eval_after`` the
    position the player's move actually reached.

    A finished position after the move is a whole pawn of win probability lost,
    whatever the player's move was: the game is over, nothing is recoverable, and
    the record cannot ask for a best move it has already said does not exist. That
    short-circuit is why this function can score a mate-in-one window without a
    best move in the second argument.

    A move that holds or improves the position costs nothing: the engine's line
    is one line, not the only one, so ``winprob_drop`` is clamped at zero and an
    improvement is ``ok``. ``k`` is the curve's slope, so a caller can re-scale
    the drop (see Q3) without touching the class boundaries.
    """
    best = to_my_pov(eval_best, my_color)
    after = to_my_pov(eval_after, my_color)

    cp_loss = max(0, _cp(best) - _cp(after))

    if is_terminal(after):
        return Severity(cp_loss=cp_loss, winprob_drop=1.0, klass=BLUNDER)

    winprob_drop = max(0.0, _winprob(best, k) - _winprob(after, k))
    return Severity(
        cp_loss=cp_loss,
        winprob_drop=winprob_drop,
        klass=classify_drop(winprob_drop),
    )
