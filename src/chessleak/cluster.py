"""Clustering: the player's recurring leaks, one cluster per position.

``severity.py`` scores a move and ``book.py`` flags one; this module answers the
question that makes either of them worth running over an archive: *how often has
the player stood here before?* A leak is only worth a report entry when it
repeats, and the report has to be able to say "this position, this many times,
these moves, this much win probability, this engine move".

Four decisions shape the code, three of them settled after the epic wrote the bead
and one of them measured on real data:

* **Cluster identity is the position, not ``(eco, fen)``.** In one real month
  archive 321 of 811 recurring positions carry more than one game-level ECO tag,
  so a compound key fragments 40% of recurrences into ``occurrences = 1`` clusters
  that a frequency ranking then drops. Clusters key on
  :func:`~chessleak.config.position_key`, the identity the eval cache already
  uses; ``eco`` is a display label chosen as the most frequent tag among the
  contributing games.
* **Only mistakes are aggregated.** A move is admitted when its class is not
  ``ok`` or a :class:`~chessleak.book.DeviationFlag` exists at its
  ``(game_id, ply_index)``. Correct play never occupies the ranking, and the
  habitual half-a-pawn leak that the win-probability thresholds call ``ok`` is
  admitted by the book trigger, which is the product's whole point.
* **The engine's move arrives as an argument.** Neither :class:`PlyRecord` nor
  :class:`Severity` carries an engine move, so the caller that already holds the
  board passes ``best_moves: Mapping[(game_id, ply_index), str]`` in SAN - the same
  currency as ``Cluster.my_moves``, which is what the report shows to a person.
  ``EvalResult.best_move`` stays UCI; the conversion happens upstream, in the one
  place holding the board, and this module never sees a UCI move.
* **The composite is frequency x severity with a rate.** ``composite_score =
  occurrences * (avg_winprob_drop + 0.05 * deviation_rate)``. A flat
  ``+0.05 * deviation_count`` bonus swings its effective weight about twentyfold
  with cluster size, which the design review found; dividing by the occurrences
  first makes the bonus a share of the cluster instead. The 0.05 is held as
  :data:`DEVIATION_WEIGHT` because open question **Q3** on the release bead asks
  whether the win-probability scale itself changes.
* **A habit is a cluster that repeats, and habits are what the report is about.**
  :func:`rank_habits` drops ``occurrences == 1`` and orders what is left by
  occurrences descending, then by composite descending. :func:`rank_clusters`
  stays, and stays the composite order, because the composite is still the honest
  description of what a leak cost - the two orderings answer different questions
  and the release wants both of them. Measured on the committed 85-game cassette
  at the e2e test's bound: 82 clusters, of which one recurs, and under the
  composite order that one-off-laden list put the single habit fourth. The ruling
  is the operator's, on ``chess-r0o`` and outcome **O2** of the release brief.

The ECO label is kept **raw**, exactly as the extractor produced it, including a
chess.com opening URL (about 12% of real games carry the archive's URL rather than
the PGN's ECMN code). Ruled on ``chess-egx``: prettifying a value this layer did
not create is not auditable, and rewriting a URL into a code is ``report.py``'s
job at render time. A URL is never a reason to drop a cluster.

:func:`aggregate` returns its clusters unsorted, in first-seen order, and
:func:`rank_clusters` is what orders them by composite descending. Splitting the
two lets the caller choose a ranking (or none) and lets ``report.py`` re-sort
defensively, as the design record requires of it. Beside them,
:func:`rank_habits` is the ordering the report actually shows: the operator's
2026-10-02 ruling that a one-time blunder is not a learning opportunity, so the
report is a list of habits - positions reached more than once - most repeated
first.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .book import DeviationFlag
from .config import position_key
from .pgnio import PlyRecord
from .severity import BLUNDER, INACCURACY, MISTAKE, OK, Severity

__all__ = [
    "HABIT_MIN_OCCURRENCES",
    "Cluster",
    "DEVIATION_WEIGHT",
    "NO_BEST_MOVE",
    "ScoredMove",
    "aggregate",
    "is_habit",
    "rank_clusters",
    "rank_habits",
]

log = logging.getLogger(__name__)

#: How much a book deviation adds to a cluster's per-occurrence score, as a share
#: of the occurrences rather than a flat bonus per deviation. A cluster that is
#: *always* a deviation is worth 0.05 more per occurrence than one that never is;
#: see the module docstring for why the flat form was rejected. Q3 re-derives this
#: once the severity scale settles.
DEVIATION_WEIGHT = 0.05

#: ``Cluster.best_move`` is a ``str`` in the frozen contract, so the "no engine
#: move was recorded for this position" answer is the empty string. ``eco`` is
#: the other optional field and uses ``None``; the report renders both the same
#: way, as an em dash.
NO_BEST_MOVE = ""

#: How many times a position must be reached to be a habit rather than a one-off.
#: The operator's 2026-10-02 ruling (outcome O2 on the release brief): a position
#: reached once is not a learning opportunity however bad the move was, so the
#: report does not surface it. Named here so the report, the CLI's withheld count
#: and the tests all read the same threshold instead of each carrying a literal.
HABIT_MIN_OCCURRENCES = 2

#: Severity order, worst last. Used to pick a cluster's ``worst_klass``. An
#: unrecognised class counts as no worse than ``ok``: a class this release does
#: not know about must not silently outrank a real mistake in the ranking.
_KLASS_ORDER = {OK: 0, INACCURACY: 1, MISTAKE: 2, BLUNDER: 3}


@dataclass(frozen=True)
class ScoredMove:
    """One of the player's moves, scored: everything a cluster counts from it.

    ``game_id`` and ``ply_index`` identify the move the way a
    :class:`~chessleak.book.DeviationFlag` identifies it, which is how the two
    are matched; ``fen_before`` is the position the cluster keys on;
    ``move_san`` and ``eco`` are what the report shows; ``severity`` is the real
    :class:`~chessleak.severity.Severity` the scoring pass produced.

    ``is_my_move`` is carried rather than assumed: the scoring pass walks a whole
    opening window, so the opponent's plies arrive in the same list, and a
    cluster of the opponent's blunders would be a report about somebody else's
    game. :func:`aggregate` skips them, loudly.

    Frozen because a move a consumer could edit between the severity pass and the
    clustering would rank differently from the one the engine produced.
    """

    game_id: str
    ply_index: int
    fen_before: str
    move_san: str
    eco: str | None
    is_my_move: bool
    severity: Severity

    @classmethod
    def from_ply(cls, ply: PlyRecord, severity: Severity) -> ScoredMove:
        """Pair an extracted ply with the severity its move was scored at.

        The one place the two are joined, so ``cli.py`` and a test cannot drift in
        which field of the record ends up in which field of the cluster.
        """
        return cls(
            game_id=ply.game_id,
            ply_index=ply.ply_index,
            fen_before=ply.fen_before,
            move_san=ply.move_san,
            eco=ply.eco,
            is_my_move=ply.is_my_move,
            severity=severity,
        )


@dataclass(frozen=True)
class Cluster:
    """One recurring position, and everything the report says about it.

    ``eco`` is the display label - the most frequent tag among the contributing
    games, raw as the data has it, ``None`` when no contributing game carried
    one. ``fen_before`` is the full FEN of the first admitted move, kept for the
    report to draw; the cluster's *identity* is :func:`position_key` of it, so a
    position reached by transposition at a different move number is the same
    cluster with one representative FEN.

    ``occurrences`` counts **admitted moves only** (see the module docstring), so
    ``sum(my_moves.values()) == occurrences`` always holds. ``my_moves`` is a
    real :class:`collections.Counter` of the player's own moves in SAN: the
    frequencies are what "you have played this here three times" is made of.
    ``best_move`` is the engine's move for the position in SAN - the most frequent
    one over the cluster's admitted moves - or :data:`NO_BEST_MOVE` when the
    caller had no engine move recorded.

    ``worst_klass`` is the class of the worst admitted move. It is carried
    because a win-probability drop cannot be classified again after the fact:
    the scale is non-linear, and the report shows the label rather than
    re-deriving it.
    """

    eco: str | None
    fen_before: str
    occurrences: int
    my_moves: Counter[str]
    best_move: str
    avg_winprob_drop: float
    max_winprob_drop: float
    deviation_count: int
    worst_klass: str
    composite_score: float


@dataclass
class _Bucket:
    """The accumulating totals of one position, before they become a ``Cluster``.

    Private because it is arithmetic in progress: insertion order is kept
    deliberately (``eco_order``, ``klasses``, ``best_order``) so that a tie in any
    of the "most frequent value wins" choices resolves on first appearance, which
    is the pipeline's order, so the same input always renders the same report.
    """

    fen_before: str
    occurrences: int = 0
    my_moves: Counter = field(default_factory=Counter)
    drop_total: float = 0.0
    max_drop: float = 0.0
    deviation_count: int = 0
    eco_order: list[str] = field(default_factory=list)
    ecos: Counter = field(default_factory=Counter)
    best_order: list[str] = field(default_factory=list)
    bests: Counter = field(default_factory=Counter)
    klasses: list[str] = field(default_factory=list)


def aggregate(
    scored_moves: Iterable[ScoredMove],
    deviations: Iterable[DeviationFlag] = (),
    best_moves: Mapping[tuple[str, int], str] | None = None,
) -> list[Cluster]:
    """Group the player's admitted moves into one cluster per position.

    ``scored_moves`` is the scored opening window of the player's games (see
    :class:`ScoredMove`); ``deviations`` is what ``first_deviation`` found, at
    most one per game; ``best_moves`` maps ``(game_id, ply_index)`` to the
    engine's move for that position **in SAN**, produced by the caller holding the
    board. The last two default to empty for a pipeline that has neither, and a
    cluster built without engine moves reports :data:`NO_BEST_MOVE`.

    A move is admitted when ``severity.klass != "ok"`` **or** a deviation flag
    exists at its ``(game_id, ply_index)``; ``occurrences`` counts admitted moves
    only, so correct play never occupies the ranking. A move whose class is ``ok``
    and which has no flag is dropped without a log line: that is the common case
    in a real run, not a defect.

    Moves that are not the player's, and plies that arrive twice, *are* logged:
    both mean the caller handed over something the ranking would otherwise turn
    into a wrong number. A repeated ply is counted once (the first copy wins),
    because ``occurrences`` is the headline figure of the report.

    Returns the clusters in first-seen order, unsorted; :func:`rank_clusters` is
    what orders them.
    """
    best_moves = best_moves or {}

    flags: dict[tuple[str, int], DeviationFlag] = {}
    for deviation in deviations:
        flags[(deviation.game_id, deviation.ply_index)] = deviation

    buckets: dict[str, _Bucket] = {}
    seen: set[tuple[str, int]] = set()
    unknown_classes: set[str] = set()

    for move in scored_moves:
        key = (move.game_id, move.ply_index)

        if key in seen:
            log.warning(
                "game %s ply %d: scored move handed over twice, counting it once",
                move.game_id,
                move.ply_index,
            )
            continue
        seen.add(key)

        if not move.is_my_move:
            log.warning(
                "game %s ply %d: %s is not the player's move, not aggregated",
                move.game_id,
                move.ply_index,
                move.move_san,
            )
            continue

        severity = move.severity
        if severity.klass == OK and key not in flags:
            continue
        if severity.klass not in _KLASS_ORDER:
            unknown_classes.add(severity.klass)

        key_of_position = position_key(move.fen_before)
        bucket = buckets.get(key_of_position)
        if bucket is None:
            bucket = _Bucket(fen_before=move.fen_before)
            buckets[key_of_position] = bucket

        bucket.occurrences += 1
        bucket.my_moves[move.move_san] += 1
        bucket.drop_total += severity.winprob_drop
        bucket.max_drop = max(bucket.max_drop, severity.winprob_drop)
        bucket.klasses.append(severity.klass)
        if key in flags:
            bucket.deviation_count += 1

        if move.eco is not None:
            if move.eco not in bucket.ecos:
                bucket.eco_order.append(move.eco)
            bucket.ecos[move.eco] += 1

        best = best_moves.get(key)
        if best:
            if best not in bucket.bests:
                bucket.best_order.append(best)
            bucket.bests[best] += 1

    for klass in sorted(unknown_classes):
        log.warning("severity class %r is not one of ok/inaccuracy/mistake/blunder", klass)

    clusters = [_build_cluster(bucket) for bucket in buckets.values()]
    log.debug("aggregated %d scored moves into %d clusters", len(seen), len(clusters))
    return clusters


def _build_cluster(bucket: _Bucket) -> Cluster:
    """Turn one position's accumulated totals into the reported cluster."""
    occurrences = bucket.occurrences
    avg_drop = bucket.drop_total / occurrences
    deviation_rate = bucket.deviation_count / occurrences

    return Cluster(
        eco=_most_frequent(bucket.ecos, bucket.eco_order),
        fen_before=bucket.fen_before,
        occurrences=occurrences,
        my_moves=bucket.my_moves,
        best_move=_most_frequent(bucket.bests, bucket.best_order) or NO_BEST_MOVE,
        avg_winprob_drop=avg_drop,
        max_winprob_drop=bucket.max_drop,
        deviation_count=bucket.deviation_count,
        worst_klass=max(bucket.klasses, key=lambda klass: _KLASS_ORDER.get(klass, 0)),
        composite_score=occurrences * (avg_drop + DEVIATION_WEIGHT * deviation_rate),
    )


def _most_frequent(counts: Counter, order: list) -> str | None:
    """The most frequent value, ties resolved on first appearance.

    ``max`` keeps the earlier item when two are equally frequent, and ``order``
    is the pipeline's own order, so the choice is deterministic without a second
    sort key. An empty tally has no most frequent value and answers ``None``, which
    is how a cluster with no ECO tag anywhere gets its label.
    """
    if not order:
        return None
    return max(order, key=lambda value: counts[value])


def rank_clusters(clusters: Iterable[Cluster]) -> list[Cluster]:
    """The clusters, best first: by ``composite_score`` descending.

    A stable sort on the composite alone, so clusters of equal score keep the
    order ``aggregate`` produced (first seen). Ranking is a separate step from
    aggregating so that ``report.py`` can re-sort defensively, and so a caller
    that wants the raw grouping never has to undo a sort.

    The returned list is a new one; the caller's list is left as it was.
    """
    return sorted(clusters, key=lambda cluster: cluster.composite_score, reverse=True)


def is_habit(cluster: Cluster) -> bool:
    """Whether this position is one the player reached more than once.

    The single definition of the filter the report applies: the operator's
    2026-10-02 ruling that a one-time blunder is not a learning opportunity, so
    it is not reported at all - not ranked last, not summarised, absent. The
    count is a fact about the cluster, not about the ranking, so this is a
    predicate on one record and both consumers (:func:`rank_habits` and any
    caller counting what it left out) can share it.
    """
    return cluster.occurrences >= HABIT_MIN_OCCURRENCES


def rank_habits(clusters: Iterable[Cluster]) -> list[Cluster]:
    """The habits only, most repeated first and costliest second.

    The release's own ranking, by the operator's 2026-10-02 ruling and outcome O2
    of the brief: the report shows positions the player reached more than once,
    ordered by how often they recurred and only then by what the leak cost. The
    composite is the tiebreak rather than the key, because a player who lost the
    same position three times for a tenth of a pawn has a bigger problem than one
    who lost it once for a pawn - which is the claim the composite-descending
    order made wrongly, measured at 19 of the top 20 entries on the committed
    85-game cassette being positions reached exactly once.

    The sort is stable, so two habits equal on both keys keep the caller's order
    and a report is reproducible. The returned list is a new one.
    """
    return sorted(
        (cluster for cluster in clusters if is_habit(cluster)),
        key=lambda cluster: (cluster.occurrences, cluster.composite_score),
        reverse=True,
    )
