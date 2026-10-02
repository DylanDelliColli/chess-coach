"""``chessleak analyze <username>``: the whole pipeline behind one command.

Every other module in this release is a stage; this one is the run. It takes a
chess.com account name and produces the ranked markdown report the release exists
to write, and it is the only place the stages are ordered - so it is also the only
place that can get the order wrong, and most of what follows is about not doing
that.

**The order, and why each step is where it is.**

1. :func:`~src.chessleak.fetch.download_all` fetches the account's history into
   ``cache_dir``. It runs first and once, because it is the only step that touches
   the network and the only one whose result the rest of the run can be bounded
   from.
2. Games are filtered to ordinary chess from the standard position. A variant or a
   custom starting position can never recur across the player's games, so each one
   would inject a one-off cluster and take a slot in a frequency ranking it does
   not belong in; each is counted in ``summary.games_skipped`` and the report
   header prints that count, because a game the player cannot see is a game they
   will ask about.
3. :func:`~src.chessleak.pgnio.extract_opening_plies` turns each surviving game's
   PGN into one record per ply of the opening window. It returns ``[]`` for a game
   it could not read - python-chess collects parse failures into ``Game.errors``
   rather than raising, so a corrupt export would otherwise be analysed as a
   shorter game and would silently drop the player's mistake from the middle of
   it. An empty window is a skipped game, counted in the same field.
4. **One** :class:`~src.chessleak.engine.EngineService` is opened for the entire
   run and reused across every game, so the FEN cache is shared: opening positions
   recur across a player's own games, and that recurrence is where the savings are
   (measured on one real month: 4,634 distinct position keys across 4,738 full
   FENs). The engine launches lazily on the first cache miss, so a run whose
   positions are all cached starts no process at all.
5. Each ply is scored with :func:`~src.chessleak.severity.move_severity` from two
   evaluations - the position before the move and the position after it - and
   handed to clustering as a :class:`~src.chessleak.cluster.ScoredMove`. The whole
   window is scored, opponent's plies included, because every position an opponent
   ply needs has already been evaluated by the player's ply before it, so it costs
   no engine time, and because ``is_my_move`` is the flag the rest of the pipeline
   keys on.
6. :func:`~src.chessleak.book.first_deviation` is called **once per game**, with
   that game's window. It walks the window in one pass, so by the time it runs the
   cache already holds every position it asks about.
7. :func:`~src.chessleak.cluster.aggregate` groups the admitted moves into one
   cluster per position, :func:`~src.chessleak.cluster.rank_clusters` orders them,
   and :func:`~src.chessleak.report.render_report` writes them out.

**Three decisions this module owns.**

* **Progress and the cache hit rate are visible while the run happens.** The
  release's outcome O1 asks for both, and a depth-18 run over a full month is
  about twenty-four minutes on this host - long enough that a silent terminal reads
  as a hung one. The progress callback writes to stderr so that ``--out -`` style
  piping and a caller capturing stdout for the report path are unaffected, and a
  caller that wants the lines somewhere else passes its own callable.
* **Exit codes are the design record's: 0 success, 1 runtime failure, 2 usage
  error.** :class:`~src.chessleak.fetch.UnknownAccountError` is the one fetch
  failure that is a *usage* error - chess.com's 404 on the archives index means the
  account name is wrong or the history is private, which is something the operator
  typed, not something that went wrong mid-run.
* **The engine never outlives the run.** One ``with`` block owns it, so a failure
  anywhere in the loop still quits the process - a Stockfish left running holds its
  threads for the rest of the session, and two sessions on ``chess-jc5`` died of
  exactly that.

**One logging decision worth naming.** ``cluster.aggregate`` logs a warning for
every ply that is not the player's move, which is by design: from its point of
view a non-player move in the list means the caller handed over something wrong.
This module hands over the whole window on purpose, so that warning would fire
once per opponent ply per game - around two hundred lines of stderr for a
30-game run, which is the difference between a usable terminal and an unreadable
one. So this logger is raised to ``ERROR`` for the run, and the count it would
have produced is reported by this module's own progress line instead. Nothing is
hidden: the number is printed, just once.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import chess

from .book import first_deviation
from .cluster import BLUNDER, MISTAKE, Cluster, ScoredMove, aggregate, rank_clusters
from .config import Config, position_key
from .engine import EngineService
from .fetch import GameRecord, UnknownAccountError, download_all
from .pgnio import PlyRecord, extract_opening_plies
from .report import render_report
from .severity import move_severity

__all__ = [
    "EXIT_FAILURE",
    "EXIT_OK",
    "EXIT_USAGE",
    "PROGRESS_PREFIX",
    "AnalysisResult",
    "UsageError",
    "analyze",
    "build_parser",
    "config_from_args",
    "main",
]

log = logging.getLogger(__name__)

#: The design record's exit codes.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

#: Every progress line starts with this, so a reader can tell the tool's output
#: from an engine's or a traceback's in a shared terminal.
PROGRESS_PREFIX = "chessleak:"

#: A progress line is a callable taking one already-formatted message.
ProgressFn = Callable[[str], None]

#: The logger whose "not the player's move" warning is contractual here; see the
#: module docstring. Named as a constant so the reason travels with the line that
#: needs it rather than living in a comment far away.
_CLUSTER_LOGGER = "src.chessleak.cluster"

#: The default report filename, with ``{username}`` filled in. Named for the
#: account so analysing a second player does not overwrite the first one's report.
DEFAULT_OUT_TEMPLATE = "chessleak-report-{username}.md"

#: How many games' progress is printed before the counter starts abbreviating.
#: A 153-archive account is thousands of games; a line per game would bury the
#: report it is reporting on.
_ALWAYS = 200


class UsageError(Exception):
    """The command line cannot mean anything: a value the run cannot use.

    Distinct from a runtime failure because the operator can fix it - a mistyped
    account name, a depth that is not a number, a flag that contradicts another.
    :func:`main` turns it into exit code 2 and prints it without a traceback.
    """


# -- the run's result ---------------------------------------------------------


@dataclass(frozen=True)
class AnalysisResult:
    """What one run produced: the ranked clusters, the summary and where it landed.

    Returned rather than printed so a caller - a test, or a future second
    surface - can read the run without parsing the report back off the disk. The
    clusters are the ones ``report.render_report`` was handed, in rank order, so
    the returned data and the written file cannot disagree.
    """

    clusters: tuple[Cluster, ...]
    summary: dict[str, object]
    out_path: Path
    hits: int
    misses: int

    @property
    def cache_hit_rate(self) -> float:
        """``hits / (hits + misses)``, or 0.0 when nothing was analysed."""
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


# -- the pipeline -------------------------------------------------------------


def _stderr_progress(message: str) -> None:
    """The default progress sink: one prefixed line on stderr, flushed.

    stderr rather than stdout so the report's path - the one thing the operator
    might pipe or capture - stays the only thing on stdout, and flushed so a
    twenty-four minute run's progress is visible while it is still going.
    """
    print(f"{PROGRESS_PREFIX} {message}", file=sys.stderr, flush=True)


def _standard_games(games: Sequence[GameRecord]) -> list[GameRecord]:
    """The games whose opening positions can recur: ordinary chess, standard start.

    ``GameRecord.is_standard_chess`` owns the judgment; this only applies it.
    Roughly one game in eight in a real month is a variant or a custom setup, and
    each is counted by the caller in ``summary.games_skipped``.
    """
    return [game for game in games if game.is_standard_chess]


def _best_move_san(fen_before: str, evaluation) -> str | None:
    """The engine's move for a position, in SAN - the currency the report shows.

    ``EvalResult.best_move`` is UCI because the engine speaks UCI, and
    ``Cluster.best_move`` is SAN because a person reads it. The conversion happens
    here, on the board the move was played from, which is the only place in the run
    that has one. ``None`` for a finished position (no move exists) or for a move
    that is not legal here, which would be a corrupt record rather than a finding.
    """
    if evaluation.best_move is None:
        return None
    try:
        move = chess.Move.from_uci(evaluation.best_move)
    except ValueError:
        return None
    board = chess.Board(fen_before)
    if move not in board.legal_moves:
        return None
    return board.san(move)


@dataclass
class _Tally:
    """The run's counters, kept together so one object owns the summary's numbers."""

    games_analyzed: int = 0
    games_skipped: int = 0
    positions: set[str] = dataclasses.field(default_factory=set)
    opponent_plies: int = 0
    flagged: int = 0


def _score_game(
    game: GameRecord,
    plies: list[PlyRecord],
    engine: EngineService,
    config: Config,
    tally: _Tally,
) -> tuple[list[ScoredMove], dict[tuple[str, int], str]]:
    """Score one game's opening window and collect the engine's move for each ply.

    Every position a ply needs - the one before it and the one after - is
    evaluated through the same :class:`EngineService`, so the cache is filled once
    and a position that recurs in a later game is answered from disk. The
    opponent's plies are scored too: they cost no engine time (the position after
    an opponent's move is the position before the player's next one) and
    ``is_my_move`` is what keeps them out of the ranking.

    ``tally.positions`` therefore counts exactly the distinct position keys this
    pass asked the engine about, and only for plies whose two positions are
    actually evaluated: the position after a window's very last move is a place
    the game reached, not a position anything was asked about, and a header that
    counted it would report a number no cache row exists for. It is therefore a
    floor on the run's true position count, by at most one key per window that
    ends on an opponent's move - ``first_deviation`` walks that last ply and asks
    about it. Measured over the 30-game e2e run: 355 counted against 356 engine
    searches, the difference being exactly one such window. Counting on the cold
    run and staying put on the warm one is what makes the figure usable as a
    report header: it does not change because a cache did.
    """
    scored: list[ScoredMove] = []
    best_moves: dict[tuple[str, int], str] = {}

    for ply in plies:
        if not ply.is_my_move:
            tally.opponent_plies += 1
            continue

        tally.positions.add(position_key(ply.fen_before))
        tally.positions.add(position_key(ply.fen_after))

        before = engine.analyse(ply.fen_before)
        after = engine.analyse(ply.fen_after)
        scored.append(
            ScoredMove.from_ply(
                ply, move_severity(before, after, game.my_color, k=config.win_prob_k)
            )
        )
        san = _best_move_san(ply.fen_before, before)
        if san is not None:
            best_moves[(game.id, ply.ply_index)] = san

    return scored, best_moves


def analyze(
    config: Config,
    *,
    out_path: str | Path | None = None,
    progress: ProgressFn | None = None,
) -> AnalysisResult:
    """Run the whole pipeline for ``config.username`` and write the report.

    This is the unit the command line wraps, and it is deliberately callable on
    its own: the integration test drives it through :func:`main`, but a caller that
    wants a report without a terminal (a test, a future surface) can hand over its
    own ``progress`` callable or ``None`` for silence.

    ``config.max_games`` bounds the number of games analysed and keeps the most
    recent ones (``fetch.download_all`` returns newest first). ``config.archives``,
    when non-empty, names the monthly archives to read instead of enumerating the
    account's index. Both are defaults-on: an unconfigured run reads the account's
    whole published history.

    ``config.cache_dir`` is created if absent. The evaluation cache lives inside it
    at ``EVAL_CACHE_FILENAME`` and is keyed by ``(position_key, depth)``, so
    a second run over unchanged inputs answers almost every position from disk and
    starts no engine process at all.

    :raises UsageError: the username is empty, or ``config.top_n`` is negative.
    :raises src.chessleak.fetch.UnknownAccountError: chess.com has no public
        history for that account name.
    """
    username = (config.username or "").strip()
    if not username:
        raise UsageError("a chess.com account name is required")
    if config.top_n < 0:
        raise UsageError(f"--top must be zero or more, got {config.top_n}")

    say = progress or _stderr_progress
    if out_path is None:
        out_path = DEFAULT_OUT_TEMPLATE.format(username=username)
    report_path = Path(out_path).expanduser()

    cache_dir = config.cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. The network, once. Games come back newest first, which is what --max-games
    #    wants to keep.
    say(f"downloading {username}'s game history into {cache_dir}")
    games = download_all(username, cache_dir, archives=config.archives or None)
    say(f"{len(games)} games in the history")

    # 2. Only ordinary chess from the standard position can recur; the rest are
    #    counted, visibly, in the report header.
    standard = _standard_games(games)
    tally = _Tally(games_skipped=len(games) - len(standard))

    # 3. The bound, after the download and before the engine, so a bounded run
    #    never searches a game it will not report on.
    selected = standard[: config.max_games] if config.max_games else standard
    if config.max_games and len(standard) > len(selected):
        say(f"analysing the {len(selected)} most recent of {len(standard)} standard games")
    else:
        say(f"analysing {len(selected)} standard games")

    # 4. One engine for the whole run, so the cache is shared across games. The
    #    with-block owns the process: a failure below still quits it.
    scored: list[ScoredMove] = []
    deviations = []
    best_moves: dict[tuple[str, int], str] = {}

    with (
        _quiet_expected_warnings(),
        EngineService(
            config.stockfish_path, config.analysis_depth, config.evalcache_path
        ) as engine,
    ):
        for number, game in enumerate(selected, start=1):
            plies = extract_opening_plies(game, max_plies=config.opening_plies)
            if not plies:
                # An unreadable PGN, or a game with no opening at all. Counted as
                # skipped so the header accounts for every game the run was given.
                tally.games_skipped += 1
                say(f"  [{number}/{len(selected)}] game {game.id}: no readable opening, skipped")
                continue

            game_scored, game_bests = _score_game(game, plies, engine, config, tally)
            scored.extend(game_scored)
            best_moves.update(game_bests)

            deviation = first_deviation(plies, engine, band_cp=config.book_band_cp)
            if deviation is not None:
                deviations.append(deviation)

            tally.games_analyzed += 1
            say(
                f"  [{number}/{len(selected)}] game {game.id}: {len(plies)} plies"
                f"{', book deviation' if deviation is not None else ''}"
            )
            if number % 25 == 0 and len(selected) > _ALWAYS:
                say(f"  {number}/{len(selected)} games done")

        hits, misses = engine.hits, engine.misses
        if tally.opponent_plies:
            # The count aggregate's warning would have produced, once.
            say(f"{tally.opponent_plies} opponent plies were scored and not aggregated")

    say(
        f"{len(tally.positions)} distinct positions evaluated, "
        f"{hits} cache hits / {misses} searches"
    )

    # 5. Aggregate, rank, render.
    clusters = rank_clusters(aggregate(scored, deviations, best_moves))
    tally.flagged = _flagged_mistakes(scored, deviations)

    summary: dict[str, object] = {
        "username": username,
        "games_analyzed": tally.games_analyzed,
        "games_skipped": tally.games_skipped,
        "positions_evaluated": len(tally.positions),
        "flagged_mistakes": tally.flagged,
        "cache_hit_rate": hits / (hits + misses) if (hits + misses) else 0.0,
    }

    written = render_report(clusters, config.top_n, report_path, summary)
    say(f"{len(clusters)} recurring positions, {tally.flagged} flagged mistakes")
    say(f"wrote {written}")

    return AnalysisResult(
        clusters=tuple(clusters),
        summary=summary,
        out_path=Path(written),
        hits=hits,
        misses=misses,
    )


@contextmanager
def _quiet_expected_warnings() -> Iterator[None]:
    """Stop ``cluster.aggregate`` warning about every opponent ply of every game.

    See the module docstring: this module hands over the whole opening window on
    purpose, so that warning is contractual rather than a defect signal, and at
    one line per ply it buries the rest of the output. The number it stands for is
    printed by :func:`analyze` instead, so nothing is lost - only repeated.

    A context manager, because the level is restored on the way out: a library
    caller that runs :func:`analyze` and then aggregates its own clusters has not
    asked to have that module's logger silenced for the rest of its process.
    """
    logger = logging.getLogger(_CLUSTER_LOGGER)
    previous = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(previous)


def _flagged_mistakes(scored: Sequence[ScoredMove], deviations: Sequence) -> int:
    """Admitted moves that are a real mistake: the design record's one definition.

    ``flagged_mistakes`` is "admitted moves whose class is ``mistake`` or
    ``blunder``, or that carry a deviation". Admitted means the same thing
    ``cluster.aggregate`` means - the class is not ``ok``, or a flag exists at that
    ``(game_id, ply_index)`` - so the header's count and the clusters in the body
    are counting the same moves.

    Computed from the run's own scored moves and flags rather than from the
    clusters, because a cluster carries only its ``worst_klass``: one cluster of six
    admitted moves with a single blunder is one cluster but two flagged moves, and
    counting clusters would understate the player's errors by the number of
    clusters.
    """
    flagged_at = {(flag.game_id, flag.ply_index) for flag in deviations}
    total = 0
    for move in scored:
        if not move.is_my_move:
            continue
        key = (move.game_id, move.ply_index)
        if move.severity.klass in (MISTAKE, BLUNDER) or key in flagged_at:
            total += 1
    return total


# -- the command line ---------------------------------------------------------


def _positive_int(text: str) -> int:
    """An integer of at least 1, or a usage error naming the flag's own value."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected 1 or more, got {value}")
    return value


def _non_negative_int(text: str) -> int:
    """An integer of at least 0, or a usage error."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected zero or more, got {value}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for ``chessleak``.

    One subcommand, ``analyze``. Every flag defaults to ``None`` rather than to a
    value, because ``None`` is what "the operator did not say this" looks like:
    :func:`config_from_args` then starts from ``Config.from_env()`` and replaces
    only the fields a flag named, so an environment variable supplies what a flag
    omits and a flag overrides what the environment set.
    """
    parser = argparse.ArgumentParser(
        prog="chessleak",
        description=("Surface a chess.com player's most consequential recurring opening mistakes."),
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    analyze_parser = commands.add_parser(
        "analyze",
        help="analyse a player's openings and write a ranked markdown report",
        description=(
            "Download a chess.com account's games, evaluate the first "
            "Config.opening_plies plies of each with Stockfish, cluster the player's "
            "worst recurring moves by position and write a ranked markdown report."
        ),
    )
    analyze_parser.add_argument(
        "username",
        nargs="?",
        default=None,
        help="the chess.com account to analyse (the PRD's canonical form)",
    )
    analyze_parser.add_argument(
        "--username",
        dest="username_option",
        default=None,
        metavar="ACCOUNT",
        help="the same account, as a flag; an alias of the positional argument",
    )
    analyze_parser.add_argument(
        "--depth",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Stockfish search depth (default 18; 12 analyses a bounded run in minutes)",
    )
    analyze_parser.add_argument(
        "--plies",
        type=_positive_int,
        default=None,
        metavar="N",
        help="how many plies of each game count as the opening (default 15)",
    )
    analyze_parser.add_argument(
        "--top",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="how many ranked positions the report shows (default 20)",
    )
    analyze_parser.add_argument(
        "--out",
        dest="out_path",
        default=None,
        metavar="PATH",
        help=f"where to write the report (default {DEFAULT_OUT_TEMPLATE})",
    )
    analyze_parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        default=None,
        metavar="DIR",
        help="where archives and evaluations are cached (default ~/.cache/chessleak)",
    )
    analyze_parser.add_argument(
        "--stockfish-path",
        dest="stockfish_path",
        default=None,
        metavar="PATH",
        help="the Stockfish binary to search with (default: the one get_stockfish.sh installs)",
    )
    analyze_parser.add_argument(
        "--max-games",
        dest="max_games",
        type=_positive_int,
        default=None,
        metavar="N",
        help="analyse only the N most recent games (default: the whole history)",
    )
    analyze_parser.add_argument(
        "--archive",
        dest="archives",
        action="append",
        default=None,
        metavar="URL",
        help=(
            "read only this monthly archive URL; repeatable. Default: every month the "
            "account has published."
        ),
    )
    return parser


def config_from_args(args: argparse.Namespace) -> tuple[Config, Path | None]:
    """The ``Config`` and the report path a parsed ``analyze`` line means.

    Starts from ``Config.from_env()`` so the ``CHESSLEAK_*`` table is honoured,
    and replaces only what a flag named. ``--cache-dir`` is expanded here, at the
    edge, so a flag-supplied path behaves exactly like an environment-supplied one.

    The username is the positional argument the PRD froze, with ``--username`` as
    its alias. Naming the same account twice is fine; naming two *different* ones
    is a usage error rather than a silent winner, because which one the operator
    meant decides whose games get downloaded.

    :raises UsageError: two different usernames, or none.
    """
    positional = getattr(args, "username", None)
    option = getattr(args, "username_option", None)
    if positional and option and positional.strip() != option.strip():
        raise UsageError(
            f"two different account names: {positional.strip()!r} and {option.strip()!r}"
        )
    username = (positional or option or "").strip()
    if not username:
        raise UsageError(
            "an account name is required: `chessleak analyze <username>`, or `--username <account>`"
        )

    config = Config.from_env()
    overrides: dict[str, object] = {"username": username}
    for flag, field in (
        ("depth", "analysis_depth"),
        ("plies", "opening_plies"),
        ("top", "top_n"),
        ("cache_dir", "cache_dir"),
        ("stockfish_path", "stockfish_path"),
        ("max_games", "max_games"),
    ):
        value = getattr(args, flag, None)
        if value is not None:
            overrides[field] = str(Path(value).expanduser()) if field == "cache_dir" else value

    archives = getattr(args, "archives", None)
    if archives:
        overrides["archives"] = tuple(str(url) for url in archives)

    config = replace(config, **overrides)

    out_path = getattr(args, "out_path", None)
    if out_path is None:
        return config, Path(DEFAULT_OUT_TEMPLATE.format(username=username))
    return config, Path(out_path).expanduser()


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``chessleak`` and return its exit code. The console entry point.

    ``argv`` defaults to ``sys.argv[1:]``. The return value is the process exit
    status, which is what a console script wrapper passes to ``sys.exit``, so
    ``chessleak analyze`` in a script is distinguishable from a crash.

    Returns 0 on success, 2 for anything the command line got wrong (including
    argparse's own errors, which exit 2 by argparse's convention) and 1 for a
    failure during the run. A usage error and a runtime failure print a one-line
    message; a runtime failure prints the reason and no traceback, because the
    operator's next question is what happened, not where in our frames it did.
    """
    parser = build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exit_request:
        # argparse exits for --help (0), an unknown flag and a bad value (2). Its
        # own convention is already the design record's, so its status is passed
        # through rather than re-invented here: main() returns an int, and the
        # console script wrapper turns that into the process's status.
        return int(exit_request.code or 0)

    if getattr(args, "command", None) != "analyze":
        parser.print_usage(sys.stderr)
        print(
            f"{PROGRESS_PREFIX} nothing to do: try `chessleak analyze <username>`",
            file=sys.stderr,
        )
        return EXIT_USAGE

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        config, out_path = config_from_args(args)
        result = analyze(config, out_path=out_path)
    except UsageError as error:
        print(f"{PROGRESS_PREFIX} {error}", file=sys.stderr)
        return EXIT_USAGE
    except UnknownAccountError as error:
        print(
            f"{PROGRESS_PREFIX} chess.com has no public game history for "
            f"{config.username!r}: {error}",
            file=sys.stderr,
        )
        return EXIT_USAGE
    except KeyboardInterrupt:
        print(f"{PROGRESS_PREFIX} interrupted", file=sys.stderr)
        return EXIT_FAILURE
    except Exception as error:  # the run failed; the operator needs the reason, not our frames
        print(f"{PROGRESS_PREFIX} {type(error).__name__}: {error}", file=sys.stderr)
        log.debug("the failing run", exc_info=True)
        return EXIT_FAILURE

    print(f"{PROGRESS_PREFIX} wrote {os.fspath(result.out_path)}", file=sys.stdout, flush=True)
    return EXIT_OK
