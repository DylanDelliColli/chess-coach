"""Flag parsing and the run's exit codes: ``chessleak analyze`` as a command.

``cli.py`` is the release's seam - the one module every other unit's output passes
through on its way to a person - so what is under test here is the surface the
operator actually types: which flags exist, what they turn into, and what the
command returns when something is wrong.

**What this file does *not* do.** It never fetches, never searches and never
writes a report. :func:`record_analyze` replaces ``cli.analyze`` with a recorder,
so these tests check the wiring around the pipeline and leave the pipeline itself
to ``tests/integration/test_cli_e2e.py``, which runs it for real against a
recorded cassette and a real Stockfish. A unit test that mocked the engine here
would prove nothing the integration file does not.

**Defaults come from ``Config.from_env()``, not from ``Config()``.** The design
record freezes both: ``Config()`` keeps the documented literal defaults, while
``from_env`` reads the ``CHESSLEAK_*`` table and expands ``~``. A command line
should honour the environment and let explicit flags override it, so the CLI
starts from ``from_env()`` and replaces only the fields a flag names. With the
environment cleared (which :func:`no_chessleak_env` does for every test here) the
two agree on the documented defaults, so a test can assert them either way.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.chessleak import cli
from src.chessleak.cluster import Cluster
from src.chessleak.config import (
    DEFAULT_ANALYSIS_DEPTH,
    DEFAULT_BOOK_BAND_CP,
    DEFAULT_CACHE_DIR,
    DEFAULT_OPENING_PLIES,
    DEFAULT_TOP_N,
    DEFAULT_WIN_PROB_K,
    Config,
)
from src.chessleak.fetch import UnknownAccountError

pytestmark = pytest.mark.unit

#: Every ``CHESSLEAK_*`` variable ``Config.from_env`` reads. Cleared for each test
#: so an operator's own shell cannot make a flag-parsing test assert something
#: about this host.
ENV_VARS = (
    "CHESSLEAK_USERNAME",
    "CHESSLEAK_STOCKFISH_PATH",
    "CHESSLEAK_STOCKFISH_ROOT",
    "CHESSLEAK_ANALYSIS_DEPTH",
    "CHESSLEAK_DEPTH",
    "CHESSLEAK_OPENING_PLIES",
    "CHESSLEAK_CACHE_DIR",
    "CHESSLEAK_WIN_PROB_K",
    "CHESSLEAK_BOOK_BAND_CP",
    "CHESSLEAK_TOP_N",
)


@pytest.fixture(autouse=True)
def no_chessleak_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``CHESSLEAK_*`` variable set, so the documented defaults are what is asserted."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# -- the flag surface ---------------------------------------------------------


def test_arg_parsing() -> None:
    """The bead's named test: the flags become a ``Config`` of the right types.

    Every flag is set at once, so a flag that is silently dropped, aliased to the
    wrong field or parsed as a string fails here rather than three units later.
    The values are deliberately of different types - ints, floats, paths, a
    repeated list - because "it parsed" and "it parsed into the right type" are
    different claims and this is the only place the second one can be checked.
    """
    argv = [
        "analyze",
        "--username",
        "bobbyfischer",
        "--depth",
        "12",
        "--plies",
        "11",
        "--top",
        "5",
        "--out",
        "/tmp/report.md",
        "--cache-dir",
        "/tmp/chessleak-cache",
        "--stockfish-path",
        "/opt/stockfish",
        "--max-games",
        "30",
        "--archive",
        "https://api.chess.com/pub/player/bobbyfischer/games/2023/11",
    ]

    args = cli.build_parser().parse_args(argv)
    config, out_path = cli.config_from_args(args)

    # Types, not just values: the pipeline hands these to argparse-free consumers
    # (EngineService wants an int depth, render_report wants an int top_n) and a
    # string there fails deep inside somebody else's module.
    assert isinstance(config.analysis_depth, int) and config.analysis_depth == 12
    assert isinstance(config.opening_plies, int) and config.opening_plies == 11
    assert isinstance(config.top_n, int) and config.top_n == 5
    assert isinstance(config.win_prob_k, float) and config.win_prob_k == DEFAULT_WIN_PROB_K
    assert isinstance(config.book_band_cp, int) and config.book_band_cp == DEFAULT_BOOK_BAND_CP

    assert config.username == "bobbyfischer"
    assert config.cache_dir == "/tmp/chessleak-cache"
    assert config.stockfish_path == "/opt/stockfish"

    # The two surfaces the design record added beyond the bead's flag list.
    assert config.max_games == 30
    assert config.archives == ("https://api.chess.com/pub/player/bobbyfischer/games/2023/11",)

    assert out_path == Path("/tmp/report.md")


def test_defaults_are_the_design_records_defaults(tmp_path: Path, monkeypatch) -> None:
    """No flags at all yields the frozen defaults, with only the username supplied.

    ``--depth 12`` is what the e2e test passes to stay inside its budget; this
    asserts that the *product's* default is still depth 18, so the test's bounding
    is visible in the test rather than invisible in the release.
    """
    monkeypatch.chdir(tmp_path)
    args = cli.build_parser().parse_args(["analyze", "someone"])
    config, out_path = cli.config_from_args(args)

    assert config.username == "someone"
    assert config.analysis_depth == DEFAULT_ANALYSIS_DEPTH == 18
    assert config.opening_plies == DEFAULT_OPENING_PLIES == 15
    assert config.top_n == DEFAULT_TOP_N == 20
    # Config() keeps the documented literal "~/.cache/chessleak" so the default
    # reads the same in a signature as in a help string; from_env() - which the
    # CLI builds on, so the CHESSLEAK_* table is honoured - expands it. What the
    # run reaches is the expanded path, and that is what this asserts.
    assert config.cache_dir == str(Path(DEFAULT_CACHE_DIR).expanduser())
    assert config.cache_path.is_absolute()
    assert config.max_games is None, "the default is unlimited, not a bound"
    assert config.archives == (), "the default is the account's whole history"
    # The report goes next to the operator by default, named for the account, so
    # two accounts do not overwrite each other's report.
    assert out_path == Path("chessleak-report-someone.md")


def test_positional_username_is_canonical_and_the_flag_is_an_alias() -> None:
    """The PRD's ``analyze <username>`` and the bead's ``--username`` agree."""
    positional = cli.build_parser().parse_args(["analyze", "bobbyfischer"])
    assert cli.config_from_args(positional)[0].username == "bobbyfischer"

    alias = cli.build_parser().parse_args(["analyze", "--username", "bobbyfischer"])
    assert cli.config_from_args(alias)[0].username == "bobbyfischer"


def test_cache_dir_is_expanded_like_every_other_path(tmp_path: Path) -> None:
    """``--cache-dir ~/x`` reaches the disk as ``~/x``, not as a literal tilde.

    ``Config()`` keeps the literal ``~`` so the documented default reads the same
    in a signature as in a help string, and expands it in ``from_env`` and in
    ``cache_path``. The CLI expands it at the edge, so a value that came from a
    flag and a value that came from the environment behave identically.
    """
    args = cli.build_parser().parse_args(["analyze", "someone", "--cache-dir", "~/somewhere"])
    config, _ = cli.config_from_args(args)
    assert config.cache_dir == str(Path.home() / "somewhere")
    assert "~" not in config.cache_dir


# -- usage errors (exit 2) ---------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["analyze"], id="no-username"),
        pytest.param(["analyze", "a", "--username", "b"], id="two-different-usernames"),
        pytest.param(["analyze", "a", "--depth", "twelve"], id="non-numeric-depth"),
        pytest.param(["analyze", "a", "--plies", "0"], id="zero-plies"),
        pytest.param(["analyze", "a", "--top", "-1"], id="negative-top"),
        pytest.param(["analyze", "a", "--max-games", "0"], id="zero-max-games"),
    ],
)
def test_usage_errors_are_exit_two(argv: list[str], capsys: pytest.CaptureFixture) -> None:
    """A command that cannot mean anything is a usage error, not a crash.

    Exit code 2 is the design record's, and it is what lets a caller tell "you
    typed it wrong" from "the run failed" (1) without reading the message.
    """
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.strip(), "a usage error says what was wrong"


def test_no_subcommand_is_a_usage_error(capsys: pytest.CaptureFixture) -> None:
    """``chessleak`` alone prints help and exits 2; it does not analyse nobody."""
    assert cli.main([]) == 2
    assert "analyze" in capsys.readouterr().err


def test_help_exits_zero(capsys: pytest.CaptureFixture) -> None:
    """Asking for help is not a mistake."""
    assert cli.main(["--help"]) == 0
    assert "analyze" in capsys.readouterr().out


# -- the run (pipeline replaced by a recorder) -------------------------------


class _Recorded:
    """What :func:`record_analyze` captured: the ``Config`` and the output path."""

    def __init__(self) -> None:
        self.calls: list[tuple[Config, Path]] = []

    @property
    def last(self) -> tuple[Config, Path]:
        assert len(self.calls) == 1, f"expected exactly one analyze call, got {len(self.calls)}"
        return self.calls[0]


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> _Recorded:
    """Replace ``cli.analyze`` with a recorder, so no fetch or search happens here."""

    def _fake(config: Config, *, out_path: Path, progress=None) -> cli.AnalysisResult:
        rec.calls.append((config, Path(out_path)))
        return cli.AnalysisResult(
            clusters=(),
            summary={"username": config.username},
            out_path=Path(out_path),
            hits=0,
            misses=0,
        )

    rec = _Recorded()
    monkeypatch.setattr(cli, "analyze", _fake)
    return rec


def test_main_passes_the_parsed_config_and_output_path(recorded: _Recorded, tmp_path: Path) -> None:
    """The wiring the bead names: argv in, one ``analyze`` call, exit 0."""
    out = tmp_path / "report.md"
    code = cli.main(
        ["analyze", "bobbyfischer", "--depth", "12", "--max-games", "30", "--out", str(out)]
    )

    assert code == 0
    config, out_path = recorded.last
    assert (config.username, config.analysis_depth, config.max_games) == ("bobbyfischer", 12, 30)
    assert out_path == out


def test_main_reports_the_report_it_wrote(
    recorded: _Recorded, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Outcome O1 is "one command, one report", so the path is on stdout at the end."""
    out = tmp_path / "report.md"
    assert cli.main(["analyze", "bobbyfischer", "--out", str(out)]) == 0
    assert str(out) in capsys.readouterr().out


def test_an_unknown_account_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """chess.com's 404 on the archives index means the name is wrong: exit 2.

    ``fetch.py`` raises :class:`UnknownAccountError` for exactly that case and
    documents that ``cli.py`` maps it to a usage error - the operator mistyped an
    account name, which is not a runtime failure of the run.
    """

    def _boom(config: Config, *, out_path: Path, progress=None) -> cli.AnalysisResult:
        raise UnknownAccountError(config.username, "https://api.chess.com/pub/player/x/games")

    monkeypatch.setattr(cli, "analyze", _boom)
    assert cli.main(["analyze", "no-such-account-9f3a"]) == 2
    assert "no-such-account-9f3a" in capsys.readouterr().err


def test_a_runtime_failure_is_exit_one(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Anything else that goes wrong mid-run is a failure of the run, not of the command line."""

    def _boom(config: Config, *, out_path: Path, progress=None) -> cli.AnalysisResult:
        raise RuntimeError("stockfish exited unexpectedly")

    monkeypatch.setattr(cli, "analyze", _boom)
    assert cli.main(["analyze", "bobbyfischer"]) == 1
    err = capsys.readouterr().err
    assert "stockfish exited unexpectedly" in err
    assert "Traceback" not in err, "a failed run prints the reason, not a stack trace"


# -- the result type ----------------------------------------------------------


def test_analysis_result_carries_what_the_report_needs(tmp_path: Path) -> None:
    """``AnalysisResult`` is the pipeline's own return value, so its shape is ours.

    A test cannot pass by asserting on a stand-in: the cluster is the real
    ``chessleak.cluster.Cluster`` with a real ``collections.Counter``, which is
    the same discipline ``test_report.py`` uses for the report seam.
    """
    from collections import Counter

    cluster = Cluster(
        eco="C60",
        fen_before=chess_start_fen(),
        occurrences=2,
        my_moves=Counter({"Nf3": 2}),
        best_move="Bc4",
        avg_winprob_drop=0.1,
        max_winprob_drop=0.2,
        deviation_count=1,
        worst_klass="mistake",
        composite_score=0.31,
    )
    result = cli.AnalysisResult(
        clusters=(cluster,),
        summary={"username": "bobbyfischer"},
        out_path=tmp_path / "report.md",
        hits=3,
        misses=1,
    )

    assert result.clusters[0] is cluster
    assert result.out_path == tmp_path / "report.md"
    assert result.cache_hit_rate == 0.75
    assert isinstance(result.clusters, tuple), "the result is immutable"


def chess_start_fen() -> str:
    """The standard position, read from python-chess rather than written out."""
    import chess

    return chess.STARTING_FEN


def test_cache_dir_of_a_run_is_the_one_the_operator_asked_for(
    recorded: _Recorded, tmp_path: Path
) -> None:
    """The cache is per-run state on disk, so its flag reaches the config verbatim."""
    cache = tmp_path / "cache"
    cli.main(["analyze", "bobbyfischer", "--cache-dir", str(cache)])
    config, _ = recorded.last
    assert Path(config.cache_dir) == cache


def test_stockfish_path_flag_reaches_the_config(recorded: _Recorded, tmp_path: Path) -> None:
    """A stockfish the operator names is used verbatim, not resolved again."""
    binary = tmp_path / "stockfish"
    binary.write_text("#!/bin/sh\n")
    cli.main(["analyze", "bobbyfischer", "--stockfish-path", str(binary)])
    config, _ = recorded.last
    assert config.stockfish_path == str(binary)


def test_the_module_has_a_console_entry_point_shape() -> None:
    """``pyproject`` freezes ``chessleak = src.chessleak.cli:main``, so main must exist.

    Guarded rather than trusted: the entry point is the only way a user reaches
    any of this, and a rename would break every install on the host while every
    other test still passed.
    """
    assert callable(cli.main)
    assert cli.main.__module__ == "src.chessleak.cli"


def test_repeated_archive_flag_accumulates() -> None:
    """``--archive`` is repeatable, so a bounded run can name several months."""
    args = cli.build_parser().parse_args(
        ["analyze", "bobbyfischer", "--archive", "https://x/1", "--archive", "https://x/2"]
    )
    config, _ = cli.config_from_args(args)
    assert config.archives == ("https://x/1", "https://x/2")


def test_environment_supplies_what_no_flag_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """A flag overrides the environment; the environment fills in what a flag omits.

    This is the layering the design record's ``CHESSLEAK_*`` table implies, and it
    is the reason the CLI builds on ``Config.from_env()``: an operator who sets
    ``CHESSLEAK_CACHE_DIR`` once should not have to repeat it on every command.
    """
    monkeypatch.setenv("CHESSLEAK_CACHE_DIR", "/from/env")
    monkeypatch.setenv("CHESSLEAK_TOP_N", "3")

    args = cli.build_parser().parse_args(["analyze", "bobbyfischer"])
    config, _ = cli.config_from_args(args)
    assert config.cache_dir == "/from/env"
    assert config.top_n == 3

    args = cli.build_parser().parse_args(["analyze", "bobbyfischer", "--cache-dir", "/from/flag"])
    config, _ = cli.config_from_args(args)
    assert config.cache_dir == "/from/flag", "the flag wins over the environment"


def test_paths_are_absolute_or_relative_as_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ``~`` is expanded; a relative ``--cache-dir`` stays relative to the cwd.

    Resolving to an absolute path here would silently change what a later
    ``--out report.md`` means if the two were resolved against different roots,
    and the operator can always write an absolute path themselves.
    """
    monkeypatch.chdir(Path(os.sep) / "tmp")
    args = cli.build_parser().parse_args(["analyze", "x", "--cache-dir", "relative/cache"])
    config, _ = cli.config_from_args(args)
    assert config.cache_dir == "relative/cache"
