"""Severity: the win-probability curve, the one perspective conversion, the classes.

This module answers one question about one move: *how much did the player throw
away?* It answers it in the two units the release reports, in the two roles the
operator's 2026-10-02 ruling gives them - the class in centipawns, the report's
"Win% lost" figure in win probability - and everything else in the release is
arranged so that the question has one answer rather than two, which comes down to
two rules.

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

Thresholds are **centipawn** bands - ``ok`` below 50, inaccuracy 50-100, mistake
100-200, blunder from 200 - ruled by the operator on 2026-10-02 and held as named
constants because the numbers were chosen by a person, not derived: they are the
bands a chess player recognises when they read their own report. They supersede
the operator's original 2026-06-05 thresholds, which were win-probability drops
(0.07 / 0.15 / 0.30 at ``win_prob_k = 0.004``) and on the real curve meant
roughly 70 / 155 / 347 centipawns, so a real game reported almost nothing as a
mistake. Win probability is still computed and still carried on
:class:`Severity` - the report shows it as "Win% lost" and :class:`~chessleak.config.Config`
still holds the slope - but it no longer decides the class. Open question **Q3**
on the release bead is what the ruling settled; :func:`classify_cp_loss` is the
whole of the rule that came out of it.

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
    "BLUNDER_CP",
    "INACCURACY",
    "INACCURACY_CP",
    "MISTAKE",
    "MISTAKE_CP",
    "OK",
    "Severity",
    "classify_cp_loss",
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

#: Centipawn loss at which a move stops being ``ok``, and where the next band
#: opens. The operator's ruling of 2026-10-02 (open question Q3 on the release
#: bead), replacing the 2026-06-05 win-probability thresholds of 0.07 / 0.15 /
#: 0.30 at ``win_prob_k = 0.004`` - which on the real curve meant roughly
#: 70 / 155 / 347 centipawns. Each band is inclusive at the class it opens, so
#: 50 is an inaccuracy and 200 is a blunder.
INACCURACY_CP = 50
MISTAKE_CP = 100
BLUNDER_CP = 200

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
        make the report's "Win% lost" figure a silent lie, and the run should hear
        about it.
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


def _mated_the_opponent(after: EvalResult) -> bool:
    """Whether the position the player's move reached is the opponent checkmated.

    ``after`` is already in the player's point of view, and it is the position
    *after the player's own move*, which is the whole of the argument: the side to
    move there is the opponent, so the finished position is the opponent's, not the
    player's. ``engine.py`` answers a checkmate as ``mate = 0`` from either side
    because the side to move is the side that is mated, so the value itself cannot
    say whose win it is - which is exactly what the terminal short-circuit this
    replaces read as a total loss.

    The mirror case is not here: a player who walks into a forced mate has an
    ``after`` with a negative ``mate``, which :func:`_lost_the_game_to_mate` reads,
    and a player who hands over a mate they had is the same rule from the other
    side. A delivered mate needs no band, no centipawn figure and no distance: the
    game is over in the player's favour.
    """
    return is_terminal(after) and after.mate == 0


def _winprob(evaluation: EvalResult, k: float) -> float:
    """The win probability of an evaluation already in the player's point of view.

    A mate score is a whole pawn of win probability in one direction or the other
    (the distance is deliberately ignored: mate in 1 and mate in 12 are both a
    win for v1, and :func:`_lost_the_game_to_mate` reads the same rule on the
    class side - the mate appearing or disappearing, never its size). A finished
    position carries no evaluation of its own - the board answered it, not the
    engine - so it scores as the even game it is worth no information about, which
    is what keeps a terminal first argument from inventing a drop. A terminal
    *second* argument never reaches this branch at all: :func:`move_severity` reads
    the finish itself first, because a checkmate there is the player's win and a
    draw is this even 0.5 - neither of which is a fact this function can see.
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


def _lost_the_game_to_mate(best: EvalResult, after: EvalResult) -> bool:
    """Whether the move cost the game itself, which centipawns cannot say.

    Both evaluations are already in the player's point of view. A mate score has
    no centipawn value, so ``cp_loss`` reads as zero for a move that walks away
    from a proved mate and for a move that walks into one, and the operator's
    centipawn bands (50 / 100 / 200) would call both ``ok``. Each is the whole
    win thrown away, so each is a blunder by itself - the same reasoning as the
    delivered-mate branch in :func:`move_severity`, read from the other side.

    Distance is deliberately not read, in either direction: a player who mates
    in four after a move that mated in three has kept the win, and a player who
    was already being mated in two has lost nothing the move cost them. What is
    watched is the mate appearing or disappearing, which is the part the design
    record fixes as a whole pawn of win probability.
    """
    had_mate = best.mate is not None and best.mate > 0
    has_mate = after.mate is not None and after.mate > 0
    if had_mate and not has_mate:
        return True
    was_mated = best.mate is not None and best.mate < 0
    is_mated = after.mate is not None and after.mate < 0
    return is_mated and not was_mated


def classify_cp_loss(cp_loss: int) -> str:
    """The class a centipawn loss falls in, at the operator's 2026-10-02 bands.

    ``ok`` below 50, inaccuracy from 50, mistake from 100, blunder from 200: the
    boundaries are inclusive at the class they open, so a loss of exactly
    ``INACCURACY_CP`` is an inaccuracy.

    A negative loss is ``ok``, because a move that *improves* the position is
    never a mistake. :func:`move_severity` clamps the loss at zero before it
    gets here - a negative figure would poison the average ``cluster.py`` builds
    - so this is the same rule stated once, for a caller classifying its own
    number.
    """
    if cp_loss >= BLUNDER_CP:
        return BLUNDER
    if cp_loss >= MISTAKE_CP:
        return MISTAKE
    if cp_loss >= INACCURACY_CP:
        return INACCURACY
    return OK


@dataclass(frozen=True)
class Severity:
    """How much a single move cost, in both of the units the release reports.

    ``cp_loss`` is the centipawn difference between the engine's line and the
    move actually played, ``winprob_drop`` the same loss on the win-probability
    curve, and ``klass`` the label the report shows. ``klass`` is read from
    ``cp_loss`` alone, by the operator's 2026-10-02 centipawn bands;
    ``winprob_drop`` is the report's "Win% lost" figure and no longer decides it.
    Both figures are non-negative: an improving move reads as zero, because the
    engine is not omniscient and a negative figure would poison the average
    ``cluster.py`` builds.
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

    A finished position after the move is read for *whose* win it is, not scored
    as a whole pawn of loss. The position after the player's own move always has
    the opponent to move, so the ``mate = 0`` that ``engine.py`` answers a
    checkmate with from either side means the opponent was checkmated: the player
    has just won the game, and no figure makes that a mistake
    (:func:`_mated_the_opponent`). A draw after the move is half the game, which
    :func:`_winprob` already scores as an even 0.5, and it classifies from its own
    centipawn figure like any other position. Neither finish needs a best move in
    the second argument, because ``engine.py`` reports none - which is what lets a
    mate-in-one window be scored at all. The loss that *is* real, a mate forced
    against the player, arrives as a mate score rather than a finish, and is read by
    :func:`_lost_the_game_to_mate`.

    The same reasoning covers a mate that appears or disappears across the move
    (:func:`_lost_the_game_to_mate`): a mate score carries no centipawn value, so
    the bands have nothing to read and the class would come out ``ok`` for the
    largest error in the game. The win-probability drop is still the ordinary
    computed figure there, which is what the report shows.

    A move that holds or improves the position costs nothing: the engine's line
    is one line, not the only one, so ``cp_loss`` is clamped at zero and an
    improvement is ``ok``. ``k`` is the curve's slope and it now shapes the
    displayed win-probability loss only; the class is a function of
    ``cp_loss`` alone, so a steeper curve makes the same error read bigger in the
    report without reclassifying it.
    """
    best = to_my_pov(eval_best, my_color)
    after = to_my_pov(eval_after, my_color)

    if _mated_the_opponent(after):
        # There is nothing to subtract from the position before: the move ended
        # the game in the player's favour, which is the best outcome there is.
        return Severity(cp_loss=0, winprob_drop=0.0, klass=OK)

    cp_loss = max(0, _cp(best) - _cp(after))

    winprob_drop = max(0.0, _winprob(best, k) - _winprob(after, k))
    if _lost_the_game_to_mate(best, after):
        return Severity(cp_loss=cp_loss, winprob_drop=winprob_drop, klass=BLUNDER)

    return Severity(
        cp_loss=cp_loss,
        winprob_drop=winprob_drop,
        klass=classify_cp_loss(cp_loss),
    )
