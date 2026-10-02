"""The book trigger: the first player move that leaves engine-best, and by how much.

A habitual leak is often not a blunder. It is the fifth move of an opening the
player has played two hundred times, differing from the engine's choice by half a
pawn, repeated in game after game. :func:`move_severity` will not see it (half a
pawn is inside the operator's inaccuracy line), and it is exactly the leak the
product exists to name, so this module reports it on a different axis: a
**centipawn band around engine-best**, not a win-probability threshold. Everything
within ``band_cp`` of the engine's own line is book; the first move outside it is
the :class:`DeviationFlag`.

Three things are easy to get wrong here, and each has cost the release a bug:

* **The player's currency, from the player's side.** Both evaluations are
  white's point of view, exactly as ``engine.py`` returns them, so the gap is
  computed after ``severity.to_my_pov`` - the same conversion, imported, never
  re-derived. A black player who gives up a pawn has to come out with a *positive*
  gap; with the sign left alone his loss is a gain and nothing is ever flagged.
* **SAN in the flag, UCI from the engine.** ``EvalResult.best_move`` is UCI,
  because the engine speaks UCI; ``DeviationFlag.my_move`` and
  ``DeviationFlag.best_move`` are SAN, because the report shows them to a person
  and ``cluster.py`` counts ``my_move`` as a Counter keyed by SAN. The two spaces
  stay distinct and the conversion happens here, on the board the move was
  played from.
* **A position with no move to play is not a deviation.** ``engine.py`` answers a
  finished position from the board (``mate = 0`` for checkmate, ``cp = 0`` for a
  draw, no best move in either case). There is no engine line to leave there, and
  a move that delivers mate is the opposite of leaving a book.

The walk evaluates both ends of every ply in the window and reports the first
*player* move outside the band. Evaluating the whole window in one pass is
deliberate: the same two positions per ply are what the severity pass over this
game's window then asks the engine for, so with a shared ``EngineService`` the
cache is filled once and the second pass costs no engine time at all
(``EngineService.hits``/``misses`` are what ``cli.py`` reports as the hit rate).
The walk stops the moment it has its answer, so a window whose first deviation is
early never pays for its later plies.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import chess

from .config import DEFAULT_BOOK_BAND_CP
from .engine import EvalResult
from .pgnio import PlyRecord
from .severity import to_my_pov

__all__ = ["DeviationFlag", "EngineLike", "MATE_CP", "first_deviation"]

log = logging.getLogger(__name__)

#: The centipawn value a mate score is worth in the centipawn arithmetic, and its
#: negation for a mate against the player. A mate score has no centipawn value
#: (``engine.py`` keeps ``cp`` and ``mate`` mutually exclusive), so the gap needs
#: a stand-in. It is deliberately far beyond any band a caller can configure, so
#: giving up a forced mate always leaves the book: a window that ends in mate is
#: one of the most common ways a 15-ply opening ends, and it must not depend on
#: the configured band to be reported.
MATE_CP = 10_000


class EngineLike(Protocol):
    """The part of ``engine.EngineService`` this module calls.

    Structural, so the unit test's stub is a legitimate argument and this module
    never has to know whether it is talking to a real Stockfish process.
    """

    def analyse(self, fen: str) -> EvalResult:
        """Evaluate one position, from the cache when it can."""
        ...


@dataclass(frozen=True)
class DeviationFlag:
    """One move that left the book, and everything ``cluster.py`` keys on it.

    ``game_id`` and ``ply_index`` identify the move in one of the player's games,
    ``fen_before`` is the position it was played from - the position's identity in
    a cluster - and ``my_move``/``best_move`` are the two moves in SAN, as a
    person reads them. ``cp_gap >= 0`` always means "worse for the player": a move
    that improved is a gap of zero, never a negative figure that would drag a
    cluster's average the wrong way.

    Frozen because a flag a consumer could edit would rank differently from the
    one the walk produced.
    """

    game_id: str
    ply_index: int
    fen_before: str
    my_move: str
    best_move: str
    cp_gap: int


def first_deviation(
    ply_records: Iterable[PlyRecord],
    engine: EngineLike,
    band_cp: int = DEFAULT_BOOK_BAND_CP,
) -> DeviationFlag | None:
    """The first move of the player's that leaves engine-best, or ``None``.

    ``ply_records`` is one game's opening window, in any order: the records are
    walked in ``ply_index`` order, so a caller that hands the window over
    shuffled still gets the earliest deviation. ``band_cp`` is the half-width of
    the book band in centipawns and defaults to ``Config.book_band_cp``: a gap
    exactly equal to it is still book, one centipawn more is not.

    A move is in book when the engine's evaluation of the position before it, and
    the evaluation of the position the move actually reached, are within
    ``band_cp`` of each other **in the player's point of view**. Only the
    player's own moves can be flagged; the opponent's moves are walked (the
    window is evaluated in one pass) and never reported.

    Returns ``None`` for a window in which every player move stayed in the book,
    for a window with no records at all, and for a move that leaves a position
    with no move to play.

    A record whose ``fen_before`` no longer agrees with the engine's ``best_move``
    is skipped with a logged reason rather than reported: that is a stale cache
    row or a corrupt record, and a flag built from it would rank a position the
    player may never have reached.
    """
    for record in sorted(ply_records, key=lambda ply: ply.ply_index):
        before = engine.analyse(record.fen_before)
        after = engine.analyse(record.fen_after)

        if not record.is_my_move:
            continue

        board = chess.Board(record.fen_before)
        best_san = _best_move_san(board, before, record)
        if best_san is None:
            continue

        cp_gap = _cp_gap(before, after, board.turn)
        if cp_gap > band_cp:
            return DeviationFlag(
                game_id=record.game_id,
                ply_index=record.ply_index,
                fen_before=record.fen_before,
                my_move=record.move_san,
                best_move=best_san,
                cp_gap=cp_gap,
            )

    return None


def _best_move_san(board: chess.Board, evaluation: EvalResult, record: PlyRecord) -> str | None:
    """The engine's move in the position the player's move was played from, in SAN.

    ``None`` means "no engine line to leave here", and the ply is skipped:

    * a position with no move to play is finished (``engine.py`` answers it from
      the board), so there is nothing to compare the player's move against. That
      is the ordinary end of a game inside the opening window, and it is logged
      at ``INFO`` because it is not a defect.
    * a move that is not legal in this position - a stale cache row keyed on a
      position reached at a different move number, or a corrupt record - is a
      defect, so it is logged at ``WARNING`` and the ply is skipped rather than
      reported against a position the record does not describe.
    """
    if evaluation.best_move is None:
        log.info(
            "game %s ply %d: no engine move for %s, the position is over; not a deviation",
            record.game_id,
            record.ply_index,
            record.fen_before,
        )
        return None

    try:
        move = chess.Move.from_uci(evaluation.best_move)
    except ValueError:
        log.warning(
            "game %s ply %d: engine move %r is not a move, skipping the ply",
            record.game_id,
            record.ply_index,
            evaluation.best_move,
        )
        return None

    if move not in board.legal_moves:
        log.warning(
            "game %s ply %d: engine move %r is illegal in %s, skipping the ply",
            record.game_id,
            record.ply_index,
            evaluation.best_move,
            record.fen_before,
        )
        return None

    return board.san(move)


def _cp_gap(eval_best: EvalResult, eval_after: EvalResult, my_color: chess.Color) -> int:
    """How much worse the played move is than the engine's line, in centipawns.

    Both evaluations are white's point of view; this is the one place they become
    the player's, through the shared conversion, so a black player's loss and a
    white player's loss are the same positive number. An improving move is a gap
    of zero rather than a negative one: the engine's line is a line, not the only
    one, and a negative gap would make the report claim the player beat the
    engine by leaving the book.
    """
    mine_best = _cp_figure(to_my_pov(eval_best, my_color))
    after = to_my_pov(eval_after, my_color)
    # A finished position after the move is mate zero, and mate zero says nothing
    # about *whose* win it is until the board is asked: the side to move there is
    # the opponent, so mate zero means the opponent is checkmated and the player
    # has just won the game. Scored any other way, delivering mate would read as
    # the largest leak in the window.
    mine_after = MATE_CP if after.mate == 0 else _cp_figure(after)
    return max(0, mine_best - mine_after)


def _cp_figure(evaluation: EvalResult) -> int:
    """An evaluation in the player's currency as one integer number of centipawns.

    A mate score has no centipawn value, so it is worth :data:`MATE_CP` in the
    player's direction and ``-MATE_CP`` against them, which is what makes giving
    up a forced mate a deviation of a size no band can absorb. A finished position
    is worth nothing either way, because the board answered it rather than the
    engine, and there is no line in it to leave.
    """
    if evaluation.mate is not None and evaluation.mate != 0:
        return MATE_CP if evaluation.mate > 0 else -MATE_CP
    return int(evaluation.cp or 0)
