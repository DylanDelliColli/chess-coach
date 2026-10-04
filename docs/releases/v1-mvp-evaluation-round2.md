# Repair-verification report — chessleak v1 MVP, candidate `23066a7`

Evaluator: `eval-0b7792567c53` (Herdr `ao-ff0ffcff-eval-0b7792567c53`, pane `w3:pS`).
Round 2, launched on the repair candidate. Independent lane, fresh context, no builder
memory; the only product sources read were the three operator/engineering documents
named below. Launch receipt: comment 88 on `chess-8el`.

## Release evaluation

- **Release / release bead:** chessleak v1 MVP, `chess-r0o`. Round child bead
  `chess-8el` ("Evaluation round 1: candidate 2ae9820"), which is also where round 2's
  run-information record lives (comment 87).
- **Candidate commit and verification checkout:**
  `23066a774cb3889fbe4db75102ffb6ad330b279b` — "Merge repair round 1: chess-nl7 (F1),
  chess-ln9 (F2), chess-r49 (F3)". Checkout `~/.cache/chessleak/eval-23066a7`, detached
  at the candidate. `git status --porcelain` empty at start and at end (no tracked and no
  untracked change); the only additions were this lane's own `.venv/` and
  `__pycache__/`. Removed at teardown (see *Teardown*).
- **Base commit used for regression comparison:** `master` at `3cd05e8` (bd→br
  migration), confirmed frozen: local `master` and `origin/master` both `3cd05e8`. The
  base carries no product code, so regression comparison here is against the previous
  **candidate** `2ae9820`, which is what this round exists to check. `origin/release/v1-mvp`
  is still at `2ae9820` (see *Scope questions*).
- **Product source paths and SHA-256:**
  | source | path | sha256 | matches launch context |
  |---|---|---|---|
  | PRD (authority) | `docs/PRD.md` | `b7c30597…b8c09` | yes |
  | Release brief (authority) | `docs/releases/v1-mvp.md` | `407cc903…da42d3c` | yes |
  | Design record (engineering, not authority) | `docs/releases/v1-mvp-design.md` | `82d34344…1eec1b4d` in the candidate | **no** — the launch context names `8984db13…` |
  The design-record mismatch is benign and fully explained: `release/v1-mvp` has since
  advanced to `1667e6a`, whose entire diff from the candidate is `docs/` (the design
  record's `move_severity` contract line, corrected by `chess-l7t`, plus the round-1
  report added under `docs/releases/`). Product source bytes are identical at `23066a7`
  and `1667e6a`. Recorded as a launch-context/readiness correction, not a product issue.
- **Evaluator client / model / effort and times:** Pi, OpenRouter
  `stealth/space-bunny-alpha`, `xhigh` (as requested in the launch context and as the
  operator's 2026-10-01 model directive requires). Evaluation window 2026-10-03
  11:05–11:52 UTC.
- **Setup, runtime/data and commands:**
  - `bash scripts/setup_env.sh` → this lane's own `.venv`, Stockfish 19 at
    `~/.local/share/chessleak/stockfish/stockfish` (shared, read-only, never modified).
  - `.venv/bin/python -m pytest -q` → **`310 passed in 168.18s`** (chief's published
    artifact for this candidate: "310 passed" — reproduces).
  - `.venv/bin/python -m ruff check .` → `All checks passed!` (reproduces).
  - `.venv/bin/python -m ruff format --check .` → `41 files already formatted` (reproduces).
  - The round-1 e2e artifact (`report.md` sha256 `105bfd55…`) **does not reproduce**, and
    should not: see *Changes beyond the release outcomes*. The round-2 record publishes
    no replacement e2e hash, so I ran the published command myself on a cold cache.
  - Real journeys run, all with real Stockfish, a real filesystem and, where stated,
    live HTTP: `bobbyfischer` 2023/11 (30 games cold; the full 85-game month cold twice
    for a reproducibility pair; `--top 0/1/3/20`); a synthetic mate archive driven
    through the real CLI; and `kijuu11` (PRD R4) live from an empty cache over its whole
    published history (38 archives, 2,191 games), `--max-games 60 --depth 12`, then a
    warm re-run with `HTTP(S)_PROXY` pointed at a dead port. A controlled base
    comparison ran the **real** `2ae9820` CLI from the round-1 verification checkout on
    the same slice with a cold cache, read-only (`PYTHONDONTWRITEBYTECODE=1`, its own
    `--cache-dir` and `--out`).
  - Probes (all retained, all outside any worktree, under `/tmp/eval-0b7792567c53/probe/`):
    `sev_probe.py`, `counter_probe.py`, `determinism_probe.py`, `fen_invariant_probe.py`,
    `mate_scan.py`, `mate_fixture.py`, `o2_invariants.py`, `attrib2_probe.py`,
    `attrib_kijuu.py`.
  - **Resource note:** the round-2 record names no serialized-resource slot bead and no
    slot contact, so there was nothing to claim or hand back (same gap round 1 raised).
    I checked `herdr agent list`, `pgrep stockfish` (none running at start) and host load
    (0.30–0.90 on 24 threads) and ran at most two engine-heavy jobs at once. No Stockfish
    process of mine outlived its run; `pgrep stockfish` empty at teardown.
- **Canonical run-information record for this round:** `chess-8el` comment 87 (chief,
  keeper, 2026-10-03 11:04 UTC), read after my initial product-source reading and again
  at teardown; unchanged during the round. No new operator comment appeared on `chess-r0o`
  during my lane. Round 1's record is comment 69; its report is comment 70 and
  `docs/releases/v1-mvp-evaluation-round1.md`.

## Outcome evidence

Team prediction column: readiness `chess-r0o` comment 68 (declared for `2ae9820`) plus
the round-2 record's setup facts. There is **no readiness declaration for `23066a7`**, so
the per-surface predictions for this candidate are inherited from round 1 and are shown
as such.

| Outcome / consumer surface | Team prediction / confidence | Observed | Evidence / limitations |
|---|---|---|---|
| **F1** — a delivered mate is `ok` | (round 1: **fail**, major) | **fixed** | Probe, real engine, probe-valid cases: delivered mate `ok`/drop `0.000` in both colours. Round-1 reproduction archive through the real CLI: rank-1 habit "`Qh4#` ×2 … `blunder` … Win% lost 100.0%" → **0 habits, 2 flagged**, both mating moves `ok`. On `kijuu11`'s own 60-game slice: the one in-window mate is the account's, `ok`/`0.000` (round-1 rule: `blunder`/`1.000`) |
| **F1 neighbour** — a real loss to mate still reads as one | (not predicted) | **pass** | `allows mate` → `blunder`, drop `0.530`; `throws away a mate it had` → `blunder`, drop `0.241`; `moved into insufficient material` → `ok`/`0.000`; bare kings → `ok`; 75-move rule answered from the real board (engine **not** asked), which is the repair's documented ordering claim |
| **F1 neighbour** — the invariant the new reasoning rests on | (not predicted) | **pass** | 2,121 real player plies (85 + 200 games, shipped extractor): `fen_before` always has the player to move and `fen_after` always equals *before + the player's own move*. 0 failures |
| **F2** — `--top 0` cannot deny the habits its header names | (round 1: minor defect) | **fixed** | `--top 0` over 11 habits now writes "Showing the top 0 of 11 habits" and no "No recurring habits" denial. `--top 1/3/20` still render 1/3/11 entries. A genuinely empty habit list still writes the section (verified: 0-habit mate-archive run) |
| **F3** — the eval cache searches the position it keys on | (round 1: minor, documented contract) | **fixed** | One board at halfmove 0/1/2/3/4/10/49 → identical cp and best move (each a cold cache); fullmove 1/2/8/20 → identical; two clocks at one shared cache → one row (1 miss / 1 hit); a row written at clock 3 replays identically at clocks 0 and 40 |
| **F3 neighbour** — the seventy-five-move rule still comes from the real board | (not predicted) | **pass** | A real board at halfmove 150 answers `cp=0 mate=None best_move=None` — the board decided, the engine was never asked |
| **O1** — CLI `chessleak analyze <username>` | pass, high (inherited) | **pass** | Live `kijuu11` run from an empty cache: 38 archives downloaded, 2,191 games in history, 60 analysed, report written, exit 0 |
| **O1** — terminal progress output | pass, high (inherited) | **pass** | Per-game lines `[n/60] … 15 plies, book deviation` throughout, plus the summary and hit-rate lines; report path printed exactly once on stdout |
| **O1** — written markdown report file | pass, high (inherited) | **pass** | Written to `--out`; re-parsed independently by my own parser for O2 |
| **O1** — second run over an unchanged cache does no network work | pass, high (inherited) | **pass** | Warm re-run with the proxy pointed at a dead port: exit 0, `1354 cache hits / 0 searches`, report byte-identical to the cold run except the hit-rate line |
| **O2** — ranked cluster sections | pass (round 1: low on demonstration; closed) | **pass** | 85-game corpus: 11 habits at occurrences 4, 3, 3, 2×8, ties ordered by descending composite (1.39, 0.43, 0.28, 0.28, 0.23, 0.21, 0.20, 0.12). `kijuu11`: 4 habits at 31, 12, 3, 2 |
| **O2** — ordering / withholding invariants | pass (inherited) | **pass** | Independent parser **plus** independent re-derivation from the returned clusters (`o2_invariants.py`): ranks 1..n, every entry `occurrences ≥ 2`, occurrences non-increasing, ties by descending cost, header withheld count equals the run's own `one_off_positions_omitted` (243), lower-bound sentence present, body count = `min(habits, top_n)`. 0 failures |
| **O2** — `top_n` truncates the habit list | pass (inherited) | **pass** | `--top 1/3` → "Showing the top N of 11 habits" with exactly N entries, not padded. `--top 0` is F2, now fixed |
| **O2** — header states the withheld count and the lower bound | pass (inherited) | **pass** | Both sentences unconditional, present in every report I produced, including the 0-habit one |
| **O3** — centipawn bands | pass, high (inherited) | **pass** | Shipped classifier: 0→ok, 49→ok, 50→inaccuracy, 99→inaccuracy, 100→mistake, 199→mistake, 200→blunder, 500→blunder, −5→ok. Thresholds 50/100/200, `win_prob_k` 0.004 |
| **O3** — mate scores map to ±1.0, player's POV | round 1: **fail** (F1) | **pass** | See the F1 rows: `ok`/0.000 for a delivered mate, `blunder` for a mate allowed or given away |
| **O4** — deviation markers and counts in the report | pass, moderate (inherited) | **pass** | 85-game corpus: 8 of 11 habits carry the marker with counts that match the occurrences (31/31 and 12/12 on `kijuu11`; 4/4, 3/3, 2/2, 1/2 elsewhere). Carried forward from round 1 as code-plus-observed output: I did not independently re-derive a first deviation at a known ply |
| **O5** — on-disk cache, no auth, UA, no re-fetch | pass, high (inherited) | **pass** | From an empty cache: username-keyed index file (case-folded) + one file per monthly URL + `evalcache.sqlite`, 7.6 MB for 38 archives. No credential anywhere in the tree; the tool's UA is in both committed cassettes and chess.com answered 200 live. Same black-holed-proxy warm run as O1 |
| **O5** — data-provenance summary in the header | pass (inherited) | **pass** | Header carries games analysed, games skipped, positions evaluated, flagged mistakes, hit rate and one-offs omitted; the `kijuu11` run counted 5 non-standard games skipped |
| **O6** — deterministic suite run | pass, high (inherited) | **pass** | `310 passed in 168.18s` on this exact candidate, matching the chief's published count |
| **O6** — no mock of engine/transport/disk in an integration assertion path | pass, high (inherited) | **pass** | `tests/integration/` contains no `mock`, `monkeypatch` or `patch` in any assertion path; every hit is a docstring saying there are none, plus one test that writes a real fake-interpreter script to exercise `setup_env.sh`'s version guard |
| **O6** — every module exercised from both suites | pass (inherited) | **pass** | Unchanged from round 1; the repair added tests, not removed them (12 files changed, 8 of them tests) |
| Release constraint — opening phase only (first 15 plies) | (not separately predicted) | **pass** | Shipped extractor over 2,276 real games (33,840 plies): **0** plies with `ply_index ≥ 15`, maximum window length 15 |
| Version `0.1.0` (operator, 2026-10-02) | declared change | **pass** | `pyproject.toml` and `src/chessleak/__init__.py` agree; `tests/unit/test_version.py` pins them |
| Pipeline reproducibility | (round 1: pass) | **pass** | Two independent cold runs of the 85-game corpus into separate caches: reports byte-identical apart from the hit-rate line |
| Real-journey check 2 — one real input through the real processing and report | done for the cassette account | **pass, agent-side** | `kijuu11` live from an empty cache, real Stockfish, real report; also the committed `bobbyfischer` month in full |
| Real-journey check 3 — uncoached walkthrough from an empty state | outstanding; operator's to perform | **unverified** | Not performed and not substitutable by an agent run. The brief makes it required evidence before acceptance |

## Scope questions

| Requirement / finding | Follow-up owner | Operator ruling and source, or UNRESOLVED | Effect on prediction and assessment |
|---|---|---|---|
| No readiness declaration and no published deterministic-suite artifacts for candidate `23066a7` | chief (`ao-ff0ffcff-chief`) | **Not a product question — a record gap.** The guide requires the declaring peer to publish suite commands, logs and artifact hashes per candidate in the run-information record; comment 87 publishes "310 passed" with no log or e2e hash | I re-ran the suite, both lint checks and the published e2e command myself. This is why my numbers, not the record's, are the evidence above |
| Round-1 e2e artifact `105bfd55…` is stale for this candidate | chief | Same gap. My cold run of the published command gives `0c2ff797b5947fc5de23f2bce23d4edb660352b908f3b73c272a230ae3e1b4d8` | Expected and legitimate (the report's content changed); recorded so nobody re-chases it as a reproducibility failure |
| Round 2's run-information record is comment 87 on **round 1's** bead rather than a round-2 child bead with its own record | chief | Record gap against the guide's one-record-per-round rule | I used comment 87 as the canonical record for this round, as instructed, and flagged it. No effect on any outcome |
| No serialized-resource slot bead for round 2 (or round 1), no slot contact | chief | **UNRESOLVED** as a record gap; raised by round 1 and still absent | Nothing to claim, so nothing was claimed. My engine use was light and load-checked; no contention observed. Not an evidence gap |
| Launch-context design-record hash `8984db13` vs the candidate's `82d34344` | chief | Not a product question. `8984db13` is `release/v1-mvp` at `1667e6a`, a docs-only commit after the candidate | No product difference; the PRD and brief hashes matched exactly |
| `origin/release/v1-mvp` is still at `2ae9820`; the repair merge `23066a7` and `1667e6a` are unpushed | chief | Publication fact, not a product question. The brief has the chief push the release branch after each merge; merging into `master` and tagging stays with the operator | No effect on the evaluated bytes. Recorded so the operator knows what a later `master` merge would carry |
| Positional similarity (`chess-sco`) deferred: a habit reached by transposition/mirror counts as one-offs and is hidden | chief → operator | **Ruled**, operator 2026-10-02, `chess-r0o` comments 61 and 63. The report's lower-bound sentence is the required mitigation and is present in every report I produced | Not a defect |
| The 30 cp book band is knife-edge under an honest cache (a position that measured 30 cp measures 31 cp and enters the report with worst class `ok`) | operator, via chief | Named in the round-2 record as an open question that is **not a defect to penalise** | No effect on pass/fail. See *Observation 4* below for the measured size of this on the operator's own account |
| `chess-6b7`: default `~/.cache/chessleak` shared, so two concurrent unconfigured runs contend on one sqlite eval cache | operator (cache location); chief (agent convention) | **Not ruled.** Filed, not deferred by the operator | No effect on the outcomes as I exercised them (every run pinned `--cache-dir`). Still a live risk for the deliberately-unconfigured operator walkthrough. Raised so it is a decision, not an unowned risk |
| `chess-kjk`: `DEVIATION_WEIGHT = 0.05` not re-derived against the ruled centipawn bands | owner of `cluster.py` (not named on the bead) | **Not ruled.** Filed as P3 by the team, not an operator deferral | Tie-break ordering only; ordering is correct as specified. Noted, not an acceptance blocker |

## Changes beyond the release outcomes

`git diff --name-status 2ae9820 23066a7` is twelve files and nothing else:
`config.py`, `engine.py`, `report.py`, `severity.py` and eight test files. **`cli.py`,
`pgnio.py`, `book.py`, `cluster.py` and `fetch.py` are untouched**, so the O1/O2/O5
plumbing cannot have moved.

| Declared change | What I checked | Result |
|---|---|---|
| `chess-nl7` (F1): a delivered mate is a win | Probe in both colours, the four neighbouring mate/draw cases, the round-1 reproduction end to end, the PRD's own validation account, and the invariant the new rule rests on | Fixed; no neighbouring behaviour lost |
| `chess-ln9` (F2): `--top 0` cannot deny habits | `--top 0/1/3/20` over an 11-habit run, plus the genuinely-empty case | Fixed |
| `chess-r49` (F3): the cache searches the position it keys on | Clock and fullmove spreads on cold caches, cache-row sharing, replay stability, the 75-move-rule ordering claim | Fixed |
| **Undeclared:** F3 changed what the report surfaces on real data | Measured, not assumed — see below | Disclosed by the team; quantified here |
| **Undeclared:** three integration fixtures were changed (Italian lines replaced by Ruy Lopez lines) and one cluster-pipeline assertion was rewritten | Read the diff and the tests' own comments; the replacement lines decide the band by hundreds of centipawns rather than one, which is a real improvement to the fixtures; the rewritten assertion now states the admission rule on the data instead of assuming the set is empty | Consistent with the repair; no test was weakened to hide a product regression |

**Attribution of the change in real output, measured.** I ran the shipped pipeline over
the 85-game corpus three times with cold caches, reverting exactly one repaired thing
per run (`attrib2_probe.py`, in-process patches, no file modified):

| run | flagged | one-offs | habits |
|---|---|---|---|
| round 1's published header for this corpus | 226 | 247 | 10 |
| run 3 — F1 **and** F3 reverted | 226 | 247 | 10 (identical entries and composites) |
| run 2 — F3 reverted only | 226 | 247 | 10 (identical to run 3) |
| run 1 — 23066a7 as shipped | 224 | 243 | 11 |

Run 3 reproduces round 1's published numbers entry for entry, so the harness is faithful
and the difference is attributable. F1 contributes nothing on this corpus (no mate inside
the window), and **all** of the post-repair change is F3: flagged 226→224, one-offs
247→243, one new 2-occurrence habit, one entry moving from `inaccuracy` to `mistake`, and
small composite shifts. No round-1 habit was lost.

**The same attribution on the operator's own account**, where it is larger. The
`kijuu11` 60-game slice is identical across rounds (592 positions evaluated in round 1
and here). Cold-cache runs of the **real** `2ae9820` CLI, of my F3-reverted emulation and
of the shipped candidate:

| run | flagged | one-offs | habits |
|---|---|---|---|
| round 1's published header (**100% warm cache**) | 81 | 61 | 6 (29, 10, 3, 3, 2, 2) |
| real `2ae9820`, cold cache | 87 | 66 | 5 (31, 12, 3, 2, 2) |
| F3-reverted emulation, cold cache | 87 | 66 | 5 (identical, position by position) |
| `23066a7` as shipped, cold cache | 80 | 66 | 4 (31, 12, 3, 2) |

Two things follow, and the second is the more useful one. First, the repair removed 7
flagged moves from the operator's own report and withdrew one recurring 2-occurrence
book-deviation habit — the honest consequence of searching the position rather than the
route to it, and the direction the team disclosed. Second: **round 1's header and my
cold-cache base run disagree on the same code and the same slice** (81/61/6 against
87/66/5) purely because round 1 ran on a cache populated by earlier runs. That is the F3
defect visible from outside the engine: before the repair, what the report said about
this account depended on which run had happened to write the eval cache. After it, three
shipped runs (two cold, one warm) agree exactly.

## Findings

No new defects. The three round-1 findings are closed on this exact candidate, with the
reproductions above. What follows is material for the team but is not a violation of a
stated requirement.

### Observations (kept separate from requirement violations)

1. **A user-visible line states something untrue.** `cli.analyze` prints "N opponent
   plies were scored and not aggregated" (449 on the `kijuu11` 60-game run), and
   `_score_game`'s docstring says the same. `_score_game` does the opposite: it
   `continue`s on `not ply.is_my_move`, so opponent plies are never scored and never
   aggregated — the number printed is the count of plies *skipped*. Round 1 raised this;
   it is unchanged. Cosmetic, but it is a factual claim in the product's own output.
   Owner: whoever next touches `cli.py`.
2. **`games_skipped` counts the whole history, not the analysed window.** On
   `--max-games 60` over 2,191 games the header reads "Games analyzed: 60 / Games
   skipped: 5", which does not account for the games the bound excluded. With the default
   unbounded run the accounting is exact. Clarity, not correctness. Carried from round 1.
3. **Withheld-sentence wording.** "N one-off positions omitted (reached once, so not
   habits)" counts one-off *clusters*, while `occurrences` counts admitted moves, so a
   position reached four times with one leak is described as "reached once". This matches
   the operator's intent and the design record's definition of the field; the wording is
   loose. Inferred preference, not a requirement. Carried from round 1.
4. **`--top 0` now writes an empty body with no explanatory line.** After the F2 repair
   the report says "Showing the top 0 of 11 habits" and then shows nothing. That is
   honest — it no longer denies the habits — but a reader sees a header claiming eleven
   habits and an empty document. A one-line note (`top_n = 0, so no entries were
   rendered`) would close the gap. Inferred preference; the operator's, not mine, and not
   a requirement.
5. **The honest cache changes what the report finds on the operator's own account**, as
   quantified above: 7 fewer flagged moves and one fewer recurring book-deviation habit
   on the 60-game slice. This is the disclosed consequence of F3, not a defect, but it is
   a product-visible reduction in what the tool offers the player, so it belongs in front
   of the operator together with the 30 cp band question rather than only in a commit
   message.

### Already disclosed failures

- `chess-6b7` (shared default cache dir) and `chess-kjk` (deviation weight) remain open
  and unruled, unchanged by this repair.
- Round 1's F3 "class-flip consequence" was recorded as a mechanism rather than an
  observed misclassification. It is now moot in the useful direction: the cached value is
  a function of the position, so the mechanism is gone rather than unobserved.

## Disposition and limits

**Accepted as a repair.** All three round-1 findings are fixed on candidate `23066a7`
with reproductions; the neighbouring behaviour each repair touched still behaves; no new
defect was found; and every outcome I could exercise — O1, O2, O3, O4, O5, O6, the
opening-phase constraint and the version — passes on this exact candidate with real
Stockfish, real HTTP and real filesystem, against the published suite artifacts.

**Release-level acceptance remains conditional on real-journey check 3**, the operator's
uncoached walkthrough from an empty cache. It is unverified, it is not substitutable by
any agent run, and the brief makes it required evidence before acceptance. My disposition
covers the evaluated requirements only; it is not merge, tag or deployment authority, and
it does not lift any operator hold.

Limits and unverified behaviour:

- **Real-journey check 3** — the operator's evidence, unverified by me.
- **O4's "first deviation at a known ply"** remains code-plus-observed-output evidence,
  not my own independent re-derivation (carried from round 1).
- **Depth.** My runs used depth 12 throughout, the design record's own e2e bound; the
  operator's default is 18. A depth-18 run shifts band-edge counts and I did not measure
  it.
- **No readiness prediction existed for this candidate**, so the prediction column above is
  round 1's, inherited. Where the team's confidence was high and round 1's evaluator
  disagreed (O3) I have re-derived the outcome myself rather than accepting either side.
- **The retained round-2 record publishes no suite log or e2e artifact hash**, so I re-ran
  the suite and the published e2e command rather than trusting the counts. The counts
  reproduce.
- **F3's residual risk is a product decision, not a defect:** the counter-free search
  discards the fifty-move information the engine would otherwise use. In a 15-ply window
  the halfmove clock cannot approach 100, and I verified the one rule that reads the real
  clock (seventy-five moves) still does.

## Teardown, data and retained evidence

- **No live processes of mine remain.** `pgrep stockfish` empty; the `analyze` context
  manager and `EngineService.close()` quit every engine it launched.
- **The operator's own account data was treated as scoped data and deleted.** The
  `kijuu11` archive cache (38 archives, 2,191 games, 7.6 MB), the base-candidate cache
  built from it, the emulation caches built from it and every `kijuu11` report and
  report-shaped aggregate were deleted at teardown. Nothing about that account is
  retained beyond the aggregate figures quoted above, and nothing was committed or pushed
  anywhere.
- **Retained** under `/tmp/eval-0b7792567c53/` (outside any worktree, disposable):
  this report, all nine probe scripts, the `bobbyfischer` (public, non-personal) reports
  `report30.md`, `full85.md`, `full85-run2.md`, `top0/1/3/20.md`, the synthetic mate-probe
  report, the suite and lint logs, and the probe outputs named in the tables above.
- **Verification checkout `~/.cache/chessleak/eval-23066a7` removed.** No process was
  using it, its tracked and untracked files were clean, and nothing in it was evidence:
  its only additions were this lane's `.venv/` and `__pycache__/`. It is rebuildable with
  `bash scripts/setup_env.sh`. Round 2's record names no verification checkout, so unlike
  round 1 there was no keeper-owned checkout to leave in place.
- **Other checkouts untouched:** `eval-2ae9820` (round 1's, keeper-named), `verify-tip`,
  `verify-k1s`, `verify-repair`, `chess-wk-repair` and the primary checkout were read or
  listed only. The single command I ran in `eval-2ae9820` was read-only against the
  product source, with `PYTHONDONTWRITEBYTECODE=1` and its own `--cache-dir`/`--out`.
- **No slot was taken or handed back**, because the round has no slot bead.

## Learning evidence

- **Prediction versus observation.** Round 1's readiness predicted PASS/high for O3 and
  round 1's evaluator found a fail; the team's repair closed it and my independent probe,
  end-to-end reproduction and the operator's own account all agree. Round 1's O2 caveat
  ("the ordering is under-demonstrated end to end") was right and stays closed: the
  ordering invariant held on two corpora at this candidate.
- **Evaluator misses and false alarms (mine).** Two, both probe bugs, both caught and
  corrected before any claim was made, and recorded so they are not re-investigated:
  (a) my first severity probe asserted "player is mated by the opponent" using Fool's mate
  with the player as the side that does *not* move last, so `before` had the wrong side to
  move — round 1's version of that case has the same structural fault, and at `2ae9820`
  the bug was invisible because every terminal position scored the same way; (b) a
  Threads=2 raw-engine harness of mine showed 11 cp of run-to-run spread, which looked
  like a determinism defect until I read `DEFAULT_ENGINE_OPTIONS` — the shipped service
  pins `Threads=1` precisely for this, so the shipped path is stable (8/8 identical) and
  my harness was the thing that varied.
- **Retrospective process notes (my own, before reading others').** What paid off was
  spending the budget on *reproduction* rather than re-derivation: replaying round 1's
  three reproductions unchanged, and then running the pipeline three times with exactly
  one repair reverted per run. That turned "the numbers moved, as disclosed" into a
  measured attribution, and it surfaced something neither round 1 nor the team had
  measured — that the pre-repair report for the operator's own account depended on which
  run had populated the eval cache. What did not pay off was hand-writing chess positions
  for the probe corpus: probing for a stalemate and an insufficient-material line by
  breadth-first search cost more than the two synthetic FENs were worth, and every case I
  ended up keeping was a game line whose truth I already knew.
- **Resource use.** This lane ran one 310-test suite (168 s), two lint checks, eleven
  real CLI runs (four over the committed cassette corpus, three over `kijuu11`, one over
  the synthetic mate archive, one base-candidate run, two truncation runs) and eight
  probe programs, roughly 45 minutes of wall clock including downloads. No token or cost
  figures are available to me and none are invented here.
- **Private scenarios.** None were supplied separately for this lane. Every scenario here
  derives from the public brief, the PRD, the operator's rulings on `chess-r0o` and the
  three round-1 findings; the ones I constructed (the F1 mate archive, the clock spread,
  the terminal-draw FENs, the reversion harness) are now disclosed and are regression
  cases, not held-out evidence.
