"""The end-to-end proof: cassette HTTP, a real Stockfish, a real report on disk.

This is the test the design record calls *the pipeline's proof* and the bead calls
the *Prime-Directive integration test for the whole pipeline*. Nothing in the
assertion path is stubbed or mocked:

* **HTTP is real and replayed.** The committed ``bobbyfischer.yaml`` cassette -
  85 real games from ``https://api.chess.com/pub/player/bobbyfischer/games/2023/11``,
  recorded 2026-10-01 by ``chess-3if`` - is served by ``tests/support/vcr.py``
  with ``record_mode="none"``, so no socket is opened. Because this run names the
  month with ``--archive`` rather than enumerating the index, exactly one
  recorded interaction is played: the archive. The index is in the cassette too,
  but a bounded run has no reason to ask for it, and ``play_count == 1`` is the
  proof that the run read the game from the recording rather than the network.
* **The engine is real.** ``EngineService`` launches the shared Stockfish 19
  binary over UCI and searches it. Nothing fakes ``EvalResult``.
* **The filesystem is real.** Archives, the sqlite evaluation cache and the
  markdown report are real files in a real temporary directory.
* **Every module between them is real**: ``fetch``, ``pgnio``, ``engine``,
  ``book``, ``severity``, ``cluster``, ``report``.

So the assertions below are about a report the pipeline actually produced from
games chess.com actually published, scored by an engine that actually searched.

**Why ``--archive`` is passed.** The cassette holds exactly two interactions: the
archives *index* and the ``2023/11`` month. The index names ten months, and
``fetch.download_all`` walks them newest first, so a run that enumerated all ten
would ask for nine URLs that were never recorded. ``chess-3if`` published this
instruction for exactly this reason: bound the run to the month the cassette
holds. ``--archive`` is how the operator does the same thing by hand - "analyse
this month" - and it is what makes ``main(argv)`` itself, not just the library
call beneath it, runnable against real recorded input.

**What the numbers mean, and what they do not.** Assertions here are about
*relationships* the report's own figures express (``avg_winprob_drop > 0``,
``deviation_count > 0``, ``occurrences >= 2``, a cache hit rate that rises), never
about absolute centipawn or win-probability values: a magic constant pinned to one
engine build is the thing that breaks next week. The engine is deterministic per
the ``chess-jc5`` repair (``ucinewgame`` per position, ``Threads=1``), so these
relationships are stable across runs on this host, but they are the *shape* of the
finding, not its magnitude.

**Habits only (``chess-iql``, the operator's 2026-10-02 ruling).** The report this
file replays is a list of positions the player reached more than once, ordered by
how often, with a count of the one-offs that were withheld and a standing
lower-bound sentence in the header. Measured on this cassette and this bound, 30
games yield 82 clusters of which a single one recurs, so the *ordering* with more
than one habit is proved in ``tests/unit/test_report.py``; what this file proves
is that the filter holds on a real run: every one-occurrence position is absent
from the file, asserted as absence rather than as a count.

**The bare month ``--archive 2023/11``.** The run below names the month as a full
URL, so it never consults the account's archives index - which is why this module
asserts the index cache is *absent*. The natural thing to type is the month on its
own, and ``chess-iql`` made that work: the second fixture runs ``main`` again with
``--archive 2023/11`` over the same warm cache, and the only HTTP it makes is the
one index request that resolving the month needs. The full-URL run above is
unchanged by that, which is what the two runs together show.
"""

from __future__ import annotations

import contextlib
import io
import re
from pathlib import Path

import pytest
from tests.support.vcr import CASSETTE_DIR, cassette

from src.chessleak import cli
from src.chessleak.config import EVAL_CACHE_FILENAME, Config
from src.chessleak.fetch import CACHE_SUBDIR_INDEX, archives_url
from src.chessleak.report import SUMMARY_FIELDS, WITHHELD_FIELD

pytestmark = pytest.mark.integration

#: The account and the one month ``chess-3if`` recorded, published on that bead.
ACCOUNT = "bobbyfischer"
ARCHIVE_URL = "https://api.chess.com/pub/player/bobbyfischer/games/2023/11"
#: The same month as the operator would type it, which is what ``chess-iql`` made
#: work: resolved against the account's archives index rather than pasted as a URL.
ARCHIVE_MONTH = "2023/11"
INDEX_URL = archives_url(ACCOUNT)
CASSETTE = "bobbyfischer.yaml"

#: The bounded run the chief measured on this host: 30 games at depth 12 sits well
#: inside five minutes with the release's ``Threads=1`` default. Depth 18 remains
#: the product's real-journey setting (``test_arg_parsing`` asserts that).
MAX_GAMES = 30
DEPTH = 12


@pytest.fixture(scope="module")
def engine_path() -> str:
    """The real Stockfish binary, resolved the way a run resolves it."""
    path = Config().stockfish_path
    if not Path(path).exists():
        pytest.fail(
            f"no Stockfish binary at {path!r}: run scripts/get_stockfish.sh, or point "
            f"CHESSLEAK_STOCKFISH_PATH at an existing binary"
        )
    return path


def analyze_argv(cache_dir: Path, report: Path, engine_path: str, archive: str) -> list[str]:
    """The command line both real runs in this file use, spelled once.

    The two runs must differ in exactly one thing - how the month is named - so
    the argument list is built here and passed to ``cli.main`` by both, rather
    than copied into each fixture where they could drift.
    """
    return [
        "analyze",
        ACCOUNT,
        "--archive",
        archive,
        "--max-games",
        str(MAX_GAMES),
        "--depth",
        str(DEPTH),
        "--cache-dir",
        str(cache_dir),
        "--stockfish-path",
        engine_path,
        "--out",
        str(report),
    ]


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory, engine_path: str) -> dict:
    """One real end-to-end run of ``chessleak analyze``, kept for the file's tests.

    Module-scoped because it is the expensive part - a real engine searching every
    opening position of thirty real games - and the assertions below all describe
    *that* run, which is also what makes them consistent with each other: the
    report on disk and the numbers parsed out of it are one run's.

    A fresh cache directory per module, so the first run really is cold and the
    second-run cache assertions mean what they say.
    """
    work = tmp_path_factory.mktemp("cli-e2e")
    cache_dir = work / "cache"
    report = work / "report.md"

    with cassette(CASSETTE) as loaded:
        code = cli.main(analyze_argv(cache_dir, report, engine_path, ARCHIVE_URL))

    assert code == 0, "a real run over real games succeeds"
    text = report.read_text(encoding="utf-8")
    return {
        "code": code,
        "report": report,
        "text": text,
        "cache_dir": cache_dir,
        "played": loaded.play_count,
        # vcrpy 8 exposes no write_count; the write-protect flag is the stronger
        # statement anyway - with record_mode="none" the cassette is sealed, so a
        # run that tried to record into it would have raised rather than quietly
        # rewritten the committed fixture.
        "sealed": loaded.write_protected,
    }


@pytest.fixture(scope="module")
def analysis(run: dict, engine_path: str, tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The same real run again, over the now-warm cache, for the run's own numbers.

    ``cli.main`` returns an exit code, so the pipeline's own :class:`AnalysisResult`
    is not observable through it. Running the library call the command wraps -
    with the config the command line above parses, no stubs anywhere - is what
    lets the habits test compare the report on disk against the clusters the run
    actually produced, rather than against a count it made up. It costs no network
    and no searches: the archive and every evaluation are on disk already.
    """
    report = tmp_path_factory.mktemp("cli-e2e-analysis") / "report.md"
    argv = analyze_argv(run["cache_dir"], report, engine_path, ARCHIVE_URL)
    config, out_path = cli.config_from_args(cli.build_parser().parse_args(argv))

    with cassette(CASSETTE) as loaded:
        result = cli.analyze(config, out_path=out_path, progress=lambda _message: None)

    return {"result": result, "played": loaded.play_count, "report": report}


# -- the bare month run (chess-iql) -------------------------------------------


@pytest.fixture(scope="module")
def month_run(run: dict, tmp_path_factory: pytest.TempPathFactory, engine_path: str) -> dict:
    """The same real run, with the month named the way an operator would type it.

    Over the ``run`` fixture's warm cache, so the archive is served from disk and
    every position is answered from the evaluation cache: the only request this
    makes is the archives index that resolving ``2023/11`` needs, and the only
    thing it proves beyond that request is the report. Both streams are captured
    here rather than per test, because the output is a fact about the run rather
    than about a test.
    """
    report = tmp_path_factory.mktemp("cli-e2e-month") / "report.md"
    out, err = io.StringIO(), io.StringIO()
    with (
        cassette(CASSETTE) as loaded,
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = cli.main(analyze_argv(run["cache_dir"], report, engine_path, ARCHIVE_MONTH))

    return {
        "code": code,
        "report": report,
        "text": report.read_text(encoding="utf-8"),
        "cache_dir": run["cache_dir"],
        "played": loaded.play_count,
        "out": out.getvalue(),
        "err": err.getvalue(),
    }


def test_a_bare_month_archive_runs_against_the_real_cassette(month_run: dict) -> None:
    """``--archive 2023/11`` is the natural thing to type, and it now works.

    The defect ``chess-iql`` recorded: a bare month reached ``httpx`` as a URL
    and died with *"Request URL is missing an 'http://' or 'https://' protocol"*.
    The month is resolved against the account's own archives index - one recorded
    request, and the only one this run makes, because the month archive and every
    evaluation are already on disk from the run above.
    """
    assert month_run["code"] == 0, month_run["err"]
    assert month_run["played"] == 1, (
        "exactly one request: the archives index that the month was resolved "
        f"against, got play_count={month_run['played']}"
    )
    assert month_run["report"].is_file(), "the run wrote a report"
    assert month_run["text"].startswith(f"# chessleak report — {ACCOUNT}")
    # The index is now a real file on disk, keyed by the account, and it is what
    # the month was resolved against. Its presence is also the difference between
    # this run and the one above, which must not consult the index at all.
    index_files = list((Path(month_run["cache_dir"]) / CACHE_SUBDIR_INDEX).glob("*.json"))
    assert len(index_files) == 1, index_files
    index_text = index_files[0].read_text(encoding="utf-8")
    assert ARCHIVE_URL in index_text, "the cached index is the account's own"
    assert ARCHIVE_MONTH in index_text, "and it names the month the run asked for"


def test_the_run_prints_the_report_path_exactly_once(month_run: dict) -> None:
    """One line, on stdout: the path a script can rely on, said once.

    ``chess-iql``'s second defect: the path was printed twice, once by the run's
    own progress sink (stderr) and once by ``main`` (stdout). The stdout one is
    the one kept - it is the only thing on stdout, by ``cli.py``'s own contract -
    so a caller capturing stdout for the path still works and a reader at a
    terminal no longer sees the same sentence twice.
    """
    lines = [line for line in (month_run["out"] + month_run["err"]).splitlines() if "wrote" in line]
    assert len(lines) == 1, f"the report path is announced once, got {lines}"
    assert str(month_run["report"]) in month_run["out"], "on stdout, where a script reads it"
    assert "wrote" not in month_run["err"], month_run["err"][-500:]


# -- reading the report back --------------------------------------------------


def entries(text: str) -> list[str]:
    """The ranked entries, in the order the file presents them."""
    parts = re.split(r"^## \d+\. ", text, flags=re.M)[1:]
    return [part.split("\n## ", 1)[0] for part in parts]


def summary_of(text: str) -> dict[str, str]:
    """The header's ``- **Field:** value`` lines, as a mapping."""
    found: dict[str, str] = {}
    for field, label in SUMMARY_FIELDS:
        match = re.search(rf"^- \*\*{re.escape(label)}:\*\* (.+)$", text, flags=re.M)
        assert match is not None, f"the report header has no {label!r} line:\n{text[:800]}"
        found[field] = match.group(1).strip()
    return found


def value_of(body: str, label: str) -> str:
    """One bullet's value out of a ranked entry, by its bold label."""
    match = re.search(rf"^- \*\*{re.escape(label)}:\*\* (.+)$", body, flags=re.M)
    assert match is not None, f"no {label!r} line in the entry:\n{body}"
    return match.group(1).strip()


# -- the bead's named test ----------------------------------------------------


def test_end_to_end_small_sample(run: dict) -> None:
    """Real HTTP replay + real Stockfish + real fs -> a ranked report with a finding.

    The bead's acceptance, end to end: ``chessleak analyze <account> --out
    report.md`` writes a ranked report. What makes this a test of the *product*
    rather than of a file writer is the second half of the design record's
    assertion - at least one cluster whose ``avg_winprob_drop > 0`` **or**
    ``deviation_count > 0``. Merely ``occurrences >= 1`` would pass on a severity
    path that scored everything ``ok``, which is exactly the no-op the design
    review named, so this asserts a positive figure or a book flag instead.
    """
    text = run["text"]

    # 1. A report was written where it was asked for, and it is a report.
    report: Path = run["report"]
    assert report.is_file(), "the report file exists"
    assert report.stat().st_size > 0, "the report is not empty"
    assert text.startswith(f"# chessleak report — {ACCOUNT}"), text[:200]

    # 2. The cassette really was replayed, and nothing was recorded back into it.
    #    One played interaction is the month archive; the index in the same
    #    cassette goes unplayed because --archive names the month directly.
    assert run["played"] == 1, (
        f"the recorded month archive was replayed once, got play_count={run['played']}"
    )
    assert run["sealed"], "a replay run holds the cassette write-protected"

    # 3. The header counts real work, and counts the games the run really skipped.
    header = summary_of(text)
    analyzed = int(header["games_analyzed"])
    assert analyzed == MAX_GAMES, f"the bound was {MAX_GAMES}, the report says {analyzed}"
    assert int(header["games_skipped"]) >= 0, "games_skipped is a count, never negative"
    assert int(header["positions_evaluated"]) > 0, "the engine really evaluated positions"

    # 4. Ranked entries exist, and at least one of them is a real finding.
    bodies = entries(text)
    assert bodies, "the report ranks at least one recurring position"

    def drop_of(body: str) -> float:
        """The entry's average win-probability loss, as the fraction the report shows."""
        percent = re.search(r"([0-9.]+)% average", value_of(body, "Win% lost"))
        assert percent is not None, f"no average win% figure in the entry:\n{body}"
        return float(percent.group(1)) / 100.0

    def deviations_of(body: str) -> int:
        """How many of the entry's occurrences carried a book-deviation flag."""
        match = re.search(r"flagged in (\d+) of", body)
        return int(match.group(1)) if match else 0

    findings = [b for b in bodies if drop_of(b) > 0.0 or deviations_of(b) > 0]
    assert findings, (
        "no ranked position has a positive win-probability drop or a book deviation: "
        "every cluster the engine scored came back ok, which is the no-op severity "
        f"path this assertion exists to catch.\n{text}"
    )

    # 5. A cluster is a *habit*: the report ranks only positions reached more than
    #    once, and every entry says how often it was seen.
    recurrences = [
        int(re.search(r"(\d+) times", b).group(1)) for b in bodies if re.search(r"(\d+) times", b)
    ]
    assert recurrences, "every ranked entry reports how often it was seen"
    assert min(recurrences) >= 2, (
        f"a habits-only report has no entry below two occurrences: {sorted(recurrences)}"
    )

    # 6. The winning entry carries a real position, a real ECO label and the
    #    player's own move against the engine's - the four things a reader acts on.
    top = findings[0]
    assert "♔" in top and "♙" in top, "the entry draws the position in Unicode pieces"
    fen_match = re.search(r"FEN `([^`]+)`", top)
    assert fen_match is not None, f"the entry shows the position's FEN:\n{top}"
    assert len(fen_match.group(1).split()) >= 4, "the FEN is a whole position"
    assert re.search(r"^## \d+\. \S", text, flags=re.M), "every entry has an opening label"
    assert "`" in value_of(top, "Your move"), "the player's move is named in SAN"


# -- habits only (chess-iql) -------------------------------------------------


def test_the_report_holds_habits_and_says_what_it_withheld(run: dict, analysis: dict) -> None:
    """The operator's 2026-10-02 ruling, on the committed 85-game cassette.

    Three things, and the third is the one a weaker test would leave out:

    * **the entries are habits** - every one of them was reached at least twice;
    * **the order is by occurrences first** - a real run, whatever its
      cardinality, cannot be ranked by cost alone and still be a habit list;
    * **the one-offs are absent, not merely unmentioned** - the header states how
      many were withheld and why, and no entry with ``Seen: 1 time`` exists.

    The withheld count is checked against the run's own clusters rather than
    against a literal, so the number in the header is this run's: it is the
    difference between every position the engine flagged and the ones that recurred.
    """
    text = run["text"]
    bodies = entries(text)
    assert bodies, "this run has at least one habit to report"

    # 1. Habits only, asserted as absence: a one-occurrence entry would be a
    #    separate ranked block, and there is none.
    assert not re.search(r"\*\*Seen:\*\* 1 time\b", text), (
        f"a position reached once is not a habit and must not be rendered:\n{text}"
    )
    seen = [int(re.search(r"(\d+) times", body).group(1)) for body in bodies]
    assert seen == sorted(seen, reverse=True), (
        f"habits are ordered by how often they recur, got {seen}"
    )

    # 2. The header says what it withheld, and that the list is a lower bound.
    header = summary_of(text)
    withheld = int(header[WITHHELD_FIELD])
    assert withheld > 0, (
        "this 30-game run reaches many positions exactly once, so the header "
        f"must withhold some: {withheld}"
    )
    assert f"{withheld} one-off positions omitted" in text, text
    assert "reached once, so not habits" in text, text
    assert "lower bound" in text and "only exact positions count" in text, (
        "the standing lower-bound sentence, which holds while positional "
        f"similarity is deferred on chess-sco:\n{text}"
    )

    # 3. The count is this run's: the pipeline's own clusters, from a real second
    #    pass over the same warm cache, must agree with what the file says - the
    #    habits in it, in the run's order, and the one-offs it withheld.
    result = analysis["result"]
    assert analysis["played"] == 0, "the cross-check run read everything from disk"
    habits = list(result.clusters)
    assert habits, "the run produced at least one habit"
    assert all(cluster.occurrences >= 2 for cluster in habits)
    assert [re.search(r"FEN `([^`]+)`", body).group(1) for body in bodies] == [
        cluster.fen_before for cluster in habits
    ], "the file's entries are the run's habits, in the run's habit order"
    assert result.summary[WITHHELD_FIELD] > 0, "the run had one-offs to withhold"
    assert withheld == result.summary[WITHHELD_FIELD], (
        "the header's withheld count is the run's own, and it is the same figure "
        "the pipeline computed over the same data"
    )
    assert sum(cluster.occurrences for cluster in habits) <= int(header["flagged_mistakes"]), (
        "the flagged moves in the body are a subset of the run's flagged moves"
    )


def test_a_second_run_uses_the_cache_and_makes_no_request(
    run: dict, tmp_path: Path, engine_path: str
) -> None:
    """Outcome O1: a second run over an unchanged cache does no network work.

    The design record names this assertion - ``EngineService.hits > 0`` after a
    second run - and it is the one thing that proves the FEN cache is keyed by
    position and shared across games rather than re-derived per game. The archive
    cache and the evaluation cache are both warm; the header's cache hit rate is
    the visible proof, and the cassette's unchanged ``play_count`` is the proof
    that the second run made no HTTP request at all.
    """
    second_report = tmp_path / "report-again.md"
    with cassette(CASSETTE) as loaded:
        code = cli.main(
            [
                "analyze",
                ACCOUNT,
                "--archive",
                ARCHIVE_URL,
                "--max-games",
                str(MAX_GAMES),
                "--depth",
                str(DEPTH),
                "--cache-dir",
                str(run["cache_dir"]),
                "--stockfish-path",
                engine_path,
                "--out",
                str(second_report),
            ]
        )

    assert code == 0
    assert loaded.play_count == 0, (
        "the second run made no HTTP request at all: the archive is on disk from the "
        f"first run, so play_count={loaded.play_count}"
    )
    assert loaded.write_protected, "the second run could not have recorded anything"

    header = summary_of(second_report.read_text(encoding="utf-8"))
    hit_rate = float(header["cache_hit_rate"].rstrip("%"))
    assert hit_rate > 0.0, (
        "the second run hit the evaluation cache for at least one position: "
        f"cache hit rate {header['cache_hit_rate']}"
    )


def test_the_cassette_is_committed_real_and_for_this_account() -> None:
    """The input is real, present and non-empty, and belongs to the account under test.

    The design record (risk 3) makes this the account's published responsibility:
    the e2e test asserts the cassette exists, is non-empty, and carries the
    username it analyses. A cassette silently emptied by a bad merge would
    otherwise make every other test in this file skip or fail for the wrong
    reason.
    """
    path = CASSETTE_DIR / CASSETTE
    assert path.is_file(), f"the recorded cassette {path} is committed"
    assert path.stat().st_size > 0, "the cassette is not empty"

    body = path.read_text(encoding="utf-8")
    assert ARCHIVE_URL in body, "the cassette holds the archive this test replays"
    assert f"/player/{ACCOUNT}/games/archives" in body, "the cassette holds the account's index"


def test_the_cache_directory_holds_real_archive_and_eval_files(run: dict) -> None:
    """Two caches, both real files on disk, both the ones the design record names.

    Deleting either costs time and never correctness, but their absence would mean
    the run reached the network twice and searched every position twice, which is
    the cost the caching exists to remove.
    """
    cache_dir = Path(run["cache_dir"])
    assert cache_dir.is_dir(), f"the run wrote its cache under {cache_dir}"
    archives = list((cache_dir / "archives").glob("*.json"))
    evals = cache_dir / EVAL_CACHE_FILENAME

    assert archives, "the monthly archive was cached as a real JSON file"
    # The archive cache holds the month verbatim, not a summary of it, so the
    # second run over this directory needs no network at all.
    assert '"games"' in archives[0].read_text(encoding="utf-8"), (
        "the cached archive is the raw monthly document"
    )
    # No archives_index directory: this run named the month with --archive, so it
    # never asked for the account's index and never cached one. Asserted as absent
    # rather than skipped, because a run that did enumerate the index would write
    # it here and this test would be measuring a different pipeline.
    assert not (cache_dir / "archives_index").exists(), (
        "a --archive run does not consult or cache the account's archives index"
    )
    assert evals.is_file(), f"the evaluation cache {evals} is a real sqlite file on disk"
    assert evals.stat().st_size > 0, "the evaluation cache holds rows"
