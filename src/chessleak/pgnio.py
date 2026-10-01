"""Opening-phase extraction from a game's PGN, one record per ply.

v1 analyses the opening only: the first ``Config.opening_plies`` plies (15 by
default) of the mainline of each of the player's own games. This module is the
one place the release walks a PGN and builds FENs; ``severity.py``, ``book.py``,
``cluster.py`` and ``cli.py`` consume :class:`PlyRecord` rather than re-deriving
any of it.

Three rules shape the code:

* **``fen_before`` for every ply.** The engine is asked to evaluate the position
  *before* the move, so a record whose predecessor is missing cannot be scored.
  ``fen_after`` rides along for the same reason: the severity unit needs the
  position after the move and would otherwise have to replay the line.
* **Colours come from the record, not from the ply number.** ``is_my_move`` is
  the side to move in ``fen_before`` compared with the record's ``my_color``, so
  a black player's game is tagged correctly (and the design record's white-POV
  rule downstream stays consistent with it).
* **A game that cannot be read is skipped, and says so.** python-chess collects
  parse failures in ``Game.errors`` instead of raising, so a truncated or corrupt
  export would otherwise be analysed as a shorter game and would inject a
  one-off position into the report. Every skip is logged at ``WARNING`` with the
  game id and the reason; ``cli.py`` counts the games that yielded no records as
  ``summary.games_skipped``.

Nothing here imports ``fetch.py``: the record is duck-typed against
:class:`GameRecordLike`, which is the shape the design record froze, so this
module can be imported (and tested) before or after the fetch unit lands.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import chess
import chess.pgn

from .config import DEFAULT_OPENING_PLIES

__all__ = ["GameRecordLike", "PlyRecord", "extract_opening_plies", "parse_game"]

log = logging.getLogger(__name__)

#: ECMN spells "opening unknown" as this; it is not a code.
_ECO_UNKNOWN = frozenset({"?", "-", "unknown"})


@runtime_checkable
class GameRecordLike(Protocol):
    """The part of ``fetch.GameRecord`` this module reads.

    Structural, not nominal: ``fetch.py`` may rename, extend or reorder its
    dataclass without touching this module, and a test can pass any object with
    these attributes.
    """

    id: object
    pgn: str
    my_color: str
    eco: str | None


@dataclass(frozen=True)
class PlyRecord:
    """One ply of the opening: the position, the move played and who played it."""

    game_id: str
    ply_index: int
    fen_before: str
    fen_after: str
    move_uci: str
    move_san: str
    is_my_move: bool
    eco: str | None


def parse_game(game_record: GameRecordLike) -> chess.pgn.Game | None:
    """Parse one game's PGN with python-chess, or return ``None`` if unusable.

    ``None`` covers all three ways a game cannot be analysed: no PGN text, PGN
    text with no game in it, and PGN text python-chess could not read to the end
    (an illegal move, a truncated line). Each is logged with the game id, so a
    skipped game is visible in the run's log rather than silently missing from
    the report.
    """
    game_id = str(game_record.id)
    pgn = game_record.pgn

    if not isinstance(pgn, str) or not pgn.strip():
        log.warning("game %s: empty PGN, skipping", game_id)
        return None

    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
    except Exception as exc:  # pragma: no cover - python-chess collects, not raises
        log.warning("game %s: unreadable PGN (%s), skipping", game_id, exc)
        return None

    if game is None:
        log.warning("game %s: PGN holds no game, skipping", game_id)
        return None

    if game.errors:
        # read_game recovers by stopping at the bad move, which would leave a
        # real game looking like a short one. Skip the whole game instead.
        log.warning(
            "game %s: %d illegal or unparseable move(s) in the PGN (first: %s), skipping",
            game_id,
            len(game.errors),
            game.errors[0],
        )
        return None

    return game


def extract_opening_plies(
    game_record: GameRecordLike, max_plies: int = DEFAULT_OPENING_PLIES
) -> list[PlyRecord]:
    """The opening window of one game, one :class:`PlyRecord` per ply.

    Walks the mainline only: variations are not the player's habitual line and
    never recur, so they are not part of what the report ranks. Returns ``[]`` for
    a game that cannot be parsed (logged by :func:`parse_game`) and for a window
    of zero plies.
    """
    game = parse_game(game_record)
    if game is None:
        return []

    game_id = str(game_record.id)
    my_color = _player_color(game_id, game_record)
    eco = _eco_label(game, game_record)

    board = game.board()
    records: list[PlyRecord] = []
    for ply_index, move in enumerate(game.mainline_moves()):
        if ply_index >= max_plies:
            break
        fen_before = board.fen()
        move_san = board.san(move)
        # Tagged from the side to move *in the position the move was played
        # from*, i.e. before the push, not after it.
        is_my_move = my_color is not None and board.turn == my_color
        board.push(move)
        records.append(
            PlyRecord(
                game_id=game_id,
                ply_index=ply_index,
                fen_before=fen_before,
                fen_after=board.fen(),
                move_uci=move.uci(),
                move_san=move_san,
                is_my_move=is_my_move,
                eco=eco,
            )
        )
    return records


def _player_color(game_id: str, game_record: GameRecordLike) -> chess.Color | None:
    """``chess.WHITE``/``chess.BLACK`` for the record's colour, or ``None``.

    ``my_color`` is chess.com's own ``"white"``/``"black"`` string. Anything else
    is a record the fetcher could not classify; it is warned about rather than
    guessed at, because guessing wrong silently attributes half a game's moves
    to the player.
    """
    raw = getattr(game_record, "my_color", "") or ""
    color = raw.strip().lower()
    if color == "white":
        return chess.WHITE
    if color == "black":
        return chess.BLACK
    log.warning("game %s: unknown colour %r, tagging no ply as the player's", game_id, raw)
    return None


def _eco_label(game: chess.pgn.Game, game_record: GameRecordLike) -> str | None:
    """The opening code to show for this game, or ``None`` when there is none.

    Precedence, as the design record fixes it: the PGN's ``[ECO]`` tag wins,
    because chess.com writes the ECMN code there; the archive's ``eco`` value is
    the fallback and is chess.com's opening *URL*, so a game classified only in
    the archive carries that URL as its label. Cluster demotes ECO to a display
    label chosen as the most frequent tag among contributing games, so a mixture
    of codes and URLs is a display concern (``report.py``), not a key.
    """
    tag = game.headers.get("ECO")
    if isinstance(tag, str) and tag.strip() and tag.strip().lower() not in _ECO_UNKNOWN:
        return tag.strip()

    archive_eco = getattr(game_record, "eco", None)
    if isinstance(archive_eco, str):
        archive_eco = archive_eco.strip()
        if archive_eco and archive_eco.lower() not in _ECO_UNKNOWN:
            return archive_eco
    return None
