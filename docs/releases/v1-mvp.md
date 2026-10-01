# Release brief: chessleak v1 MVP — "Opening-phase recurring-mistake analyzer"

Status: **APPROVED by the operator on 2026-10-01** ("agree with your proposal") in
response to the chief's release plan for this repository, with one amendment:
agents must not use OpenAI or Anthropic models for this release (see *Team and
models*). Predecessor decision: epic `chess-r0o`, design decisions locked
2026-06-05.

- Release name and tracker release ID: **chessleak v1 MVP**, `chess-r0o`.
- PRD path/revision: `docs/PRD.md`, the operator's epic `chess-r0o` transcribed
  (SHA-256 recorded on the release bead with this brief's).
- Operator decision/source establishing this release: epic `chess-r0o` (2026-06-05);
  chief's plan approved in the operator session, 2026-10-01; model amendment in the
  same message.
- Release branch: `release/v1-mvp`. Base branch: `master`, frozen at `3cd05e8`
  (the bd→br migration commit; the release branch is cut from it).
- Operator availability windows: 2026-10-01, present and answering; later windows
  are recorded on `chess-r0o` as the operator names them. Questions are batched for
  those windows, each with a recommended default.
- Curator of the repository-general Jot scope: the **chief**. Workers share the
  `worker` rough scope, curated by the chief with `jot study --agent worker`.
- Tracker: **br** (Beads Rust), migrated from bd/Dolt on 2026-10-01 (bead history
  and `~/dev-env/beads-archives/chess/README.md`). Never run `bd` here.

## Outcomes

Stable names, so readiness can predict them and evaluators can judge them.

### O1 — One command, one report

*Surfaces: the `chessleak analyze <username>` CLI, its terminal progress output, and
the written markdown report file.*

`chessleak analyze --username <account>` runs the whole pipeline — download and
cache, opening-phase extraction, Stockfish evaluation, severity, book deviation,
clustering, report — and writes a ranked markdown report. Progress and cache hit
rate are visible while it runs. A second run over an unchanged cache does no
network work.

### O2 — Recurring positions, ranked by habit

*Surfaces: the report's ranked cluster sections; the cluster data structure other
units consume.*

The player's moves are keyed by (ECO, exact FEN through the opening phase).
Clusters rank by `occurrences × average win-probability drop`, with a small weight
per book deviation, so a habitual leak outranks a single large blunder in an
unusual position. Each cluster reports occurrences, the player's usual moves with
counts, the engine's best move, average and maximum win% lost, and a deviation
marker when deviations were flagged there.

### O3 — Severity in win-probability terms

*Surfaces: the severity classification consumed by clustering and the report; the
per-move win% figures in the report.*

Centipawn evaluation maps to win probability through a logistic curve
(`Config.win_prob_k`), mate scores map to ±1.0, and each player move is classified
`ok` / `inaccuracy` / `mistake` / `blunder` by its win-probability drop against the
engine's best move in the position before the move, always from the player's point
of view.

### O4 — Book-deviation flags for small habitual leaks

*Surfaces: deviation markers in the report; `DeviationFlag` records consumed by
clustering.*

The first point in each game where the player leaves engine-best (outside
`Config.book_band_cp` of the engine move) is flagged, even when the win-probability
drop is modest, and feeds the cluster's deviation count.

### O5 — Real game history, acquired honestly and cached

*Surfaces: the on-disk archive cache under `Config.cache_dir`; the CLI's
data-provenance summary in the report header.*

The player's complete public game history comes from the chess.com public Published
Data API with **no authentication**, using a descriptive `User-Agent` (chess.com
returns 403 without one). Raw monthly archives are cached on disk keyed by archive
URL, so a re-run makes no HTTP requests. `my_color` is derived by matching the
username case-insensitively.

### O6 — A suite that exercises real composition

*Surfaces: `pytest` collection and the deterministic suite run; the recorded HTTP
cassette under `tests/fixtures/cassettes/`.*

Every module ships unit tests and integration tests that compose real parts: a real
Stockfish process over UCI, real filesystem and real SQLite, and real HTTP recorded
once into a VCR cassette that CI replays deterministically. No mock of the engine,
transport or disk appears in an integration assertion path.

## Size and team

Nine beads, six units, dispatched over four waves. Three concurrent workers while
the host also runs another release's team; Stockfish runs are CPU-bound, so a
worker checks host load before a heavy analysis job. Wall-clock envelope:
roughly one focused working day of build plus evaluation and repair rounds, given
the scaffold lands quickly — this is an estimate, not a commitment, and the
backlog's own dependencies (scaffold → engine/fetch/extract → severity → cluster →
report → CLI) are sequential at the ends.

## Team and models

- Chief: the operator's own session (Pi, `stealth/space-bunny-alpha`, `xhigh`).
- Workers: one fresh Pi session per unit, `stealth/space-bunny-alpha` via
  OpenRouter, `xhigh` effort. **Operator amendment, 2026-10-01: no OpenAI or
  Anthropic model may be used for this release.** The operator is testing this
  model, so evaluator and helper lanes use it too.
- Because the framework's launcher supports Claude Code and Codex only, this
  repository carries a small local launcher, `tools/pi_worker.py`, that assembles
  the same launch context and starts the worker through Herdr's `pi` agent kind.
  The framework package is not modified.

## Taste and explicit constraints

- Python 3.11+, `python-chess`, `httpx` or `requests`, `pytest`, `vcrpy`;
  `ruff` for lint. Standard library otherwise.
- Console entry point `chessleak = src.chessleak.cli:main`.
- Package layout `src/chessleak/`, tests split `tests/unit/` and
  `tests/integration/`.
- **No mocks in integration assertion paths** (the epic's "Prime Directive").
- Opening phase only: first `Config.opening_plies` plies (default 15). No
  whole-game analysis in v1.
- Stockfish is acquired by `scripts/get_stockfish.sh` (release binary or documented
  source build) and its path resolved into `Config.stockfish_path`. No engine
  process may be left running after a test.
- Descriptive `User-Agent` on every chess.com request; requests stay serial and
  polite.
- Nothing authenticates to chess.com, and no account credential is ever needed or
  stored.
- **No Git remote exists** (operator, 2026-10-01). Workers commit and merge
  nothing: they commit on their own branch in their own worktree and report the
  head commit. The chief reviews and merges locally into `release/v1-mvp`. The
  beads' "open a pull request" wording is superseded by this clause.

## Real inputs and journeys

Real input family: one chess.com account's public monthly archives (JSON with
embedded PGN). Data policy: public data, no authentication, no personal data beyond
what the account publishes.

- A worker records a small public account's archive as a VCR cassette under
  `tests/fixtures/cassettes/` on first live run; CI and later runs replay it. The
  live-fetch integration test keeps its real-HTTP path, guarded so it does not
  hammer the service.
- **Open (R4):** the operator has not named the account for the final end-to-end
  validation. Recommended default: the operator names their own account and runs
  `chessleak analyze --username <account>` themselves as the uncoached walkthrough
  (check 3). Until then, readiness predicts O1 conditionally for real-account
  evidence.

Real-journey checks:

1. Before first readiness: layout-faithful replicas — a multi-game PGN fixture at
   realistic size and an archive-shaped JSON fixture — run end to end with real
   Stockfish, measuring wall-clock time and cache reuse.
2. Before first readiness: one real input through the real processing and report,
   in a lane allowed to reach the network (recorded to cassette on first success).
3. Before acceptance: an uncoached walkthrough by the operator, or by a code-blind
   agent, from an empty cache — see the open question above.

## Scope boundaries

In scope: the nine beads of `chess-r0o` and the six outcomes above.

Out of scope for v1: whole-game (beyond-ply-15) analysis, any web or GUI surface,
account authentication, writing to chess.com, opponent-side analysis, a hosted
deployment, and multi-account comparison.

Default allowances: small fixes in code already being changed, covered by tests and
declared at readiness; silent-data-loss fixes in paths this release touches are in
scope. Everything else found is filed as a bead and flagged, not fixed here.

## Interrupt policy

An urgent fix reaches `master` only by the operator's own merge. The chief then
merges `master` into `release/v1-mvp` and tells affected workers. `master` stays
frozen during the build otherwise.

## Release authority

- The **chief** merges into `release/v1-mvp`, only on a unit's own reviewed head
  with its required checks passing. Workers never merge.
- The **operator** merges the accepted release into `master` and creates the
  annotated tag at that merge commit.
- Evaluator acceptance is evidence, never merge or deployment authority.
- Semantic version: **`1.0.0`** (confirm or change — open question).
- No deployment: `chessleak` is a local CLI. "Deployment" for this release is the
  operator running it against their own account.

## Release close

Whoever created a worktree removes it at unit merge, after checking for live
processes, uncommitted work and evidence; anything live defers removal with a named
owner. At release close the chief lists remaining worktrees and branches, removes
the unused, keeps the final round's evidence, and posts a close receipt on
`chess-r0o` listing what was removed, kept or deferred.

## Engineering handoff (recorded on `chess-r0o`, not designed by the operator)

- Tracker/publication owner: the **chief**. State record: `chess-r0o` notes, kept
  current in the shape of `templates/state.md`, plus one round child bead per
  evaluation round.
- Serialized resource: Stockfish CPU is the only contended resource; workers check
  host load and keep at most three concurrent engine-heavy runs.
- Readiness predicts each outcome per surface named above, publishes the
  deterministic suite commands and hashes for the candidate, and lists every change
  beyond the outcomes.
- Evaluation: one incremental lane during the build, then a fresh two-lane
  evaluation on the final candidate, both running `stealth/space-bunny-alpha`.