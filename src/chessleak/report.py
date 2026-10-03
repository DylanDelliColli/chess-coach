"""The report: the player's recurring habits, written out for a person to read.

Everything upstream in this release exists to fill in the fields of a
:class:`~chessleak.cluster.Cluster`, and this module is where those fields stop
being numbers and become advice. It renders, and only renders: it does not
re-score, re-cluster, recompute a composite or touch the engine. It takes the list
``cluster.py`` produced, the ``top_n`` the operator configured, a path and the
``summary`` ``cli.py`` computed, and writes one markdown file. That boundary is
what makes it testable with no engine, no network and no cache - the properties
that let a unit test build real ``Cluster`` objects by hand and let the
integration test hand over clusters a real Stockfish produced.

**The report is a list of habits, and that is the operator's ruling.** "For now,
focus only on habits" (2026-10-02, outcome O2 of the release brief): a position
reached **once** is not a learning opportunity however bad the move was, so it is
not rendered at all - not ranked last, not summarised, absent. What is rendered
is ordered by **how often** the position recurred and only then by what the leak
cost, because the most-repeated leak is the first thing a player should read, and
among equally repeated ones the costlier is the worse habit. ``top_n`` therefore
truncates the habit list: a player with three habits gets a short report, which is
the honest result, and the page is never padded with one-offs to look fuller.
The filter is :func:`~chessleak.cluster.rank_habits`, called here defensively
rather than assumed of the caller, so a list straight out of
:func:`~chessleak.cluster.aggregate` - which is unfiltered by design - still
produces a habits-only report.

**The header says what the report left out, and in which direction it errs.** Two
sentences, both unconditional:

* the withheld count, with the reason - a position reached once is not a habit -
  so a player who suspects a missing entry can see that it was a deliberate
  omission and how many there were. The number is ``cli.py``'s, because it is a
  fact about the run, not about this list;
* **the habit list is a lower bound**, because only exact positions count as the
  same position. Cluster identity is :func:`~chessleak.config.position_key`, so
  two positions that are the same by transposition or by mirror image are two
  clusters, and the real count is at least this one. Positional similarity
  (deferred by the operator on ``chess-sco``) can only ever *raise* these counts,
  which is why this sentence may not be removed while that bead is open.

**The board diagram: a fenced block of Unicode pieces, not embedded SVG.** The
bead allows either, and the choice is worth writing down because it is a real
trade-off rather than a preference. Inline SVG in a markdown file needs an
``<img>`` tag with a data URI, and no common markdown viewer - GitHub included -
renders one; the reader gets a blank box or the raw text, and a terminal shows
nothing at all. It also would only pay for itself if the report had an HTML
sibling to point at, and that is beyond v1. A fenced block of Unicode piece
glyphs renders in a terminal, in a text editor, in every markdown viewer, in a
``less`` scroll and in a paste into an issue, needs no asset, no font beyond the
one already drawing a chess forum, and survives ``cat``. So: Unicode, in a fence,
drawn from White's side. Every glyph used is East-Asian-width *neutral*
(``U+2654``-``U+265F``, ``U+2691``) and every empty square is an ASCII period, so
the grid keeps its columns in a monospace cell - which an ambiguous-width
character such as a middle dot would not, in a terminal configured for a CJK
locale. The board is never flipped for the player, because ``Cluster`` carries no
colour and the frozen contract has no field for one; the report says who is to
move instead, which is the fact the reader actually needs.

**Three decisions this module owns, and why they are here and not upstream.**

* **The ranking is re-sorted defensively, and to the ruled order.**
  :func:`~chessleak.cluster.aggregate` returns clusters unsorted and
  :func:`~chessleak.cluster.rank_clusters` is the release's owner of the composite
  ordering, so the habit order
  (:func:`~chessleak.cluster.rank_habits`, which is a filter *and* a sort) is
  called here rather than written out again: a caller that forgets to rank, or
  that ranks by cost, therefore cannot produce a report whose rank 1 is somebody's
  worst one-off - the failure the operator's ruling removed.
* **A chess.com opening URL is shortened to its last path segment, here and once.**
  ``cluster.py`` keeps ``Cluster.eco`` raw, ruled on ``chess-egx``: a data layer
  that rewrites a value it did not create cannot be audited against its source,
  and the same cluster may be rendered in more than one surface. So the rule lives
  at the edge of the display: a label that parses as a URL shows its final path
  segment with whitespace substituted for spaces, anything else shows as it is,
  and no label at all is an em dash. About 12% of real games carry no ECO tag at
  all, so the em dash is a common line in a real report, not a corner case.
* **The summary is rendered, never computed.** ``cli.py`` owns the counts and the
  cache hit rate; this module prints what it is handed, and says so in a log
  warning when a field is missing rather than quietly printing a number of its own
  invention. A missing field renders as an em dash, because a report that crashed
  on a partial summary would lose the four hundred games' worth of findings in it.
  The withheld count is such a field: it is printed twice, once as a header bullet
  beside the other five and once inside the sentence that explains it, and both
  come from the one value, so they cannot disagree.

Two smaller rules, both about a reader rather than a machine: a value in
``0..1`` that means a share is printed as a percentage with one decimal, and a
``cache_hit_rate`` already given in percent (above 1) is not multiplied again -
the two readings can only disagree above 1, and agree at both ends of the range,
so the ambiguity in the field's type cannot produce a wrong figure. And a FEN
python-chess cannot parse does not lose the report: the entry is still written,
with the raw string and a line saying the position could not be drawn.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import unquote, urlparse

import chess

from .cluster import NO_BEST_MOVE, Cluster, rank_habits

__all__ = [
    "DEVIATION_MARKER",
    "EM_DASH",
    "LOWER_BOUND_SENTENCE",
    "SUMMARY_FIELDS",
    "WITHHELD_FIELD",
    "format_eco",
    "render_board",
    "render_report",
]

log = logging.getLogger(__name__)

#: What an absent value reads as. The design record fixes this for a cluster with
#: no ECO tag, and the same character answers the other two ways a field can be
#: empty here - a position with no engine move, and a summary field the caller
#: did not supply - so the report has one way of saying "nothing to show".
EM_DASH = "—"

#: The book-deviation marker, the U+2691 black flag. Narrow, so it does not
#: disturb a line of text, and unmistakably a flag to anyone who has seen one in
#: a chess annotation.
DEVIATION_MARKER = "⚑"

#: The ``summary`` field carrying how many positions the run reached only once.
#: ``chess-iql`` added it with the operator's habits-only ruling: a reader who can
#: see that twelve entries were withheld can weigh the list, and one who cannot is
#: being shown a list of unknown completeness. ``cli.py`` computes it from the
#: clusters the run produced; this module only prints it.
WITHHELD_FIELD = "one_off_positions_omitted"

#: The header fields, in the order the design record defines them. The tuple is
#: the order the report prints them in and the set the module's own tests check
#: against, so a field added to the record without a line here is a visible gap
#: rather than a silently missing number.
SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("games_analyzed", "Games analyzed"),
    ("games_skipped", "Games skipped"),
    ("positions_evaluated", "Positions evaluated"),
    ("flagged_mistakes", "Flagged mistakes"),
    ("cache_hit_rate", "Eval cache hit rate"),
    (WITHHELD_FIELD, "One-off positions omitted"),
)

#: The same fields keyed for lookup, so printing one does not rebuild the mapping.
_SUMMARY_LABELS = dict(SUMMARY_FIELDS)

#: One glyph per piece, white then black. Chosen over the ASCII letters ``KQRBNP``
#: for how it reads, and over the *solid* and *outlined* white-piece sets because
#: python-chess holds one ``PieceType`` per side: two glyph sets would mean a
#: colour the board does not know, and a filled set on both colours is
#: unambiguous at a glance in a terminal with no colour support.
_PIECE_GLYPHS: dict[chess.PieceType, tuple[str, str]] = {
    chess.KING: ("♔", "♚"),
    chess.QUEEN: ("♕", "♛"),
    chess.ROOK: ("♖", "♜"),
    chess.BISHOP: ("♗", "♝"),
    chess.KNIGHT: ("♘", "♞"),
    chess.PAWN: ("♙", "♟"),
}

#: The empty square. ASCII on purpose: see the module docstring on grid width.
_EMPTY_SQUARE = "."

#: The drawn board is this wide before the pieces: a rank number right-aligned in
#: two columns, then two spaces. The file-letter header is padded to match.
_RANK_LABEL = "{:>2}  "
_HEADER_PAD = "    "

#: What a share is printed with. One decimal is the difference between a number a
#: player can act on and noise from a logistic curve.
_PERCENT = "{:.1f}%"

#: The composite is a ranking key, not a measurement, so it does not need the
#: precision the win-probability figures do.
_COMPOSITE = "{:.2f}"

#: The standing sentence under the header, printed whether or not anything was
#: withheld. It is a property of how positions are counted rather than of this
#: run: cluster identity is ``position_key``, so a position reached twice by
#: transposition, or reached once as White and once as a mirrored board, is two
#: clusters rather than one, and the true habit count can only be higher. Keep it
#: while ``chess-sco`` (positional similarity, deferred by the operator on
#: 2026-10-02) is open: that work can only raise these counts, so removing the
#: sentence would be true by accident and wrong by omission.
LOWER_BOUND_SENTENCE = (
    "_This list is a lower bound: only exact positions count as the same position, so a "
    "transposed or mirrored repeat is counted separately and would only raise the count._"
)

#: The reason a one-off is not in the report. It is the operator's own argument,
#: so it is written once and quoted into the withheld sentence.
_NOT_A_HABIT = "reached once, so not habits"


# -- the ECO label (chess-egx) ------------------------------------------------


def _url_segment(label: str) -> str | None:
    """The final path segment of ``label`` if it is a URL, else ``None``.

    A label is a URL when it parses with an ``http``/``https`` scheme and a host,
    or when it is a bare ``www.`` address - the shape a hand-typed or truncated
    value takes. A three-letter ECO code is not a URL: ``urlparse`` gives it no
    scheme (a scheme cannot contain a digit), and the ``www.`` test does not match
    it, so ``C65`` is left alone by the same code path that shortens a URL.

    A URL with no path segment after the host answers the empty string, which is
    *not* the same as ``None``: it was recognised as a URL and has no opening name
    in it, so the caller shows the em dash rather than the whole address.
    """
    parsed = urlparse(label)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        path = parsed.path
    elif label.lower().startswith("www."):
        path = "/" + label.split("?", 1)[0].split("#", 1)[0]
    else:
        return None
    segments = [segment for segment in path.split("/") if segment]
    return segments[-1] if segments else ""


def format_eco(eco: str | None) -> str:
    """One ECO label, short enough to read as an opening name.

    The rule, decided on ``chess-egx`` and implemented only here: a label that
    parses as a URL shows its final path segment, with spaces substituted;
    anything else shows as it is; ``None`` shows as an em dash.

    Three details that are not decoration:

    * **Whitespace is collapsed first, for every label.** A label with a newline
      in it would break the ranked entry's own layout, so runs of whitespace
      become a single space. That is a rendering requirement rather than a
      prettification, which is why it applies to a plain code too.
    * **Percent escapes are decoded in the URL branch.** A chess.com slug with a
      space in it arrives as ``%20``; leaving that in the report would print
      ``King%27s%20Pawn%20Opening``, which is the failure the bead was raised to
      prevent, just spelled differently. No label in the recorded real data carries
      an escape, so this changes nothing real today and everything readable if it
      ever does.
    * **A URL with no opening segment answers the em dash.** A bare host names no
      opening, so there is no name to show.

    The raw value is logged at debug level whenever it is rewritten, so a
    prettified label can be traced back to the archive value it came from.
    """
    if eco is None:
        return EM_DASH
    label = " ".join(eco.split())
    if not label:
        return EM_DASH

    segment = _url_segment(label)
    if segment is None:
        return label

    readable = "-".join(unquote(segment).split())
    if not readable:
        log.debug("eco label %r has no opening segment, rendering as %s", eco, EM_DASH)
        return EM_DASH
    log.debug("eco label %r rendered as %r", eco, readable)
    return readable


# -- the board ----------------------------------------------------------------


def _side_to_move(fen: str) -> str:
    """Who is to move in ``fen``, read from the FEN's own second field.

    Read as text rather than through :class:`chess.Board` so that a FEN the board
    cannot parse still names a side to move: the report's promise is that a bad
    record costs one diagram, not the entry.
    """
    fields = fen.split()
    if len(fields) < 2:
        return "side to move unknown"
    if fields[1] == "w":
        return "White to move"
    if fields[1] == "b":
        return "Black to move"
    return "side to move unknown"


def render_board(fen: str) -> str:
    """Draw ``fen`` as ten lines of monospace text, from White's side.

    File letters above and below, rank numbers down the side, one glyph per
    occupied square and a period per empty one. A FEN that does not parse returns
    a single line saying so, having logged the reason, so one malformed record
    cannot take a whole report down with it.
    """
    try:
        board = chess.Board(fen)
    except ValueError as error:
        log.warning("position %r could not be parsed: %s", fen, error)
        return "(this position could not be drawn)"

    rows = [_HEADER_PAD + " ".join(chess.FILE_NAMES)]
    for rank in range(7, -1, -1):
        squares = []
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            if piece is None:
                squares.append(_EMPTY_SQUARE)
            else:
                white, black = _PIECE_GLYPHS[piece.piece_type]
                squares.append(white if piece.color == chess.WHITE else black)
        rows.append(_RANK_LABEL.format(rank + 1) + " ".join(squares))
    rows.append(_HEADER_PAD + " ".join(chess.FILE_NAMES))
    return "\n".join(rows)


# -- formatting ---------------------------------------------------------------


def _percent(value: float) -> str:
    """A share of 1.0 as a percentage, to one decimal."""
    return _PERCENT.format(value * 100)


def _cache_hit_rate(value: float) -> str:
    """The cache hit rate, whichever of the two plausible units it arrived in.

    The design record defines ``cache_hit_rate`` as ``hits / (hits + misses)``, a
    fraction, but the field is typed ``int | float | str`` and ``cli.py`` is a
    separate unit. A value above 1 is already a percentage. The two readings can
    only differ above 1, and 0 and 1 render identically either way, so this cannot
    print a wrong figure at either end of the range.
    """
    return _PERCENT.format(value if value > 1.0 else value * 100)


def _plural(count: int, noun: str) -> str:
    """``3 positions``, ``1 position`` - a count a reader does not have to parse."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _my_moves(cluster: Cluster) -> str:
    """The player's own moves here, most frequent first, with their counts.

    Ordered by count and then by the move itself, rather than by the Counter's
    insertion order: a reader scans the first move on this line, and the same data
    must produce the same line on every run.
    """
    if not cluster.my_moves:
        return EM_DASH
    ordered = sorted(cluster.my_moves.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"`{move}` ×{count}" for move, count in ordered)


def _best_move(cluster: Cluster) -> str:
    """The engine's move here, or the em dash when no engine move was recorded.

    :data:`~chessleak.cluster.NO_BEST_MOVE` is the empty string because the frozen
    ``Cluster.best_move`` is a ``str``; on the page it reads as the same "nothing
    to show" as every other absent value.
    """
    if not cluster.best_move or cluster.best_move == NO_BEST_MOVE:
        return EM_DASH
    return f"`{cluster.best_move}`"


def _summary_line(field: str, value: object) -> str:
    """One header line, or a logged gap and an em dash."""
    label = _SUMMARY_LABELS[field]
    if value is None:
        log.warning("summary has no %r field, rendering it as %s", field, EM_DASH)
        return f"- **{label}:** {EM_DASH}"
    if field == "cache_hit_rate":
        try:
            return f"- **{label}:** {_cache_hit_rate(float(value))}"
        except (TypeError, ValueError):
            return f"- **{label}:** {value}"
    return f"- **{label}:** {value}"


def _header(summary: Mapping[str, object]) -> list[str]:
    """The report's title and the run's provenance, in the record's field order."""
    username = str(summary.get("username") or "").strip()
    title = f"# chessleak report — {username}" if username else "# chessleak report"
    lines = [title, "", "Recurring opening habits, ranked by how often you reach them.", ""]
    lines += [_summary_line(field, summary.get(field)) for field, _ in SUMMARY_FIELDS]
    return lines


def _count(value: object) -> int | None:
    """A summary figure read as a count, or ``None`` when it is not one.

    A withheld count arrives as an ``int`` from ``cli.py`` and as a string from a
    hand-written summary, and anything else is a gap rather than a number to
    guess at - which is the same rule the rest of the header follows for a field
    the caller left out.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _withheld_line(count: object) -> str:
    """What the report left out, and why, in the reader's own terms.

    Printed even when the count is zero: "nothing was withheld" is a fact about
    the run worth stating once, and a run that found no one-offs at all is not
    rarer than a run that found only one-offs. A count the summary did not supply
    renders as the em dash with a logged warning, on the same terms as every other
    field here.
    """
    number = _count(count)
    if number is None:
        log.warning("summary has no %r field, rendering it as %s", WITHHELD_FIELD, EM_DASH)
        return f"_{EM_DASH} one-off positions omitted ({_NOT_A_HABIT})._"
    return f"_{_plural(number, 'one-off position')} omitted ({_NOT_A_HABIT})._"


def _entry(rank: int, cluster: Cluster) -> list[str]:
    """One ranked position: the board, the move, the alternative, the cost."""
    lines = [
        "",
        "---",
        "",
        f"## {rank}. {format_eco(cluster.eco)}",
        "",
        f"- **Composite score:** {_COMPOSITE.format(cluster.composite_score)}",
        f"- **Seen:** {_plural(cluster.occurrences, 'time')}",
        f"- **Worst:** `{cluster.worst_klass}`",
        f"- **Your move:** {_my_moves(cluster)} vs **engine's best:** {_best_move(cluster)}",
        f"- **Win% lost:** {_percent(cluster.avg_winprob_drop)} average, "
        f"{_percent(cluster.max_winprob_drop)} worst",
    ]
    if cluster.deviation_count > 0:
        lines.append(
            f"- **Book deviation:** {DEVIATION_MARKER} flagged in {cluster.deviation_count} "
            f"of {_plural(cluster.occurrences, 'time')}"
        )
    lines += [
        "",
        "```",
        render_board(cluster.fen_before),
        "```",
        "",
        f"{_side_to_move(cluster.fen_before)} · FEN `{cluster.fen_before}`",
    ]
    return lines


def _ranking_line(shown: int, total: int) -> str:
    """What the report is showing: the habit list, and what ``top_n`` capped.

    The wording names the order the reader is looking at, because "ranked" on its
    own does not say whether the first entry is the most repeated or the most
    expensive. It is a cap on the habit list only: a report that reported how many
    habits it left out by ``top_n`` would be a report about the display, and the
    withheld sentence below already accounts for what is genuinely not in it.
    """
    order = "by how often you reach them, then by what they cost"
    if shown >= total:
        return f"_{_plural(total, 'habit')}, {order}._"
    return f"_Showing the top {shown} of {_plural(total, 'habit')}, {order}._"


# -- the report ---------------------------------------------------------------


def render_report(
    clusters: Iterable[Cluster],
    top_n: int,
    out_path: Path | str,
    summary: Mapping[str, object],
) -> Path:
    """Write the ranked markdown report and return the path it was written to.

    ``clusters`` is what :func:`~chessleak.cluster.aggregate` produced; it is
    filtered and re-sorted here through
    :func:`~chessleak.cluster.rank_habits`, defensively, so unsorted input - and
    input that has not been filtered - cannot produce wrong ranks or a one-occurrence
    entry. ``top_n`` caps how many *habits* are rendered - the operator's
    ``Config.top_n`` - and the report states what it capped, because a report that
    silently dropped entries reads as a finding about the player's play when it is a
    fact about the display. It is never padded with the clusters that were left
    out: a player with two habits gets a two-entry report. A negative ``top_n``
    raises ``ValueError`` here rather than writing an empty report: it is a usage
    error, and ``cli.py`` turns one into its usage exit code.

    The "no recurring habits" section is a claim about the *run* - nothing recurred
    and nothing was played worse than the engine - so it is written from
    ``habits``, never from the truncated list. Gating it on what ``top_n`` left
    would let a capped report, ``--top 0`` above all, deny in its own body the
    habits its header has just counted, which is the worst kind of wrong for this
    file: the reader cannot tell a fact about their openings from a fact about the
    display, and this report exists to be acted on.

    ``out_path`` may be a ``Path`` or a string, since ``cli.py`` will have whatever
    argparse produced. Parent directories are created, so a first run does not
    need a ``mkdir`` the caller might forget, and an existing file is replaced, so
    a second run over an unchanged cache rewrites the report instead of appending
    to it.

    ``summary`` is rendered, never computed - it is ``cli.py``'s, and the count
    fields plus ``username`` are the ones the design record defines. A field the
    caller left out becomes an em dash and a log warning, not a number of this
    module's own invention. The withheld count is one of them: this module cannot
    know how many one-offs the run produced, because the list it is handed may
    already have been filtered, so it says what it is told.
    """
    if top_n < 0:
        raise ValueError(f"top_n must be zero or more, got {top_n}")

    habits = rank_habits(clusters)
    shown = habits[:top_n]
    summary = summary or {}

    lines = _header(summary)
    lines += ["", _ranking_line(len(shown), len(habits)), ""]
    lines += [_withheld_line(summary.get(WITHHELD_FIELD)), "", LOWER_BOUND_SENTENCE, ""]
    if not habits:
        lines += [
            "## No recurring habits",
            "",
            "No position in this run was both reached more than once and played worse "
            "than the engine's best. Nothing to fix here.",
        ]
    for rank, cluster in enumerate(shown, start=1):
        lines += _entry(rank, cluster)

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info(
        "wrote %s: %d of %d habits, top_n=%d",
        path,
        len(shown),
        len(habits),
        top_n,
    )
    return path
