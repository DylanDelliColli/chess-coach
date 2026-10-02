"""Clustering: which of the player's moves are the same recurring position.

The types under test are the **real** ones the release freezes - the real
:class:`Severity` from ``severity.py`` and the real :class:`DeviationFlag` from
``book.py`` - because a look-alike dataclass with the same field names would pass
every assertion in this file and then break ``report.py`` at the seam. The
severities here are hand-built rather than derived from evaluations: this unit
consumes scores, it does not produce them (``severity.py`` is where the engine
becomes arithmetic), and pinning the composite against exact figures is the point.

Four rules earn their tests here, three of them added to the bead after the epic
wrote it and one of them measured:

* **Cluster identity is the position, not ``(eco, fen)``.** 321 of 811 recurring
  positions in one real month archive carry more than one game-level ECO tag, so
  a compound key fragments 40% of recurrences into ``occurrences = 1`` clusters
  that then vanish from a frequency ranking. ``aggregate`` keys on
  :func:`position_key`, so a position reached by transposition at a different
  move number is one cluster.
* **Only mistakes are aggregated.** A move is admitted when its class is not
  ``ok`` or a deviation flag exists at its ``(game_id, ply_index)``; correct play
  never occupies the ranking.
* **The engine's move arrives as an argument**, keyed ``(game_id, ply_index)`` in
  SAN, because ``PlyRecord`` and ``Severity`` carry no engine move.
* **The composite is frequency x severity with a rate, not a count**:
  ``occurrences * (avg_winprob_drop + 0.05 * deviation_rate)``. A flat
  ``+0.05 * deviation_count`` bonus swings its effective weight about 20x with
  cluster size, which is what the review found.
* **A habit is reached more than once, and habits rank by frequency first**
  (``chess-iql``, the operator's 2026-10-02 ruling): ``rank_habits`` drops
  ``occurrences == 1`` clusters and orders what is left by occurrences
  descending, then composite descending. ``rank_clusters`` keeps the composite
  order, because that is still the honest description of what a leak cost.
"""

from __future__ import annotations

from collections import Counter

import pytest

from src.chessleak.book import DeviationFlag
from src.chessleak.cluster import (
    DEVIATION_WEIGHT,
    HABIT_MIN_OCCURRENCES,
    NO_BEST_MOVE,
    Cluster,
    ScoredMove,
    aggregate,
    is_habit,
    rank_clusters,
    rank_habits,
)
from src.chessleak.config import position_key
from src.chessleak.severity import BLUNDER, INACCURACY, MISTAKE, OK, Severity

pytestmark = pytest.mark.unit

#: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6, white to move on move 4.
START_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"

#: The same position reached by transposition, as the real line
#: ``1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Nf3 Nf6 5. Bc4 Nc6`` actually reaches it:
#: white plays a tempo while black shuffles its knight out and back, so the board
#: arrives two moves later and both clocks differ. The halfmove clock and the
#: fullmove number are the only fields that differ, which is exactly what
#: ``position_key`` drops.
TRANSPOSED_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 6"

#: A different position entirely (4.Bb5, the Ruy Lopez proper), for the tests
#: that need two clusters to rank.
OTHER_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 5 4"

#: A third position (the French Defence's main line, 3.Nc3), for the habit
#: ranking: ordering three clusters needs three positions, and the habit rule is
#: about *which* of them comes first, so one more distinct board is required.
FRENCH_FEN = "rnbqkb1r/ppp2ppp/4pn2/3p4/3P4/2N5/PPP1PPPP/RNBQKBR w KQkq - 0 3"

assert position_key(START_FEN) == position_key(TRANSPOSED_FEN)
assert position_key(START_FEN) != position_key(OTHER_FEN)
assert position_key(FRENCH_FEN) not in (position_key(START_FEN), position_key(OTHER_FEN))


def scored(
    game_id: str,
    ply_index: int,
    fen_before: str,
    *,
    move_san: str = "Nf3",
    eco: str | None = "C50",
    klass: str = MISTAKE,
    winprob_drop: float = 0.20,
    cp_loss: int = 120,
    is_my_move: bool = True,
) -> ScoredMove:
    """One scored player move, as the pipeline hands one to ``aggregate``."""
    return ScoredMove(
        game_id=game_id,
        ply_index=ply_index,
        fen_before=fen_before,
        move_san=move_san,
        eco=eco,
        is_my_move=is_my_move,
        severity=Severity(cp_loss=cp_loss, winprob_drop=winprob_drop, klass=klass),
    )


def flag(
    game_id: str,
    ply_index: int,
    fen_before: str,
    *,
    my_move: str = "Nf3",
    best_move: str = "Nc3",
    cp_gap: int = 70,
) -> DeviationFlag:
    """One book deviation, as ``first_deviation`` produces it."""
    return DeviationFlag(
        game_id=game_id,
        ply_index=ply_index,
        fen_before=fen_before,
        my_move=my_move,
        best_move=best_move,
        cp_gap=cp_gap,
    )


# -- the two named behaviours ------------------------------------------------


def test_aggregate_groups_and_composite() -> None:
    """Two games reaching one position collapse into one ranked cluster.

    The position is reached at two different move numbers on purpose: a compound
    ``(eco, fen)`` key would call these two positions, two clusters, and the
    frequency ranking the product exists for would show ``occurrences = 1`` twice
    instead of one recurring position. The two moves are also scored differently
    (0.20 and 0.30 of win probability) and only one of them is a book
    deviation, so every aggregate field is pinned to a figure a reader can
    check by hand.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, klass=MISTAKE, winprob_drop=0.20),
            scored("g2", 0, TRANSPOSED_FEN, klass=BLUNDER, winprob_drop=0.30),
            # Correct play in the same two games, at the same position, is not
            # aggregated: occurrences counts admitted moves only.
            scored("g1", 4, START_FEN, move_san="d3", klass=OK, winprob_drop=0.01),
            scored("g2", 4, TRANSPOSED_FEN, move_san="d3", klass=OK, winprob_drop=0.01),
            # A real mistake somewhere else, so the file has a second cluster.
            scored("g1", 2, OTHER_FEN, move_san="Bb5", klass=INACCURACY, winprob_drop=0.08),
        ],
        [flag("g1", 0, START_FEN, my_move="Nf3", best_move="Nc3", cp_gap=70)],
        {("g1", 0): "Nc3", ("g2", 0): "Nxe5"},
    )

    assert len(clusters) == 2, "correct play must not occupy the ranking"

    recurring = [c for c in clusters if c.fen_before == START_FEN]
    assert len(recurring) == 1, (
        "the transposed position must be the same cluster, not a second one; got "
        f"{[c.fen_before for c in clusters]}"
    )

    cluster = recurring[0]
    assert cluster.occurrences == 2, "only the two mistakes are counted"
    assert cluster.my_moves == Counter({"Nf3": 2})
    assert cluster.avg_winprob_drop == pytest.approx(0.25)
    assert cluster.max_winprob_drop == pytest.approx(0.30)
    assert cluster.deviation_count == 1, "only g1's move left the book"
    assert cluster.worst_klass == BLUNDER, "the worst class among the admitted moves"
    assert cluster.best_move == "Nc3", "the engine's move in SAN, most frequent first"

    # composite = occurrences * (avg_drop + 0.05 * deviation_rate), spelled out
    # rather than restated from the module so the formula is checked, not echoed.
    deviation_rate = cluster.deviation_count / cluster.occurrences
    assert cluster.composite_score == pytest.approx(2 * (0.25 + DEVIATION_WEIGHT * deviation_rate))
    assert cluster.composite_score == pytest.approx(0.55)

    ranked = rank_clusters(clusters)
    assert ranked[0] is cluster, "the recurring position outranks a one-off leak"
    assert ranked[0].composite_score == pytest.approx(0.55)
    assert ranked[1].composite_score == pytest.approx(0.08), "one occurrence, no deviation"


def test_my_moves_counter() -> None:
    """The player's move frequencies are tallied per position, in SAN.

    Three games, two of which reach the position by transposition and answer the
    engine the same way, one of which reaches it by a third move: the Counter is
    what the report shows as "you play Nf3 here, and you have played it three
    times".
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, move_san="Nf3"),
            scored("g2", 0, TRANSPOSED_FEN, move_san="Nf3"),
            scored("g3", 2, START_FEN, move_san="Bc4"),
            # A different position, so its move does not pollute this counter.
            scored("g1", 4, OTHER_FEN, move_san="Nf3"),
        ],
        [],
        {("g1", 0): "Nc3", ("g2", 0): "Nc3", ("g3", 2): "d3"},
    )

    assert len(clusters) == 2

    cluster = next(c for c in clusters if position_key(c.fen_before) == position_key(START_FEN))
    assert cluster.my_moves == Counter({"Nf3": 2, "Bc4": 1})
    assert cluster.occurrences == 3
    assert sum(cluster.my_moves.values()) == cluster.occurrences


# -- identity ----------------------------------------------------------------


def test_transposition_is_one_cluster_and_the_first_fen_is_kept_for_display() -> None:
    """The key is the position; the FEN kept is a representative for the report.

    ``Cluster.fen_before`` is the full FEN of the first admitted move, because
    the report renders it and the design record keeps the full FEN for display
    only. Two games reaching the same position at different move numbers share one
    cluster, and the counters add up.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, klass=BLUNDER, winprob_drop=0.40),
            scored("g2", 0, TRANSPOSED_FEN, klass=BLUNDER, winprob_drop=0.40),
        ],
        [],
        {},
    )

    assert len(clusters) == 1
    assert clusters[0].fen_before == START_FEN, "the first admitted move's own FEN"
    assert clusters[0].occurrences == 2


def test_two_different_eco_tags_do_not_split_a_position() -> None:
    """ECO is a label on the cluster, never part of its identity.

    This is the measurement the design record cites: in one real month 321 of 811
    recurring positions carried more than one game-level ECO tag, so keying on
    ``(eco, fen)`` split 40% of recurrences into ``occurrences = 1`` clusters
    that a frequency ranking then drops. The label below is the more frequent of
    the two, chosen from the data.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, eco="C50"),
            scored("g2", 0, TRANSPOSED_FEN, eco="C50"),
            scored("g3", 0, START_FEN, eco="C60"),
        ],
        [],
        {},
    )

    assert len(clusters) == 1
    assert clusters[0].occurrences == 3
    assert clusters[0].eco == "C50"


def test_eco_is_kept_raw_including_a_chesscom_url() -> None:
    """An opening URL is the label the data has, and this unit does not rewrite it.

    Ruled on ``chess-egx``: ``Cluster.eco`` stays exactly as the extractor produced
    it, including a chess.com URL (about 12% of real games carry the archive's
    URL rather than the PGN's ECMN code). Prettifying a value this layer did not
    create would not be auditable, and a URL is not a reason to drop a cluster.
    """
    url = "https://www.chess.com/openings/Giuoco-Piano-Game...6.c3-O-O-7.Re1-a6"
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, eco=url),
            scored("g2", 0, TRANSPOSED_FEN, eco=url),
            scored("g3", 0, START_FEN, eco=None),
        ],
        [],
        {},
    )

    assert len(clusters) == 1
    assert clusters[0].eco == url
    assert clusters[0].occurrences == 3


def test_a_position_no_game_tagged_is_eco_none() -> None:
    """No tag anywhere leaves the label empty, which the report renders as an em dash."""
    clusters = aggregate([scored("g1", 0, START_FEN, eco=None)], [], {})

    assert clusters[0].eco is None
    assert clusters[0].occurrences == 1


def test_eco_tie_breaks_on_the_first_tag_seen() -> None:
    """Two labels at the same frequency resolve deterministically, not by luck.

    Insertion order is the pipeline's order (the games were read in archive
    order), so the first one seen wins and the same input always renders the same
    report.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, eco="C50"),
            scored("g2", 0, TRANSPOSED_FEN, eco="C60"),
        ],
        [],
        {},
    )

    assert clusters[0].eco == "C50"


# -- admission ---------------------------------------------------------------


def test_correct_play_is_never_admitted() -> None:
    """An ``ok`` move with no deviation does not appear in the ranking at all."""
    clusters = aggregate([scored("g1", 0, START_FEN, klass=OK, winprob_drop=0.0)], [], {})

    assert clusters == []


def test_a_deviation_admits_a_move_the_thresholds_call_ok() -> None:
    """The book trigger admits what the win-probability thresholds do not.

    This is the leak the product exists for: a habitual move that is half a pawn
    away from the engine's line is below the 0.07 inaccuracy line, so severity
    calls it ``ok``, and the deviation flag is what brings it into the report.
    """
    clusters = aggregate(
        [scored("g1", 0, START_FEN, move_san="d3", klass=OK, winprob_drop=0.049, cp_loss=49)],
        [flag("g1", 0, START_FEN, my_move="d3", best_move="e5", cp_gap=73)],
        {("g1", 0): "e5"},
    )

    assert len(clusters) == 1
    assert clusters[0].occurrences == 1
    assert clusters[0].deviation_count == 1
    assert clusters[0].worst_klass == OK, "no admitted move was worse than ok"
    assert clusters[0].my_moves == Counter({"d3": 1})
    # A pure deviation at the point of the score: its own 0.049 drop, plus the
    # 0.05 a cluster whose every occurrence is a deviation earns per occurrence.
    assert clusters[0].composite_score == pytest.approx(0.049 + DEVIATION_WEIGHT)


def test_a_deviation_at_another_ply_does_not_admit_this_one() -> None:
    """A flag is matched on ``(game_id, ply_index)``, not merely on the position.

    The flag says which move left the book. Attributing it to a sibling ply in
    the same position would put a move the player did not play in the cluster's
    frequency count.
    """
    clusters = aggregate(
        [scored("g1", 2, START_FEN, move_san="d3", klass=OK, winprob_drop=0.01)],
        [flag("g1", 4, START_FEN, my_move="d3", best_move="e5")],
        {},
    )

    assert clusters == []


def test_a_flag_in_another_game_does_not_admit_a_move() -> None:
    """Flags are per game: the same ply number in another game is another move."""
    clusters = aggregate(
        [scored("g1", 2, START_FEN, move_san="d3", klass=OK, winprob_drop=0.01)],
        [flag("g2", 2, START_FEN, my_move="d3", best_move="e5")],
        {},
    )

    assert clusters == []


def test_the_opponents_moves_are_never_clustered() -> None:
    """A blunder by the opponent is not the player's recurring mistake.

    The walk upstream scores a whole window, so the opponent's plies arrive in the
    same list as the player's. Ranking them would put moves the player never
    chose at the top of a report about their own habits.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, is_my_move=False, klass=BLUNDER, winprob_drop=0.9),
            scored("g1", 1, OTHER_FEN, is_my_move=False, klass=BLUNDER, winprob_drop=0.9),
            scored("g1", 2, OTHER_FEN, move_san="Nc3"),
        ],
        [],
        {},
    )

    assert len(clusters) == 1
    assert position_key(clusters[0].fen_before) == position_key(OTHER_FEN)
    assert clusters[0].occurrences == 1


def test_a_duplicated_ply_is_counted_once() -> None:
    """The same ply handed over twice is one occurrence, not two.

    ``occurrences`` is the product's headline number, so a caller that scored one
    game twice must not be able to double its frequency. The first copy wins and
    the duplicate is logged.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, klass=BLUNDER, winprob_drop=0.40),
            scored("g1", 0, START_FEN, klass=BLUNDER, winprob_drop=0.40),
        ],
        [],
        {},
    )

    assert len(clusters) == 1
    assert clusters[0].occurrences == 1
    assert clusters[0].my_moves == Counter({"Nf3": 1})


def test_the_opponents_plies_are_skipped_with_a_reason(caplog: pytest.LogCaptureFixture) -> None:
    """Skipping the opponent's move is visible in the log, not silent."""
    with caplog.at_level("WARNING", logger="src.chessleak.cluster"):
        aggregate([scored("g1", 0, START_FEN, is_my_move=False, klass=BLUNDER)], [], {})

    assert any("g1" in record.getMessage() for record in caplog.records)
    assert "not the player's move" in caplog.text


def test_nothing_to_aggregate_is_an_empty_list() -> None:
    """An empty input is an empty ranking, not an error."""
    assert aggregate([], [], {}) == []
    assert aggregate([], [], {("g1", 0): "Nc3"}) == []
    assert rank_clusters([]) == []


# -- the fields the report reads --------------------------------------------


def test_best_move_is_the_most_frequent_engine_move_in_san() -> None:
    """``best_move`` is the engine's move for this position, as a person reads it.

    It is the mode of the mapping over the cluster's admitted moves, with ties
    broken by first appearance. UCI never appears here: the engine speaks UCI,
    the report shows SAN, and this unit consumes the SAN the caller converted.
    """
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, move_san="Nf3"),
            scored("g2", 0, TRANSPOSED_FEN, move_san="Nf3"),
            scored("g3", 0, START_FEN, move_san="d3"),
        ],
        [],
        {("g1", 0): "Nc3", ("g2", 0): "Nc3", ("g3", 0): "e5"},
    )

    assert clusters[0].best_move == "Nc3"


def test_a_position_with_no_recorded_engine_move_says_so() -> None:
    """No mapping entry means no engine move, and the field says that plainly.

    ``best_move`` is ``str`` in the frozen contract, so the empty string is the
    documented "no engine move was recorded for this position"; the report renders
    it as an em dash beside the same treatment it gives a missing ECO.
    """
    clusters = aggregate([scored("g1", 0, START_FEN)], [], {})

    assert clusters[0].best_move == NO_BEST_MOVE
    assert NO_BEST_MOVE == ""


def test_the_cluster_reports_the_worst_class_it_contains() -> None:
    """``worst_klass`` is the class of the worst admitted move, in the module's order."""
    clusters = aggregate(
        [
            scored("g1", 0, START_FEN, move_san="a", klass=INACCURACY, winprob_drop=0.08),
            scored("g2", 0, START_FEN, move_san="b", klass=BLUNDER, winprob_drop=0.35),
            scored("g3", 0, START_FEN, move_san="c", klass=MISTAKE, winprob_drop=0.20),
            scored("g4", 0, START_FEN, move_san="d", klass=OK, winprob_drop=0.00),
        ],
        [flag("g4", 0, START_FEN, my_move="d", best_move="e5")],
        {},
    )

    assert clusters[0].worst_klass == BLUNDER
    assert clusters[0].occurrences == 4


# -- ranking -----------------------------------------------------------------


def test_aggregate_is_unsorted_and_rank_clusters_sorts_by_composite() -> None:
    """``aggregate`` does not rank; ``rank_clusters`` does.

    Splitting them means the caller chooses a ranking (or none) and the report can
    re-sort defensively, as the design record requires of it. The order
    ``aggregate`` returns is first-seen, which keeps a run reproducible.
    """
    weak_once = scored("g1", 0, OTHER_FEN, move_san="Bb5", klass=INACCURACY, winprob_drop=0.08)
    strong_twice = scored("g2", 0, START_FEN, klass=BLUNDER, winprob_drop=0.35)
    clusters = aggregate(
        [weak_once, strong_twice, scored("g3", 0, START_FEN, winprob_drop=0.35)], [], {}
    )

    assert [c.fen_before for c in clusters] == [OTHER_FEN, START_FEN], "first-seen order"

    ranked = rank_clusters(clusters)
    assert [c.fen_before for c in ranked] == [START_FEN, OTHER_FEN], "composite descending"
    assert [c.composite_score for c in ranked] == sorted(
        (c.composite_score for c in clusters), reverse=True
    )
    # Frequency is the multiplier the product ranks on: two 0.35 blunders (0.70)
    # outrank one 0.08 inaccuracy, which is the whole claim of the composite.
    assert ranked[0].composite_score == pytest.approx(0.70)
    assert ranked[1].composite_score == pytest.approx(0.08)


def test_rank_clusters_leaves_the_callers_list_alone() -> None:
    """Ranking returns a new list; a caller's list is not re-ordered underneath it."""
    clusters = aggregate(
        [
            scored("g1", 0, OTHER_FEN, move_san="Bb5", klass=INACCURACY, winprob_drop=0.08),
            scored("g2", 0, START_FEN, klass=BLUNDER, winprob_drop=0.35),
        ],
        [],
        {},
    )
    before = list(clusters)

    rank_clusters(clusters)

    assert clusters == before


def test_is_habit_is_reached_more_than_once() -> None:
    """A habit is ``occurrences >= 2``; the threshold is the operator's 2026-10-02 ruling.

    ``outcome O2``: a position reached once is not a learning opportunity however
    bad the move was, so it is not a habit and the report does not surface it.
    """
    once = aggregate([scored("g1", 0, OTHER_FEN)], [], {})
    twice = aggregate([scored("g1", 0, START_FEN), scored("g2", 0, TRANSPOSED_FEN)], [], {})

    assert HABIT_MIN_OCCURRENCES == 2
    assert not is_habit(once[0]), "reached once is not a habit"
    assert is_habit(twice[0]), "reached twice, at two move numbers, is one habit"


def test_rank_habits_drops_one_offs_and_orders_by_frequency_then_cost() -> None:
    """The release's ranking rule (O2): frequency first, cost as the tiebreak.

    The clusters are built so that the two orders disagree - a single 0.90-drop
    blunder is the most expensive thing the player did, and the operator's ruling
    says it is still not what the report is for. It is the case the report unit
    renders away, and it is why ``rank_habits`` exists beside ``rank_clusters``
    rather than replacing it: the composite ordering is still the honest
    description of severity, and the habit ordering is the honest description of
    what a player should go and fix.
    """
    clusters = aggregate(
        [
            # One occurrence, the biggest drop in the run: withheld.
            scored("g1", 0, OTHER_FEN, move_san="Bb5", klass=BLUNDER, winprob_drop=0.90),
            # Three occurrences of a small leak: a habit, and the most repeated.
            scored("g2", 0, FRENCH_FEN, klass=INACCURACY, winprob_drop=0.10),
            scored("g3", 0, FRENCH_FEN, klass=INACCURACY, winprob_drop=0.10),
            scored("g4", 0, FRENCH_FEN, klass=INACCURACY, winprob_drop=0.10),
            # Two occurrences of a big one: a habit, and the costlier of the two.
            scored("g5", 0, START_FEN, klass=BLUNDER, winprob_drop=0.35),
            scored("g6", 0, TRANSPOSED_FEN, klass=BLUNDER, winprob_drop=0.35),
        ],
        [],
        {},
    )
    assert len(clusters) == 3, "three distinct positions"

    habits = rank_habits(clusters)

    # Frequency first: the three-occurrence leak outranks the costlier pair even
    # though its composite is the lower of the two, which is what the operator's
    # ruling asks for and what a composite-descending sort would get wrong.
    assert [c.fen_before for c in habits] == [FRENCH_FEN, START_FEN]
    assert [c.occurrences for c in habits] == [3, 2]
    assert habits[0].composite_score == pytest.approx(0.30)
    assert habits[1].composite_score == pytest.approx(0.70)
    assert rank_clusters(habits)[0] is habits[1], "the composite order is the other one"

    # The composite order is the other one, and it starts with the withheld one-off.
    assert [c.fen_before for c in rank_clusters(clusters)][0] == OTHER_FEN
    assert OTHER_FEN not in [c.fen_before for c in habits], "the one-off is not a habit"


def test_rank_habits_keeps_a_tie_in_the_pipeline_order() -> None:
    """Equal frequency *and* equal cost keep the caller's order, so runs repeat."""
    clusters = aggregate(
        [
            scored("g1", 0, OTHER_FEN, move_san="Bb5", klass=INACCURACY, winprob_drop=0.08),
            scored("g2", 0, START_FEN, klass=INACCURACY, winprob_drop=0.08),
            scored("g3", 0, START_FEN, klass=INACCURACY, winprob_drop=0.08),
        ],
        [],
        {},
    )
    habits = rank_habits(clusters)

    assert [c.fen_before for c in habits] == [START_FEN], "one habit, at occurrences 2"
    assert [c.occurrences for c in habits] == [2]
    assert rank_habits([]) == []
    assert rank_habits(list(clusters)) is not clusters, "a new list, the caller's untouched"


def test_a_cluster_is_built_from_real_types_and_a_real_counter() -> None:
    """The record's own requirement: ``report.py`` must be able to build one.

    ``Severity``, ``DeviationFlag``, ``Cluster`` and ``Counter`` are the real
    classes here, so the seam the report unit codes against is this one.
    """
    severity = Severity(cp_loss=120, winprob_drop=0.2, klass=MISTAKE)
    deviation = flag("g1", 0, START_FEN)
    moves = Counter({"Nf3": 1})

    cluster = Cluster(
        eco="C50",
        fen_before=START_FEN,
        occurrences=1,
        my_moves=moves,
        best_move="Nc3",
        avg_winprob_drop=severity.winprob_drop,
        max_winprob_drop=severity.winprob_drop,
        deviation_count=1,
        worst_klass=severity.klass,
        composite_score=0.25,
    )

    assert isinstance(cluster, Cluster)
    assert cluster.my_moves is moves
    assert cluster.worst_klass == MISTAKE
    assert aggregate([scored("g1", 0, START_FEN)], [deviation], {("g1", 0): "Nc3"})[0].my_moves == {
        "Nf3": 1
    }


def test_scored_move_from_a_real_ply_record_carries_every_field() -> None:
    """The classmethod that builds a ``ScoredMove`` from a real ``PlyRecord``.

    ``cli.py`` pairs an extracted record with a severity; doing that in one place
    means the field mapping cannot drift between the two callers that do it.
    """
    from tests.game_records import make_record

    from src.chessleak.pgnio import extract_opening_plies

    record = make_record(
        id="g1",
        pgn='[Event "?"]\n[ECO "C50"]\n\n1. e4 e5 2. Nf3 *\n',
        my_color="white",
    )
    plies = extract_opening_plies(record, max_plies=2)
    ply = plies[0]

    scored_move = ScoredMove.from_ply(ply, Severity(cp_loss=30, winprob_drop=0.05, klass=OK))

    assert scored_move.game_id == "g1"
    assert scored_move.ply_index == 0
    assert scored_move.fen_before == ply.fen_before
    assert scored_move.move_san == "e4"
    assert scored_move.eco == "C50"
    assert scored_move.is_my_move is True
    assert scored_move.severity.klass == OK
