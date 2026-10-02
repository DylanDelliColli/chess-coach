"""The report: what a person reads instead of the raw clusters.

The report is the whole product. Everything upstream of it - the engine, the
severity curve, the book band, the clustering - exists to fill in the fields a
:class:`~chessleak.cluster.Cluster` carries, and this unit's job is to put those
fields in front of a person in the order that answers "what do I keep getting
wrong, and what should I have played?". So the tests here are about what a reader
sees, in this order:

* **the ranking is the product's claim** - rank 1 is the highest composite score,
  and it must be even when the caller hands the clusters over unsorted, which is
  what :func:`~chessleak.cluster.aggregate` returns;
* **each entry is a position, a move and its alternative** - a board diagram, what
  the player played here and how often, what the engine wanted, and what that
  cost in win probability;
* **the header is the run's provenance** - games, skipped games, positions
  evaluated, flagged mistakes, cache hit rate - the numbers ``cli.py`` computes
  and this module only renders.

The types under test are the **real** frozen ones, the real
:class:`~chessleak.cluster.Cluster` with a real :class:`collections.Counter` of the
player's SAN moves, because a look-alike dataclass with the same field names would
pass every assertion in this file and then break the CLI at the seam. The
severities are hand-built: this unit consumes classifications, it does not produce
them (``severity.py`` is where an engine's numbers become arithmetic), and the
integration test feeds this module clusters a real engine produced.

Two decisions are pinned here rather than left to taste, because they are the ones
a reader would notice:

* **The board is drawn in a fenced block of Unicode pieces** (``♜ ♞ ♝`` and
  ``.`` for an empty square), from White's side. The module docstring of
  ``report.py`` argues the trade-off against embedded SVG; this file pins the
  output, glyph for glyph, so the choice cannot drift silently. Every glyph is
  East-Asian-width *neutral* and every empty square is ASCII, so the grid keeps
  its columns in a monospace terminal instead of drifting the way an ambiguous
  width character would.
* **A chess.com opening URL is shortened to its last path segment, once, at render
  time.** ``cluster.py`` keeps the label raw (ruled on ``chess-egx``), so this is
  the only place the rule exists and the only place it can be tested;
  :func:`test_eco_label_renders_readably` is that test.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from src.chessleak.cluster import NO_BEST_MOVE, Cluster, rank_clusters
from src.chessleak.report import (
    DEVIATION_MARKER,
    EM_DASH,
    format_eco,
    render_board,
    render_report,
)

pytestmark = pytest.mark.unit

#: The real starting position, from python-chess itself rather than typed by
#: hand, so the expected diagram below cannot disagree with the FEN it draws.
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

#: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6, black to move. A non-starting position, and one
#: with castling rights and a halfmove clock, so the diagram is not accidentally
#: right only for the opening array.
SPANISH_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 4"

#: The board a reader sees for :data:`START_FEN`: file letters above and below,
#: rank numbers down the side, Unicode pieces and a period for an empty square.
START_BOARD = """\
    a b c d e f g h
 8  ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜
 7  ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟
 6  . . . . . . . .
 5  . . . . . . . .
 4  . . . . . . . .
 3  . . . . . . . .
 2  ♙ ♙ ♙ ♙ ♙ ♙ ♙ ♙
 1  ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖
    a b c d e f g h"""

SPANISH_BOARD = """\
    a b c d e f g h
 8  ♜ . ♝ ♛ ♚ ♝ . ♜
 7  ♟ ♟ ♟ ♟ . ♟ ♟ ♟
 6  . . ♞ . . ♞ . .
 5  . . . . ♟ . . .
 4  . . ♗ . ♙ . . .
 3  . . . . . ♘ . .
 2  ♙ ♙ ♙ ♙ . ♙ ♙ ♙
 1  ♖ ♘ ♗ ♕ ♔ . . ♖
    a b c d e f g h"""

#: The summary ``cli.py`` computes, with the six fields the design record freezes.
SUMMARY = {
    "username": "jefferyx",
    "games_analyzed": 20,
    "games_skipped": 2,
    "positions_evaluated": 231,
    "flagged_mistakes": 6,
    "cache_hit_rate": 0.712,
}


def make_cluster(**overrides) -> Cluster:
    """A real ``Cluster``, with the real Counter of the player's own moves.

    Every field is stated, so an individual test overrides only the one thing it
    is about; a new field on the frozen dataclass makes this fail loudly rather
    than be silently defaulted here.
    """
    fields = {
        "eco": "C65",
        "fen_before": SPANISH_FEN,
        "occurrences": 4,
        "my_moves": Counter({"Bxf7+": 3, "Bxc7": 1}),
        "best_move": "Qxf7+",
        "avg_winprob_drop": 0.214,
        "max_winprob_drop": 0.339,
        "deviation_count": 2,
        "worst_klass": "blunder",
        "composite_score": 0.936,
    }
    fields.update(overrides)
    return Cluster(**fields)


def render(tmp_path: Path, clusters, top_n: int = 20, summary=None) -> str:
    """Render to a real file under ``tmp_path`` and hand back what was written."""
    out = render_report(clusters, top_n, tmp_path / "report.md", summary or SUMMARY)
    return out.read_text(encoding="utf-8")


# -- the bead's named test ---------------------------------------------------


def test_render_contains_top_clusters(tmp_path: Path) -> None:
    """The named test: a ranked entry shows the position, the move, the cost.

    Deliberately handed the clusters **unsorted**, in the order
    :func:`~chessleak.cluster.aggregate` produces them, because ``report.py`` is
    required to re-sort defensively: a caller that forgets ``rank_clusters`` must
    not get a report whose rank 1 is somebody's worst leak.
    """
    worst = make_cluster(
        eco="C65",
        composite_score=0.936,
        occurrences=4,
        my_moves=Counter({"Bxf7+": 3, "Bxc7": 1}),
        best_move="Qxf7+",
        avg_winprob_drop=0.214,
        max_winprob_drop=0.339,
        deviation_count=2,
        worst_klass="blunder",
        fen_before=SPANISH_FEN,
    )
    milder = make_cluster(
        eco="C42",
        fen_before=START_FEN,
        composite_score=0.211,
        occurrences=2,
        my_moves=Counter({"Nc3": 2}),
        best_move="Nf3",
        avg_winprob_drop=0.11,
        max_winprob_drop=0.11,
        deviation_count=0,
        worst_klass="inaccuracy",
    )
    # Lowest composite first, so an implementation that trusted its input would
    # put this one at rank 1 and fail the ordering assertion below.
    clusters = [milder, worst]

    text = render(tmp_path, clusters, top_n=2)

    # 1. The ranking, in composite order, numbered from one.
    assert text.index("## 1. C65") < text.index("## 2. C42"), text
    assert "## 3." not in text, "top_n=2 renders two entries"

    # 2. A board diagram of the position the mistake was made in, glyph for glyph.
    assert f"```\n{SPANISH_BOARD}\n```" in text, text
    assert f"```\n{START_BOARD}\n```" in text, text

    # 3. The move-versus-best line, with the player's own move and its count.
    assert "**Your move:** `Bxf7+` ×3, `Bxc7` ×1" in text, text
    assert "**engine's best:** `Qxf7+`" in text, text

    # 4. A non-zero win%-lost figure, average and worst, in percent.
    assert "**Win% lost:** 21.4% average, 33.9% worst" in text, text
    assert "11.0% average" in text, text
    assert "0.0%" not in text, "every entry here loses win probability"

    # 5. The rest of what the outcome names, and the header's provenance.
    assert "- **Seen:** 4 times" in text, text
    assert "**Worst:** `blunder`" in text, text
    assert f"{DEVIATION_MARKER} flagged in 2 of 4 times" in text, text
    assert "# chessleak report — jefferyx" in text, text
    assert "- **Games analyzed:** 20" in text, text
    assert "- **Games skipped:** 2" in text, text
    assert "- **Positions evaluated:** 231" in text, text
    assert "- **Flagged mistakes:** 6" in text, text
    assert "- **Eval cache hit rate:** 71.2%" in text, text
    assert text.endswith("\n"), "a markdown file ends with a newline"


# -- the defensive re-sort ----------------------------------------------------


def test_ranks_by_composite_not_by_input_order(tmp_path: Path) -> None:
    """Rank 1 is the highest composite, whatever order the caller used."""
    clusters = [
        make_cluster(composite_score=1.0, eco="A00", best_move="a1"),
        make_cluster(composite_score=9.0, eco="B00", best_move="b1"),
        make_cluster(composite_score=5.0, eco="C00", best_move="c1"),
    ]
    text = render(tmp_path, list(reversed(clusters)), top_n=3)
    assert text.index("## 1. B00") < text.index("## 2. C00") < text.index("## 3. A00")

    # Same order as the release's own ranking, so the two cannot disagree.
    assert [c.eco for c in rank_clusters(clusters)] == ["B00", "C00", "A00"]


def test_ranking_keeps_a_tie_in_the_pipeline_order(tmp_path: Path) -> None:
    """Equal scores keep the caller's order, so a report is reproducible."""
    clusters = [
        make_cluster(composite_score=2.0, eco="A00", best_move="a1"),
        make_cluster(composite_score=2.0, eco="B00", best_move="b1"),
    ]
    assert "## 1. A00" in render(tmp_path, clusters, top_n=2)


def test_top_n_truncates_and_says_how_many_were_left_out(tmp_path: Path) -> None:
    """``top_n`` is a display cap, and the report says what it capped."""
    clusters = [make_cluster(composite_score=float(i), eco=f"E{i:02d}") for i in range(7)]
    text = render(tmp_path, clusters, top_n=3)
    assert "## 1. E06" in text and "## 3. E04" in text
    assert "## 4." not in text
    assert "top 3 of 7" in text, text


def test_top_n_larger_than_the_list_renders_all_of_them(tmp_path: Path) -> None:
    """A cap above the number of clusters is not a claim that entries are missing."""
    text = render(tmp_path, [make_cluster(composite_score=1.0)], top_n=1000)
    assert "1 recurring position" in text, text
    assert "## 1." in text


def test_negative_top_n_is_rejected(tmp_path: Path) -> None:
    """A negative cap is a usage error at the edge, not a silently empty report."""
    with pytest.raises(ValueError, match="top_n"):
        render_report([], -1, tmp_path / "report.md", SUMMARY)


# -- the board ----------------------------------------------------------------


def test_board_is_drawn_from_white_and_names_who_is_to_move() -> None:
    """Both orientations of the diagram are pinned, and the side to move is stated.

    The board is never flipped for the player: ``Cluster`` carries no colour, and
    the frozen contract has no field for one, so a report that guessed would be
    guessing. The reader is told who is to move instead.
    """
    assert render_board(START_FEN) == START_BOARD
    assert render_board(SPANISH_FEN) == SPANISH_BOARD


def test_side_to_move_is_stated_for_both_sides(tmp_path: Path) -> None:
    """A position says who is to move, so the diagram is never ambiguous."""
    black = render(tmp_path, [make_cluster(fen_before=SPANISH_FEN)], top_n=1)
    assert "Black to move" in black, black
    assert "White to move" not in black, black

    white = render(tmp_path, [make_cluster(fen_before=START_FEN)], top_n=1)
    assert "White to move" in white, white
    assert "Black to move" not in white, white


def test_the_fen_travels_with_the_diagram(tmp_path: Path) -> None:
    """The full FEN is kept for display, and it is the one the engine saw."""
    text = render(tmp_path, [make_cluster(fen_before=SPANISH_FEN)], top_n=1)
    assert SPANISH_FEN in text, text


def test_an_unparseable_position_is_reported_not_crashed(tmp_path: Path) -> None:
    """A FEN python-chess cannot read still produces a report that says so.

    ``cli.py`` checks for upstream errors, but a report generator that dies on one
    bad record loses the other four hundred games' worth of findings with it.
    """
    text = render(tmp_path, [make_cluster(fen_before="not a fen at all")], top_n=1)
    assert "not a fen at all" in text, text
    assert "could not be drawn" in text, text


# -- the ECO label (chess-egx) ------------------------------------------------


def test_eco_label_renders_readably() -> None:
    """The one place a raw ECO label is prettified, pinned case by case.

    ``chess-egx``: ``cluster.py`` keeps the label exactly as the data had it,
    because a data layer that rewrites a value it did not create cannot be audited
    against its source, and the same cluster may be rendered in more than one
    surface. So the rule lives here, once, and these are its cases: a label that
    parses as a URL shows its final path segment with spaces substituted, anything
    else shows as it is, and no label at all is an em dash.
    """
    # A real label out of the recorded cassette, verbatim.
    assert (
        format_eco("https://www.chess.com/openings/Grob-Opening-1...e5")
        == "Grob-Opening-1...e5"
    )
    assert (
        format_eco("https://www.chess.com/openings/English-Opening-Kings-English-Variation-2.d3")
        == "English-Opening-Kings-English-Variation-2.d3"
    )
    # The same opening, spelled the three other ways a label can arrive.
    assert format_eco("https://www.chess.com/openings/Queen's Gambit Declined") == (
        "Queen's-Gambit-Declined"
    )
    assert format_eco("https://www.chess.com/openings/Queen's Gambit Declined/") == (
        "Queen's-Gambit-Declined"
    )
    assert format_eco("https://www.chess.com/openings/Foo?ref=bar#top") == "Foo"
    assert format_eco("www.chess.com/openings/Foo") == "Foo"
    assert format_eco("https://www.chess.com/") == EM_DASH, (
        "a URL with no opening segment has no readable name to show"
    )
    # A percent-escaped space is a space in the name the reader knows it by.
    assert format_eco("https://www.chess.com/openings/King%27s%20Pawn%20Opening") == (
        "King's-Pawn-Opening"
    )
    # An ECO code is not a URL and is shown as it is, spaces and all.
    assert format_eco("C65") == "C65"
    assert format_eco("A45") == "A45"
    assert format_eco("B  Chess, absolutely") == "B Chess, absolutely"
    # No label at all: the design record says ~12% of real games carry none.
    assert format_eco(None) == EM_DASH
    assert format_eco("") == EM_DASH
    assert format_eco("   ") == EM_DASH
    # A label cannot smuggle a second line of markdown into the report.
    assert "\n" not in format_eco("C65\n## 1. something else")


def test_a_url_label_is_shortened_in_the_written_report(tmp_path: Path) -> None:
    """The end-to-end consequence: no 90-character URL in a ranked entry."""
    text = render(
        tmp_path,
        [
            make_cluster(
                eco="https://www.chess.com/openings/Four-Knights-Game-Italian-Variation",
            )
        ],
        top_n=1,
    )
    assert "## 1. Four-Knights-Game-Italian-Variation" in text, text
    assert "chess.com" not in text, text
    assert len(max(text.splitlines(), key=len)) < 200, "no line runs away"


def test_a_cluster_with_no_eco_label_renders_an_em_dash(tmp_path: Path) -> None:
    text = render(tmp_path, [make_cluster(eco=None)], top_n=1)
    assert f"## 1. {EM_DASH}" in text, text


# -- one entry's fields -------------------------------------------------------


def test_no_deviation_marker_when_nothing_was_flagged(tmp_path: Path) -> None:
    """The marker means something: it appears only when a deviation was flagged."""
    with_flag = render(tmp_path, [make_cluster(deviation_count=2, occurrences=4)], top_n=1)
    without = render(tmp_path, [make_cluster(deviation_count=0, occurrences=4)], top_n=1)

    assert DEVIATION_MARKER in with_flag, with_flag
    assert "Book deviation" in with_flag, with_flag
    assert DEVIATION_MARKER not in without, without
    assert "Book deviation" not in without, without


def test_a_deviation_on_every_occurrence_is_still_one_marker(tmp_path: Path) -> None:
    """The marker's own ratio is a share, so a whole cluster of leaks reads as one."""
    text = render(tmp_path, [make_cluster(deviation_count=3, occurrences=3)], top_n=1)
    assert f"{DEVIATION_MARKER} flagged in 3 of 3 times" in text, text

    single = render(tmp_path, [make_cluster(deviation_count=1, occurrences=1)], top_n=1)
    assert f"{DEVIATION_MARKER} flagged in 1 of 1 time" in single, single
    assert "1 of 1 times" not in single, "a share of one is still one time"


def test_a_position_with_no_engine_move_says_so(tmp_path: Path) -> None:
    """``NO_BEST_MOVE`` is the empty string in a frozen ``str`` field."""
    text = render(tmp_path, [make_cluster(best_move=NO_BEST_MOVE)], top_n=1)
    assert f"**engine's best:** {EM_DASH}" in text, text


def test_the_usual_move_is_listed_most_frequent_first(tmp_path: Path) -> None:
    """Counts are ordered, and a tie is broken on the move itself, not on a hash.

    The player's own first move is usually the most frequent, so this is the line
    a reader scans; it has to be the same line on every run of the same data.
    """
    text = render(
        tmp_path,
        [make_cluster(my_moves=Counter({"Bb5": 1, "Bb3": 5, "Ba4": 1}))],
        top_n=1,
    )
    assert "**Your move:** `Bb3` ×5, `Ba4` ×1, `Bb5` ×1" in text, text


def test_win_percentages_keep_one_decimal(tmp_path: Path) -> None:
    """Two decimals of win probability is the difference between noise and a number."""
    text = render(
        tmp_path,
        [make_cluster(avg_winprob_drop=1 / 3, max_winprob_drop=0.5, composite_score=0.0)],
        top_n=1,
    )
    assert "**Win% lost:** 33.3% average, 50.0% worst" in text, text


# -- the header ---------------------------------------------------------------


def test_the_header_renders_the_summary_it_is_given(tmp_path: Path) -> None:
    """``summary`` is rendered, never computed: this module does not own a count."""
    text = render(
        tmp_path,
        [make_cluster()],
        top_n=1,
        summary={
            "username": "someone_else",
            "games_analyzed": 548,
            "games_skipped": 65,
            "positions_evaluated": 4634,
            "flagged_mistakes": 1209,
            "cache_hit_rate": 0.8734,
        },
    )
    assert "# chessleak report — someone_else" in text, text
    assert "- **Games analyzed:** 548" in text, text
    assert "- **Games skipped:** 65" in text, text
    assert "- **Positions evaluated:** 4634" in text, text
    assert "- **Flagged mistakes:** 1209" in text, text
    assert "- **Eval cache hit rate:** 87.3%" in text, text


def test_a_cache_hit_rate_already_in_percent_is_not_multiplied(tmp_path: Path) -> None:
    """The record defines the rate as a fraction; a caller in percent is not wrong.

    ``cache_hit_rate`` is ``hits / (hits + misses)`` in the design record, but the
    field is typed ``int | float | str`` and ``cli.py`` is a different unit. A
    value above 1 is already a percentage, and the only two values both readings
    agree about - 0 and 1 - render the same either way, so this cannot be wrong
    at the boundaries.
    """
    assert "87.3%" in render(tmp_path, [], summary={**SUMMARY, "cache_hit_rate": 87.3})
    assert "8700.0%" not in render(tmp_path, [], summary={**SUMMARY, "cache_hit_rate": 87.3})


def test_a_missing_summary_field_renders_a_dash_and_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A partial summary does not lose the report, and does not hide the gap."""
    text = render(tmp_path, [make_cluster()], top_n=1, summary={"username": "jefferyx"})
    assert "- **Games analyzed:** —" in text, text
    assert "games_analyzed" in caplog.text, caplog.text


def test_an_empty_username_still_names_the_report(tmp_path: Path) -> None:
    """A run with no username configured says what it is instead of a blank line."""
    text = render(tmp_path, [make_cluster()], top_n=1, summary={**SUMMARY, "username": ""})
    assert "# chessleak report" in text, text


# -- the file -----------------------------------------------------------------


def test_the_file_is_written_where_it_was_asked_for(tmp_path: Path) -> None:
    """The returned path is the one written, and its parent is created on demand."""
    out = render_report([make_cluster()], 5, tmp_path / "nested" / "deeper" / "report.md", SUMMARY)
    assert out == tmp_path / "nested" / "deeper" / "report.md"
    assert out.is_file()
    assert out.read_text(encoding="utf-8").startswith("# chessleak report")


def test_a_string_path_is_accepted(tmp_path: Path) -> None:
    """``cli.py`` may hand over what argparse gave it, which is a string."""
    out = render_report([make_cluster()], 5, str(tmp_path / "report.md"), SUMMARY)
    assert isinstance(out, Path)
    assert out.is_file()


def test_a_second_render_overwrites_rather_than_appends(tmp_path: Path) -> None:
    """The CLI re-runs over an unchanged cache; the report is replaced, not doubled."""
    out = tmp_path / "report.md"
    render_report([make_cluster()], 5, out, SUMMARY)
    first = out.read_text(encoding="utf-8")
    render_report([make_cluster()], 5, out, SUMMARY)
    assert out.read_text(encoding="utf-8") == first


def test_a_run_with_no_recurring_mistakes_says_so(tmp_path: Path) -> None:
    """An empty ranking is a finding - the player's openings are clean - not a bug."""
    text = render(tmp_path, [], top_n=20)
    assert "No recurring" in text, text
    assert "- **Flagged mistakes:** 6" in text, "the header still reports the run"
    assert "## 1." not in text, text
