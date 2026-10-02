"""The report seam: real clusters, a real engine, a real file on disk.

This is the composition the unit exists for and the one the design record names as
a required seam test: real PGN out of the real extractor, scored by a **real
``EngineService``** over UCI with the real sqlite cache, aggregated by the real
``cluster.aggregate``, ranked by the real ``rank_clusters``, and written by the real
``render_report`` to a real file. There is no stub and no mock anywhere in the
assertion path - the ECO label, the FEN, the SAN moves, the win-probability
figures and the best move in the finished report are the engine's and the fixture's
own.

**The corpus, and why it is shaped this way.** Two sources, both real:

* ``tests/fixtures/games_multi.pgn`` - verbatim PGN from one public chess.com
  monthly archive, provenance in ``tests/fixtures/pgn_fixtures.manifest.json``. The
  first **four** games in archive order are used: the same reproducible prefix rule
  the fetch unit recorded twenty games under, scaled down, because this unit needs a
  position that *recurs* and a large archive makes the test slow without making it
  truer. These are the games that supply the real ECO codes and the real opening
  positions.
* The two transposition lines ``1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Nxe5`` and its
  knight-shuffle twin, wrapped in chess.com-shaped PGN headers by
  :func:`pgn_of`. They are there for the one property the archive prefix cannot
  supply on its own: the same position reached at two different move numbers,
  which is what makes ``occurrences == 2`` and therefore what makes this a test of
  a *recurring* mistake rather than of a one-off. ``chess-usk`` measured the same
  thing on the same fixture and recorded why twenty games alone is not enough (see
  that file's docstring); a four-game prefix is smaller still, so the two lines are
  not decoration.

``Threads=1`` and the release's real-journey depth, for the reason every real
engine test here gives: Stockfish's search is only reproducible when it is told to
be, and the chief's ruling on ``chess-jc5`` makes the service default
``Threads=1`` for exactly this. Nothing here asserts an exact centipawn figure: the
assertions are about the report describing the clusters it was handed, and a number
pinned to one engine build would be the thing that breaks.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import re
from pathlib import Path
from typing import NamedTuple

import chess
import chess.pgn
import pytest
from tests.game_records import make_record

from src.chessleak.book import first_deviation
from src.chessleak.cluster import ScoredMove, aggregate, rank_clusters
from src.chessleak.config import Config
from src.chessleak.engine import EngineService
from src.chessleak.pgnio import extract_opening_plies
from src.chessleak.report import DEVIATION_MARKER, format_eco, render_report
from src.chessleak.severity import move_severity

pytestmark = pytest.mark.integration

#: The release's real-journey depth (``Config.analysis_depth``).
DEPTH = Config().analysis_depth

#: One thread, so the run is the same run twice. See the module docstring.
ENGINE_OPTIONS = {"Threads": "1", "Hash": "128"}

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MULTI_PGN = FIXTURES / "games_multi.pgn"
MANIFEST = FIXTURES / "pgn_fixtures.manifest.json"

#: The account the archive belongs to, read from the provenance manifest rather
#: than hard-coded twice: it is the name whose side of the board is the player's.
ACCOUNT = json.loads(MANIFEST.read_text())["source"]["account"]

#: How many of the archive's real games this file uses, and why (module docstring).
REAL_GAMES = 4

TRANSPOSITION_FIRST = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Nxe5"
TRANSPOSITION_SECOND = "1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Nf3 Nf6 5. Bc4 Nc6 6. Nxe5"
TRANSPOSITION_BLUNDER = "Nxe5"

#: Glyphs written out here, independently of ``report.py``'s own table, so this
#: file checks the diagram against python-chess rather than against the renderer
#: that produced it. Same mapping, two implementations: the point is that a flipped
#: board, a lost piece or a reversed rank order cannot pass.
GLYPHS = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}  # fmt: skip

#: The summary ``cli.py`` will compute. Written out here in full, because the point
#: of the seam is that ``render_report`` renders what it is handed and computes
#: nothing: these are the six fields the design record freezes.
SUMMARY = {
    "username": ACCOUNT,
    "games_analyzed": REAL_GAMES + 2,
    "games_skipped": 0,
    "positions_evaluated": 0,  # filled in from the run's own cache counters below
    "flagged_mistakes": 0,
    "cache_hit_rate": 0.0,
}


# -- the corpus ---------------------------------------------------------------


def pgn_of(line: str, game_id: str) -> str:
    """A chess.com-shaped PGN around one SAN line, with the tag the pipeline reads."""
    tags = {
        "Event": "?",
        "Site": "?",
        "Date": "2026.10.01",
        "ECO": "C60",
        "Link": f"https://www.chess.com/game/live/{game_id}",
    }
    head = "".join(f'[{key} "{value}"]\n' for key, value in tags.items())
    return f"{head}\n{line} *\n"


def fixture_games() -> list:
    """The first ``REAL_GAMES`` real games of the archive, as archive records.

    Parsed from the fixture's own PGN text with python-chess, and the player's
    colour derived from the two name headers against the account the provenance
    manifest names - the same rule ``fetch.py`` applies, so the corpus is what the
    pipeline would really have been handed.
    """
    handle = io.StringIO(MULTI_PGN.read_text())
    records = []
    while len(records) < REAL_GAMES:
        game = chess.pgn.read_game(handle)
        if game is None:
            break
        assert not game.errors, f"the fixture must parse: {game.errors}"
        records.append(
            make_record(
                id=game.headers["Link"].rstrip("/").rsplit("/", 1)[-1],
                pgn=str(game),
                eco=game.headers.get("ECO"),
                white=game.headers.get("White", ""),
                black=game.headers.get("Black", ""),
                my_color="white" if game.headers.get("White") == ACCOUNT else "black",
            )
        )
    assert len(records) == REAL_GAMES, "the fixture holds at least this many games"
    return records


def corpus() -> list:
    """The real games plus the two transposition lines, in pipeline order."""
    return fixture_games() + [
        make_record(
            id="transpose-a", pgn=pgn_of(TRANSPOSITION_FIRST, "transpose-a"), my_color="white"
        ),
        make_record(
            id="transpose-b", pgn=pgn_of(TRANSPOSITION_SECOND, "transpose-b"), my_color="white"
        ),
    ]


# -- the real run -------------------------------------------------------------


@pytest.fixture(scope="module")
def engine_path() -> str:
    """The engine binary this repository's config resolves to."""
    path = Config.from_env().stockfish_path
    if not os.path.exists(path):
        pytest.fail(
            f"no Stockfish binary at {path!r}: run scripts/get_stockfish.sh, or point "
            f"CHESSLEAK_STOCKFISH_PATH at an existing binary"
        )
    return path


def best_move_in_san(engine: EngineService, fen_before: str) -> str | None:
    """The engine's move for a position in SAN - what ``cli.py`` will hand over.

    ``EvalResult.best_move`` is UCI because the engine speaks UCI, and
    ``Cluster.best_move`` is SAN because the report shows it to a person.
    """
    uci = engine.analyse(fen_before).best_move
    if uci is None:
        return None
    return chess.Board(fen_before).san(chess.Move.from_uci(uci))


def score_games(engine: EngineService, records: list):
    """The whole upstream path over real games: extract, score, flag.

    The three arguments of ``aggregate``, exactly as the pipeline produces them.
    """
    scored: list[ScoredMove] = []
    deviations = []
    best_moves: dict[tuple[str, int], str] = {}
    config = Config()

    for record in records:
        plies = extract_opening_plies(record, max_plies=config.opening_plies)
        assert plies, f"game {record.id} yielded no ply records"
        for ply in plies:
            if not ply.is_my_move:
                continue
            scored.append(
                ScoredMove.from_ply(
                    ply, move_severity(engine.analyse(ply.fen_before),
                                        engine.analyse(ply.fen_after), record.my_color)
                )
            )
            san = best_move_in_san(engine, ply.fen_before)
            if san is not None:
                best_moves[(record.id, ply.ply_index)] = san
        deviation = first_deviation(plies, engine, band_cp=config.book_band_cp)
        if deviation is not None:
            deviations.append(deviation)

    return scored, deviations, best_moves


class RealRun(NamedTuple):
    """One real run's output: the clusters, the summary and the engine's counters."""

    clusters: list
    summary: dict
    hits: int
    misses: int


@pytest.fixture(scope="module")
def real_run(engine_path: str, tmp_path_factory: pytest.TempPathFactory) -> RealRun:
    """The whole pipeline over the corpus, once, for this module.

    Module-scoped because it is the expensive part: the real engine searching every
    distinct position of six real games at the release's own depth. The two tests
    that read it share one run, so they are also consistent with each other - the
    report under test is one run's report.
    """
    cache = tmp_path_factory.mktemp("report-seam") / "evalcache.sqlite"
    records = corpus()
    with EngineService(engine_path, DEPTH, cache, options=ENGINE_OPTIONS) as engine:
        scored, deviations, best_moves = score_games(engine, records)
        clusters = rank_clusters(aggregate(scored, deviations, best_moves))
        hits, misses = engine.hits, engine.misses

    summary = {
        **SUMMARY,
        "positions_evaluated": misses,
        "flagged_mistakes": sum(c.occurrences for c in clusters),
        "cache_hit_rate": hits / (hits + misses) if (hits + misses) else 0.0,
    }
    return RealRun(clusters, summary, hits, misses)


# -- reading the report back --------------------------------------------------


def read_report(clusters, out_path: Path, summary: dict) -> str:
    """Render with the real function and hand back what landed on disk."""
    written = render_report(clusters, out_path=out_path, top_n=20, summary=summary)
    assert written == out_path
    return out_path.read_text(encoding="utf-8")


def entries(text: str) -> list[str]:
    """The ranked entries, in the order the file presents them."""
    parts = re.split(r"^## \d+\. ", text, flags=re.M)[1:]
    return [part.split("\n## ", 1)[0] for part in parts]


def heading_of(text: str, rank: int) -> str:
    """The opening-name label of one ranked entry, as the reader sees it."""
    match = re.search(rf"^## {rank}\. (.+)$", text, flags=re.M)
    assert match is not None, f"no rank {rank} entry in:\n{text}"
    return match.group(1).strip()


def board_block(text: str, rank: int) -> str:
    """The ten lines of the diagram under one ranked entry."""
    body = entries(text)[rank - 1]
    blocks = re.findall(r"^```\n(.*?)^```$", body, flags=re.M | re.S)
    assert len(blocks) == 1, f"rank {rank} has {len(blocks)} board blocks, expected one"
    return blocks[0]


def cells_of(block: str) -> dict[str, str]:
    """``{"e4": "♙", "a1": "♖", ...}`` read out of a rendered diagram.

    Written against the diagram's *shape* - ten lines, file letters above and
    below, rank numbers down the side - rather than against any constant of
    ``report.py``, so a renderer that draws the wrong square fails here.
    """
    rows = block.rstrip("\n").split("\n")
    assert len(rows) == 10, f"a diagram is ten lines, got {len(rows)}"
    assert rows[0].split() == list("abcdefgh"), rows[0]
    assert rows[9].split() == list("abcdefgh"), rows[9]
    cells: dict[str, str] = {}
    for expected_rank, row in zip("87654321", rows[1:9], strict=True):
        label = row[:2].strip()
        assert label == expected_rank, f"rank order is wrong at {row!r}"
        squares = row[4:].split()
        assert len(squares) == 8, f"a rank is eight squares, got {row!r}"
        for file_letter, square in zip("abcdefgh", squares, strict=True):
            cells[f"{file_letter}{label}"] = square
    return cells


def expected_cells(fen: str) -> dict[str, str]:
    """The same map, from python-chess: the independent half of the comparison."""
    board = chess.Board(fen)
    out = {}
    for name in chess.SQUARE_NAMES:
        piece = board.piece_at(chess.parse_square(name))
        out[name] = GLYPHS[piece.symbol()] if piece is not None else "."
    return out


# -- the bead's named test ----------------------------------------------------


def test_report_from_real_clusters(real_run: RealRun, tmp_path: Path) -> None:
    """Real clusters, a real engine behind them, a real markdown file on disk.

    The bead's named seam: the report is written, it contains a real ECO code from
    the real archive and a real board diagram, and every figure in it is the
    cluster's own. What a four-game prefix cannot show on its own - a position
    reached more than once - the two transposition lines supply, so the ranking this
    file renders is a ranking of *recurring* leaks and not of one-offs.
    """
    clusters, summary = real_run.clusters, real_run.summary
    assert clusters, "a real run over real games produces real clusters"
    assert real_run.misses > 0, "the engine really ran"

    out = tmp_path / "report.md"
    text = read_report(clusters, out, summary)

    # 1. The file exists where it was asked for, and is a report.
    assert out.is_file() and out.stat().st_size > 0
    assert text.startswith(f"# chessleak report — {ACCOUNT}")

    # 2. A real ECO code, out of the real archive, as the rank-1 opening name.
    real_ecos = {game.eco for game in fixture_games() if game.eco}
    assert real_ecos, "the real archive games carry ECO tags"
    labels = [heading_of(text, rank) for rank in range(1, len(clusters) + 1)]
    assert any(label in real_ecos for label in labels), (
        f"no real ECO code among the headings: {labels}"
    )
    assert any(re.fullmatch(r"[A-E]\d\d", label) for label in labels), labels

    # 3. A real board diagram, square for square, of the position rank 1 is about.
    top = clusters[0]
    assert cells_of(board_block(text, 1)) == expected_cells(top.fen_before), (
        f"the diagram does not draw {top.fen_before}"
    )
    # ...and the FEN printed beside it is the one the engine was asked about.
    assert top.fen_before in entries(text)[0]

    # 4. The move, the alternative and the cost, for every entry, from the cluster.
    for rank, cluster in enumerate(clusters, start=1):
        body = entries(text)[rank - 1]
        for move, count in cluster.my_moves.items():
            assert f"`{move}` ×{count}" in body, (move, count, body)
        if cluster.best_move:
            assert f"**engine's best:** `{cluster.best_move}`" in body, body
        assert f"- **Seen:** {cluster.occurrences} time" in body, body
        assert f"{cluster.avg_winprob_drop * 100:.1f}% average" in body, body
        assert f"{cluster.max_winprob_drop * 100:.1f}% worst" in body, body

    # 5. At least one entry costs real win probability, and says so in percent.
    lossy = [c for c in clusters if c.avg_winprob_drop > 0]
    assert lossy, "a real engine over real games leaves a real leak"
    assert any(f"{c.avg_winprob_drop * 100:.1f}% average" in text for c in lossy)

    # 6. The recurring cluster the transposition lines were included to produce.
    recurring = [c for c in clusters if c.occurrences > 1]
    assert recurring, (
        "the two transposition lines reach one position twice, so the corpus should "
        f"hold a recurring cluster; it held {[(c.fen_before, c.occurrences) for c in clusters]}"
    )
    blunder = next(c for c in recurring if c.my_moves[TRANSPOSITION_BLUNDER])
    assert blunder.occurrences == 2
    assert blunder.max_winprob_drop > 0.30, "giving away a knight is not a marginal call"
    assert blunder.deviation_count >= 1
    recurring_body = next(e for e in entries(text) if blunder.fen_before in e)
    assert DEVIATION_MARKER in recurring_body, recurring_body

    # 7. Ranks are in composite order in the file, not just in the list.
    scores = [float(m) for m in re.findall(r"\*\*Composite score:\*\* (\d+\.\d\d)", text)]
    assert scores == sorted(scores, reverse=True), scores
    assert len(scores) == len(clusters)

    # 8. The header carries this run's own numbers.
    assert f"- **Games analyzed:** {summary['games_analyzed']}" in text
    assert f"- **Positions evaluated:** {summary['positions_evaluated']}" in text
    assert f"- **Eval cache hit rate:** {summary['cache_hit_rate'] * 100:.1f}%" in text
    assert real_run.hits > 0, "the cache was reused across games, as the pipeline intends"


def test_a_real_chess_com_url_label_is_shortened_at_render_time(
    real_run: RealRun, tmp_path: Path
) -> None:
    """The ``chess-egx`` rule, on a label out of the real archive rather than a typed one.

    The manifest records the chess.com opening URL each real game carries in the
    archive, which is the value ``pgnio`` falls back to when a PGN has no ``[ECO]``
    tag - about 12% of real games. ``cluster.py`` keeps it raw on purpose, so this
    is the one place it is shortened, and the test uses an archive value rather
    than an invented URL.
    """
    real_url = next(
        game["eco_url"]
        for game in json.loads(MANIFEST.read_text())["games_multi.pgn"]["games"]
        if game.get("eco_url")
    )
    assert real_url.startswith("https://www.chess.com/openings/")

    clusters = [
        dataclasses.replace(real_run.clusters[0], eco=real_url),
        *real_run.clusters[1:],
    ]
    text = read_report(clusters, tmp_path / "report.md", real_run.summary)

    assert heading_of(text, 1) == real_url.rsplit("/", 1)[-1], text
    assert "chess.com" not in text, "a 90-character URL must not reach a ranked entry"
    assert real_url not in text
    # The raw value is still what the cluster carries: rendering is the only place
    # it is rewritten, so the data layer stays auditable against the archive.
    assert clusters[0].eco == real_url
    assert format_eco(clusters[0].eco) == real_url.rsplit("/", 1)[-1]


def test_a_clean_run_writes_a_report_with_nothing_in_it(
    real_run: RealRun, tmp_path: Path
) -> None:
    """No clusters is a finding, not a crash: the provenance numbers still print.

    Worth a test of its own because it is the shape ``cli.py`` will hit on a player
    whose openings are sound, and it is the shape in which a report that fell over
    would lose the very numbers that explain why it is empty.
    """
    text = read_report([], tmp_path / "clean.md", real_run.summary)
    assert text.startswith(f"# chessleak report — {ACCOUNT}")
    assert "No recurring mistakes" in text, text
    assert f"- **Games analyzed:** {real_run.summary['games_analyzed']}" in text
    assert f"- **Positions evaluated:** {real_run.summary['positions_evaluated']}" in text
