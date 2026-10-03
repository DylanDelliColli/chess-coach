# Evaluation report — chessleak v1 MVP, candidate `2ae9820`

Evaluator: `eval-046b7b4af52e` (Herdr `ao-ff0ffcff-eval-046b7b4af52e`, pane `w3:pQ`).
Independent lane; no builder context, no product source beyond the three operator
documents named below. Lane 2 of two for this round (the round record names
`eval-2c628636e64b`; Herdr shows no session for it, so I ran without contact from
that lane).

## Release evaluation

- **Release / release bead:** chessleak v1 MVP, `chess-r0o`; round child bead
  `chess-8el` (round 1).
- **Candidate commit and verification checkout:**
  `2ae982042129f553a1d61cf1d5281d3ddef0eee6`, `release/v1-mvp` (identical to
  `origin/release/v1-mvp`). Checkout: `~/.cache/chessleak/eval-2ae9820`, detached
  at the candidate, `git status` clean at teardown. Untracked additions were only
  this lane's `.venv/` (my own build). The checkout is the one the run-information
  record names, prepared by the chief, so I did not remove it; my own runtime was
  disposable and is accounted for below.
- **Base commit for regression comparison:** `master` at `3cd05e8` (bd→br
  migration), confirmed still frozen at `3cd05e8` and `origin/master` at
  `3cd05e8`. The base carries no `chessleak` product code, so every behaviour in
  this release is new; regression comparison is limited to the release branch's
  own history.
- **Product source paths and SHA-256 (all verified at evaluation start and
  unchanged at end):** PRD `/home/ddc/dev-env/chess/docs/PRD.md`
  `b7c30597…b8c09`; release brief `docs/releases/v1-mvp.md` `407cc903…da42d3c`;
  design record `docs/releases/v1-mvp-design.md` `82d34344…1eec1b4d`. All three
  match the launch context and the chief's correction comment (67). `docs/PRD.md`
  and the brief carry operator rulings of 2026-10-02; the design record is
  engineering, not authority.
- **Evaluator client / model / effort and times:** Pi, OpenRouter
  `stealth/space-bunny-alpha`, `xhigh` (as requested in the launch context and as
  the operator's 2026-10-01 model directive requires). Evaluation window
  2026-10-02 16:17–17:20 UTC.
- **Setup, runtime/data and commands:**
  - `bash scripts/setup_env.sh` → own `.venv` in the checkout, Stockfish 19 at
    `~/.local/share/chessleak/stockfish/stockfish` (shared, read-only).
  - `.venv/bin/python -m pytest -q` → `298 passed in 170.52s`
    (published artifact: 298 passed in 174.8s — reproduces).
  - `.venv/bin/python -m ruff check .` → `All checks passed!`;
    `ruff format --check .` → `41 files already formatted` (both reproduce).
  - Reproduced e2e artifact: `chessleak analyze bobbyfischer --archive 2023/11
    --max-games 30 --depth 12 --out report.md` on a warm cache →
    `report.md` sha256 `105bfd553579e84aa700c88b15214e9b919435cae32ce8f3a906a46b8129ba6e`,
    **identical to the published artifact**. Note: this hash is only reproducible
    from a *warm* cache, because the header prints the run's cache hit rate; a
    cold run of the same command differs from the published artifact in that one
    line alone (`58.4%` instead of `100.0%`), everything else byte-identical.
  - Real journeys I ran, all with real Stockfish and a real filesystem:
    `kijuu11` (the PRD's R4 validation account, the operator's own) from an empty
    cache: whole published history downloaded live (38 monthly archives), then
    `--max-games 60 --depth 12`; `bobbyfischer` 2023/11 in full (85 games,
    depth 12); `kijuu11` warm re-runs with the network black-holed; a
    same-command-twice reproducibility pair; a 60-game vs 40-game pair; and a
    synthetic-FEN probe archive. Runtime, caches and reports under
    `~/.cache/chessleak/eval-scratch/` (disposable, outside the checkout).
  - Resource note: the round record names no serialized-resource slot bead and no
    slot contact, so there was nothing to claim. I checked `herdr agent list`
    (only this lane live in the chess workspace; chief idle/done), `pgrep
    stockfish` (none running) and host load (0.36–1.5 on 24 threads) before
    starting, and ran at most two engine-heavy runs at once. No slot was taken,
    because none exists to take; the missing Stockfish slot record is itself
    reported below.
- **Canonical run-information record:** `chess-8el` comment 1 (chief, keeper,
  2026-10-02 16:16 UTC), unchanged during my evaluation; the readiness declaration
  is `chess-r0o` comment 68. Both read at start; no new operator comment appeared
  during the round.

## Outcome evidence

| Outcome / consumer surface | Team prediction / confidence | Observed | Evidence / limitations |
|---|---|---|---|
| **O1** — CLI `chessleak analyze <username>` | PASS, high | **pass** | Live run from an empty cache: `kijuu11`, 38 archives downloaded, 60 games analysed, report written. Progress lines on stderr throughout, report path printed once on stdout, exit 0. |
| **O1** — terminal progress output | PASS, high | **pass** | Per-game lines `[n/60] game …: 15 plies, book deviation`, plus the summary lines and the cache-hit-rate line; visible while running. |
| **O1** — written markdown report file | PASS, high | **pass** | Report written to the given `--out`; published artifact hash reproduced exactly; report re-parsed independently (see O2). |
| **O1** — second run over unchanged cache does no network work | PASS, high | **pass** | Warm re-run with `HTTP(S)_PROXY` pointed at a dead port completed in 0.48 s with `1404 cache hits / 0 searches` and no engine process started at all. |
| **O2** — ranked cluster sections (report) | PASS, low on the *demonstration* of ordering | **pass** (behaviour), content at risk from F1 | `kijuu11` 60 games → 6 habits ordered 29, 10, 3, 3, 2, 2 occurrences, ties broken by descending composite (0.32 > 0.27; 0.22 > 0.18); `bobbyfischer` 85 games → 10 habits (4, 3, 3, 2×7). Readiness's "under-demonstrated" concern is now demonstrated on the operator's own account. |
| **O2** — ordering/withheld invariants | PASS | **pass** | Independent parser + independent re-derivation (`o2_invariants.py`): every body entry `occurrences ≥ 2`, occurrences non-increasing, ties ordered by descending cost, header withheld count equals the run's `one_off_positions_omitted` (61), lower-bound sentence present, body entry count equals `min(habits, top_n)`. |
| **O2** — `top_n` truncates the habit list | PASS | **pass** | `--top 3` on the same run → "Showing the top 3 of 6 habits", three entries, not padded. (`--top 0` is F2.) |
| **O2** — header states the withheld count and the lower bound | PASS | **pass** | Both sentences unconditional, printed in every report I produced (including the zero-habit one). |
| **O3** — centipawn bands | PASS, high | **pass** | Band edges exercised through the shipped classifier: 49→ok, 50→inaccuracy, 99→inaccuracy, 100→mistake, 199→mistake, 200→blunder. On 449 real player moves (`kijuu11`, 60 games) every class agreed with `classify_cp_loss`. |
| **O3** — win% is display, not classifier | PASS, high | **pass** | Same 449 moves re-scored at `win_prob_k` 0.004 and 0.02: identical class mix (ok 387 / inaccuracy 34 / mistake 18 / blunder 10) while displayed drops moved (e.g. 3.6% → 14.2%). |
| **O3** — mate scores map to ±1.0, player's POV | PASS, high | **fail** (F1) | A move that *delivers* mate inside the opening window is classified `blunder` with `winprob_drop = 1.000`, i.e. the report says the player lost the whole win probability while the report's own line shows the move was the engine's best. Reproduction, expectation and consequence under Findings. |
| **O4** — deviation markers in the report | PASS, moderate | **pass** | Real run: 5 of 6 habits carry the marker with an accurate count (29 of 29, 10 of 10, 3 of 3, 1 of 2), including a habit whose worst class is `ok` — the habitual small leak the trigger exists for. |
| **O4** — `DeviationFlag` feeds the cluster count | PASS | **pass** (code + observed) | `first_deviation` is called once per game with that game's window; `aggregate` counts a flag at its `(game_id, ply_index)`. I did not re-derive a known-ply flag independently of the team's integration test; marked as evidence-by-code plus observed report output. |
| **O5** — on-disk archive cache under `Config.cache_dir` | PASS, high | **pass** | From an empty cache: `archives_index/<slug>-<hash>.json` (username-keyed, case-folded), `archives/<slug>-<hash>.json` per monthly URL, `evalcache.sqlite`; 7.6 MB for 38 archives. A case-variant username (`KIJUU11`) reused the same single index-cache file. |
| **O5** — no authentication, descriptive UA | PASS, high | **pass** | No credential anywhere; the tool's UA is recorded in both committed cassettes and chess.com answered 200 live (it answers 403 without a descriptive UA). Requests serial, 0.5 s apart. |
| **O5** — re-run makes no HTTP requests | PASS, high | **pass** | Same black-holed-proxy warm run as O1. |
| **O5** — `my_color` matched case-insensitively | PASS, high | **pass** | `KIJUU11` run analysed the same games as `kijuu11`; single index cache entry. |
| **O5** — data-provenance summary in the header | PASS | **pass** | Header shows games analyzed, games skipped, positions evaluated, flagged mistakes, cache hit rate, one-offs omitted; `kijuu11` run counted 5 non-standard games skipped. |
| **O6** — deterministic suite run | PASS, high | **pass** | `298 passed in 170.52s` on this candidate, reproducing the published artifact. |
| **O6** — no mock of engine/transport/disk in an integration assertion path | PASS, high | **pass** | `tests/integration/` contains no `mock`, `monkeypatch`, `patch` or stub; the only occurrences of the word are docstrings saying so. Stockfish processes were observed running during the suite, and `pgrep stockfish` was empty afterwards, as the brief requires. |
| **O6** — every module has unit and integration tests | PASS | **pass** | Each of the eight product modules is exercised from both suites (`config` is imported and asserted through six integration files). |
| Release constraint — opening phase only (first 15 plies) | (not separately predicted) | **pass** | After a real 60-game run, 0 of 594 cached positions lie outside the first 15 plies of those games, while the same games reach 3,251 positions after ply 15. |
| Real-journey check 2 — one real input through the real processing and report | done for the cassette account | **pass, agent-side** | `kijuu11` (PRD R4 validation account) live, from an empty cache, real Stockfish, real report. Cache and report left untracked and deleted at teardown per the brief's data policy. |
| Real-journey check 3 — uncoached walkthrough from an empty state | outstanding; operator's to perform | **unverified** | I performed the closest agent-side equivalent (one command, empty cache, live network) and it worked, but an *uncoached* walkthrough is the operator's evidence and cannot be substituted. |
| Version `0.1.0` (operator, 2026-10-02) | (declared change) | **pass** | `pyproject.toml` and `src/chessleak/__init__.py` agree; `tests/unit/test_version.py` pins them. |

## Scope questions

| Requirement / finding | Follow-up owner | Operator ruling and source, or UNRESOLVED | Effect on prediction and assessment |
|---|---|---|---|
| Positional similarity (`chess-sco`) deferred: a habit reached by transposition/mirror counts as one-offs and is hidden | chief, then operator (`chess-sco`, P2) | **Ruled**, operator 2026-10-02, `chess-r0o` comments 61 and 63; the report's lower-bound sentence is the required mitigation and is present | Not a defect. The ruling's stated consequence (lower bound) is delivered in every report I produced |
| `chess-6b7`: default `~/.cache/chessleak` shared, so two concurrent unconfigured runs contend on one sqlite eval cache | operator (cache location); chief for the agent convention | **Not ruled.** No operator ruling on the operator's own run path; the bead is filed, not deferred by the operator | No effect on the outcomes as I exercised them (every run I did pinned `--cache-dir`/env). It is a live risk for the *uncoached walkthrough*, which is deliberately unconfigured. Raised here so it is a decision rather than an unowned risk |
| `chess-kjk`: `DEVIATION_WEIGHT = 0.05` not re-derived against the ruled centipawn bands | owner of `cluster.py` (not named on the bead) | **Not ruled.** Filed as P3 by the team, not an operator deferral | Affects tie-break ordering only; ordering is correct as specified. Noted, not an acceptance blocker |
| `--max-games` surface (design-record Q5) | — | **Ruled**, operator 2026-10-02 (design record, *Rulings needed* §3) | Implemented as approved; exercised repeatedly |
| Severity banding (Q3) and cluster identity (Q4) | — | **Ruled**, operator 2026-10-02 (design record §1, §2) | Bands and identity verified as ruled |
| Serialized Stockfish slot bead for this round | chief (keeper of `chess-8el`) | **UNRESOLVED — no slot bead and no slot contact exist for round 1.** The record names setup facts but no resource slot, so there was nothing to claim or hand back | My use was light (≤2 engines, load-checked, no contention observed). The gap is a coordination-record gap, not an evidence gap; flagged for the record owner |
| F1 (delivered mate scored as a blunder) | unassigned — needs an owner | Not a scope question: an ordinary in-scope defect in a path this release owns. No ruling needed to repair | See Findings; it fails O3 as written |
| F2 (`--top 0` self-contradicting report) | unassigned | Ordinary in-scope defect | See Findings |

## Changes beyond the release outcomes

Checked against `git diff --name-status 3cd05e8..2ae9820`, the release-bead
readiness list (comment 68), and the design record:

| Declared change | What I checked | Result |
|---|---|---|
| Two post-ship behaviour fixes: engine determinism (`7b86b0b`), habits-only report (`6a8e8c8`) | Exercised both: cache-hit/no-engine warm runs (determinism fix, F3 qualifies its documented guarantee), habits-only ordering and withholding (ruling) | Habit behaviour as ruled. The determinism fix's *documented* guarantee is stronger than what the code achieves (F3) |
| Three small defects fixed: `--archive YYYY/MM`, duplicated output line, stale vcr docstring | `--archive 2023/11` works (used throughout); `stdout` carries the report path exactly once; cassette docstring | All confirmed |
| Four documentation corrections; version `0.1.0` in `pyproject.toml` and `__init__.py` | Read the three product documents at the corrected hashes; checked both version carriers | Consistent |
| Tracker migrated bd→br before the first unit | `br` only; `master` still frozen at `3cd05e8`; no interrupt-policy merge | No regression |
| `scripts/setup_env.sh`, `tools/pi_worker.py` (canary/harness additions) | Used `setup_env.sh` for setup (works from a clean checkout, names a real engine path); `tools/` excluded from ruff by design | No regression |
| Undeclared changes | The only non-`tests`/non-`docs` paths in the whole diff are the product package, the three scripts, `pyproject.toml`, `tools/pi_worker.py`, `.gitignore`, `AGENTS.md` | **None found** |

## Findings

### F1 — a move that delivers mate inside the opening window is reported as a blunder worth 100% of the win probability (major)

- **Requirement:** brief O3 — "each player move is classified `ok` / `inaccuracy` /
  `mistake` / `blunder` by its win-probability drop against the engine's best move
  in the position before the move, always from the player's point of view", and
  "mate scores map to ±1.0".
- **Exact revision:** `2ae982042129f553a1d61cf1d5281d3ddef0eee6`.
- **Setup:** `~/.cache/chessleak/eval-2ae9820/.venv`, Stockfish 19, disposable
  cache. Probe fixture `eval-scratch/probe/mate_probe.py` (invented content at the
  real archive layout; no cassette, nothing committed) and
  `eval-scratch/probe/severity_mate_probe.py`. Both are reusable.
- **Reproduction (CLI, end to end):**
  `chessleak analyze testplayer --archive https://api.chess.com/pub/player/testplayer/games/2099/01 --depth 14 --cache-dir … --out mate-report.md`
  over an archive holding two Fool's-mate games with the account as Black.
- **Expected:** the account's `2...Qh4#` *wins* the game. From the player's point of
  view the position before the move is a mate (win probability 1.0) and the
  position after is also a win, so the drop is 0 and the move is not a mistake —
  and, with no deviation flag, it would not be admitted to the report at all.
- **Observed:** the run's rank-1 habit reads

      ## 1. A00
      - **Composite score:** 2.00
      - **Seen:** 2 times
      - **Worst:** `blunder`
      - **Your move:** `Qh4#` ×2 vs **engine's best:** `Qh4#`
      - **Win% lost:** 100.0% average, 100.0% worst

  and the run reports `6 flagged mistakes`. The line contradicts itself: the
  player's move *is* the engine's best move, it mated, and the report says it cost
  the whole win probability.
- **Mechanism, isolated with the real engine and the real severity code**
  (`severity_mate_probe.py`, one shot per case):

      player delivers mate (Fool's, Black)   before: mate=1   after: mate=0  -> cp_loss=0 winprob_drop=1.000 klass=blunder
      player delivers mate (Scholar's, White) before: mate=1   after: mate=0  -> cp_loss=0 winprob_drop=1.000 klass=blunder
      player is mated by the opponent         before: mate=-1  after: mate=0  -> cp_loss=0 winprob_drop=1.000 klass=blunder

  `severity.move_severity` short-circuits on `is_terminal(eval_after)` and returns
  `blunder` / `winprob_drop = 1.0` before it ever asks *who* delivered the mate.
  `EvalResult` answers a checkmate as `mate = 0` from either side (`engine.py`'s
  `_terminal_result`), so a delivered mate and a received mate are the same value.
  `book.py` guards exactly this case in `_cp_gap` ("delivering mate would read as
  the largest leak in the window"); `severity.py` does not. A stalemate or an
  insufficient-material draw after the player's move reaches the same branch and
  would read as a 100% loss as well (not reachable inside a 15-ply window in
  practice).
- **User consequence:** the player is told their most-repeated habit is a blunder
  that throws away the game, when it wins it. On the operator's own account
  (`kijuu11`, whole published history, 2,185 games) **3 games end by checkmate
  inside the 15-ply window and in all 3 the account made the mating move**, so
  those runs always inflate "Flagged mistakes" with moves that were wins; where the
  same mating position recurs (as in the probe) it becomes the top-ranked habit.
- **Repair direction (engineering, not mine):** distinguish the two terminal
  cases before the short-circuit — `mate == 0` after a position in which the player
  had `mate > 0` is a *won* game (no loss, class from `cp_loss`), and a terminal
  position that is a draw is not a 100% loss either.

### F2 — `--top 0` writes a report that contradicts its own header (minor)

- **Revision:** `2ae9820`. **Setup:** as above.
- **Reproduction:** `chessleak analyze kijuu11 --max-games 60 --depth 12 --top 0`
  over the warm real cache. The flag is accepted (`_non_negative_int`).
- **Expected:** a report that does not deny the six habits its own header names.
- **Observed:** header `_Showing the top 0 of 6 habits, …_`, then
  `## No recurring habits` / "No position in this run was both reached more than once
  and played worse than the engine's best. Nothing to fix here."
- **Mechanism:** `report.render_report` gates that section on `shown` (the
  truncated list) rather than on `habits`. With a genuinely empty habit list the
  wording is correct (verified separately).
- **User consequence:** a reader is told there is nothing to fix when there are six
  habits. Small, opt-in flag, but the report is the product.
- **Repair direction:** branch on `habits` (and keep the "showing the top N of M"
  line for the `top_n` cap).

### F3 — the eval-cache key drops the halfmove clock, but the engine's answer depends on it (minor, documented-contract)

- **Requirement:** `engine.py` states "A score is a property of its position, not of
  what was searched before it", and `analyse` states that one position at one depth
  answers identically "in one process or two". `position_key` (design record)
  deliberately drops the halfmove clock so one board reached at different move
  counts is one cache row; the engine is searched from the **full** FEN, clock
  included.
- **Reproduction:** one real board at depth 12, real Stockfish 19, shipped service,
  each in its own fresh cache, changing only the FEN's move counters
  (`counter_spread.py`): halfmove 0/1/2/3/4/10/49 → cp 54 / 67 / 63 / 78 / 63 / 60 /
  67, with two different best moves; the fullmove number changes nothing (54 for
  1/2/8/20). Stockfish takes its `rule50` counter from the FEN, so the same board
  with a different halfmove clock is a different search input.
- **Observed exposure on the real 60-game slice** (`halfmove_exposure.py`): 15 of
  592 positions are reached with more than one halfmove clock; for all 15 the
  engine's **best move** depends on which clock's FEN populated the row (cp equal
  in this slice); **0** player moves change severity class here.
- **Expected vs observed:** expected a position's numbers to be a function of the
  board alone; observed that the stored best move (and, on other boards, up to
  ~24 cp of cp) is a function of whichever ply first reached the position. With
  50/100/200 cp bands, a cp difference of that size can decide a class at an edge;
  I did not observe a class flip on this corpus, so that part is a mechanism, not a
  demonstrated misclassification.
- **Repair direction:** normalise the halfmove clock (or the whole FEN's counters)
  before searching, so the cached value is a well-defined function of the board and
  the documented guarantee holds; the cache-sharing benefit is unaffected.
- **Not a finding (recorded so nobody re-chases it):** the pipeline itself *is*
  reproducible. Two independent cold runs of the same command into separate caches:
  356 positions, **0** rows differing, reports byte-identical apart from the
  cache-hit-rate line. A 60-game vs 40-game cold pair: 413 shared positions, **0**
  differing. The original run's cache vs an independent cold run: 594 rows, **0**
  differing. My first observation of shifting composite scores was my own error —
  I had two runs overlapping on one cache file — and the clean re-test above
  clears the product.

### Observations (kept separate from requirement violations)

- **Progress line states something untrue.** `cli.analyze` prints "N opponent plies
  were scored and not aggregated", and the module docstring says "The whole window
  is scored, opponent's plies included". `_score_game` does the opposite: it
  `continue`s on `not ply.is_my_move`, so opponent plies are never scored and
  never aggregated. The number printed (451 on a 60-game run) is the count of plies
  *skipped*. Cosmetic, but it is a factual claim in user-visible output.
- **`games_skipped` counts the whole history, not the analysed window.** On a
  `--max-games 60` run over 2,185 games the header reads "Games analyzed: 60 /
  Games skipped: 5", which does not account for the games the bound excluded. With
  the default unbounded run the accounting is exact. Clarity, not correctness.
- **Withheld sentence wording.** "N one-off positions omitted (reached once, so not
  habits)" counts one-off *clusters*, and `occurrences` counts admitted moves, so a
  position reached four times with one leak is described as "reached once". This
  matches the operator's intent (a one-time mistake is not a habit) and the design
  record's definition of the field; the wording is loose. Inferred preference, not
  a requirement.

## Disposition and limits

**Not accepted** against the stated release requirements: O3 fails as written on
candidate `2ae9820` (F1 — a delivered mate is classified as a 100%-loss blunder, in
real data on the operator's own account), with two smaller in-scope defects (F2,
F3). O1, O2, O4, O5, O6 and the opening-phase constraint pass on the evidence
above, and the published suite artifacts reproduce on this exact candidate.

Unverified / limits:

- The **uncoached walkthrough** (real-journey check 3) is the operator's evidence;
  it is not performed and not substitutable by my agent-side run. The brief makes
  it required before acceptance.
- O4's "first deviation at a known ply" is evidenced by code and observed report
  output rather than by my own independent re-derivation.
- My runs used depth 12 for tractability (the design record's own e2e bound); the
  operator's default is 18, which the 24-minute estimate in the record implies. A
  depth-18 run would shift band-edge counts; I did not measure that.
- The Stockfish slot record the round guide asks for does not exist, so resource
  coordination for this round ran on host inspection only.
- F3's class-flip consequence is a mechanism, not an observed misclassification.

This disposition is evidence about the release requirements. It is not merge or
deployment authority.

## Teardown, data and retained evidence

- No live processes of mine remain: `pgrep stockfish` empty after every run; the
  `with` block in `analyze` and `EngineService.close()` quit each engine.
- The **operator's own account data was treated as scoped data**: the `kijuu11`
  archive cache (38 archives, 2,185 games), its derived eval caches and all
  `kijuu11*.md` reports were deleted at teardown. Nothing about that account is
  retained beyond the aggregate figures quoted above, and nothing was committed or
  pushed anywhere.
- Retained under `~/.cache/chessleak/eval-scratch/` (disposable, outside any
  worktree): this report, the probe scripts listed above, the bobbyfischer reports
  (public non-personal account), the synthetic mate-probe report, and the suite
  log.
- The verification checkout `~/.cache/chessleak/eval-2ae9820` was **not** removed:
  the round record names it as this round's shared verification checkout, prepared by
  the keeper, so removal is the keeper's decision. It is left detached at `2ae9820`
  with tracked files clean; its only untracked addition is the `.venv` this lane
  built.
- No slot was taken or handed back, because the round has no slot bead.

## Learning evidence

- **Prediction vs observation:** readiness predicted PASS/high for O1, O3, O5, O6
  and PASS-with-low-demonstration for O2; observed pass, **fail**, pass, pass and
  pass-with-demonstration respectively. The one miss is O3, and it is a miss in a
  branch the readiness evidence never exercised (a terminal position produced by the
  player's own move). The O2 "ordering is under-demonstrated" caveat was correct and
  is now closed by the operator's own account.
- **Evaluator misses / false alarms (mine):** I first believed the report was
  non-reproducible from differing composite scores between runs. That was my own
  concurrency error on one sqlite file, and the clean serial re-test cleared the
  product; recorded in F3's "not a finding" so it is not re-investigated.
- **Retrospective process notes (my own, before reading others'):** the productive
  part of this round was spending an independent budget on *real* journeys with the
  operator's own account and on building a probe fixture whose truth I knew in
  advance (a mate in the window), which is what surfaced F1 — no team artifact did.
  The unproductive part was chasing an engine anomaly through raw python-chess probes
  before controlling for my own concurrent runs; two probes measured my harness
  rather than the product. Control runs (serial, one cache per run, same inputs)
  should come *before* mechanism hunting. Publishing the round's cache-state caveat
  next time would have saved part of that.
- Resource use: this lane ran one 298-test suite (170 s), eight Stockfish-backed
  probes and six real CLI runs over ~4,100 engine-heavy seconds wall-clock in
  total; no cost/token figures are available to me and none are invented here.
- Private scenarios: none were supplied separately for this lane; every scenario
  above derives from the public brief, the PRD and the operator's own rulings, and
  the ones I constructed (Fool's-mate archive, ordering over many habits, the
  halfmove-clock spread) are now disclosed and are regression cases, not held-out
  evidence.