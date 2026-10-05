# Shift change — chessleak v1 MVP (`chess-r0o`), 2026-10-03

**For the next chief. Read this, then `docs/releases/v1-mvp.md` (the brief) and
`docs/releases/v1-mvp-design.md` (the contracts). Everything below is operational
knowledge that is *not* in those two documents — the things I had to learn the hard way.**

You are the chief of a release that is **built, independently evaluated twice, repaired,
and waiting on the operator**. You have not started work yet: there is no remaining unit
to dispatch. Your first job is not engineering.

---

## 1. Where the release stands

| | |
| --- | --- |
| Release tip | `3aa1772` on `release/v1-mvp`, pushed to `origin/release/v1-mvp` (same commit) |
| Base | `master` at `3cd05e8`, **frozen** for the whole build, matching `origin/master` |
| Units | 11 merged by the chief, each verified in a clean detached checkout before merge |
| Beads | 8 of 8 unit beads closed; round bead `chess-8el` still open; `chess-sco`, `chess-6b7`, `chess-kjk`, `chess-r0o` open |
| Suite at tip | **310 passed** (~175 s), `ruff check` clean, `ruff format --check` clean |
| Evaluation | round 1 (`2ae9820`) found F1/F2/F3; round 2 (`23066a7`) **accepted the repair, no new defects** |
| Reports | `docs/releases/v1-mvp-evaluation-round1.md`, `-round2.md`; also comments 70 and 89 on `chess-8el` |

Leftover state to clean when convenient (all disposable, none is evidence):
`~/.cache/chessleak/eval-*`, `verify-*` worktrees, and the `wk-repair` worktree and branch —
the merged evidence is in the commits and the bead comments, so removing them is safe.

---

## 2. What is waiting on the OPERATOR, not on you

Three items. **Do not close them, and do not substitute an agent run for any of them.**

1. **The uncoached walkthrough of `kijuu11`** (the operator's own chess.com account) from
   an empty cache. Brief real-journey check 3. Both evaluators said explicitly that no agent
   run substitutes for it. Suggested command, with the report left untracked:
   `chessleak analyze kijuu11 --out report.md --depth 12`
2. **Merge `release/v1-mvp` into `master` and tag `0.1.0`** — theirs alone. The brief gives
   the chief merge authority over the release branch only, and neither evaluator's
   disposition grants merge, tag or deployment authority. Hold the tag until after the
   walkthrough, so the tag means something.
3. **Three unruled questions**, all recorded on `chess-r0o`:
   - `chess-6b7` — the default `~/.cache/chessleak` is shared, so two concurrent
     *unconfigured* runs contend on one sqlite eval cache. Every agent run is pinned
     per-worktree; the operator's walkthrough is deliberately not, which is exactly why this
     is live now.
   - the **30 cp book band is knife-edge** under the repaired cache: a position that measured
     30 cp measures 31 cp and enters the report with worst class `ok`. The band is theirs.
   - `chess-kjk` — the cluster's `DEVIATION_WEIGHT` (0.05) was tuned against the old
     win-probability scale, not the ruled centipawn bands. Affects tie-breaks only.

---

## 3. Authority: where the product decisions live

The operator's rulings are **not** in the code. They are on the bead `chess-r0o` (comments
1, and the batch around 55–67 for 2026-10-01 and 2026-10-02), and they are folded into the
brief and record. If a document and a ruling disagree, **the ruling wins** and the document
is stale — that is a correction task, not a licence to re-decide.

Source hashes at the tip (a hash identifies a version; the operator decision gives authority):

    docs/PRD.md                     b7c3059771b198cd7d8af9529d0a2bc46afa46078fdfe7f5118ad506285b8c09
    docs/releases/v1-mvp.md         407cc9037400c99788f00b79779af806df287cc943227b2306244d99dda42d3c
    docs/releases/v1-mvp-design.md  8984db13b0f7b598966d8ac5122899c166e6594275900a8d2ed1f2882c19f3f4

Standing rulings, all 2026-10-01/02 unless noted: the agent model is Pi with
`stealth/space-bunny-alpha` at `xhigh` (no OpenAI, no Anthropic); severity is **centipawn
bands** 50/100/200 with win% as display only; a cluster's identity is the **position**, ECO
is a display label; `--max-games` and `--archive` are approved; the report shows **habits
only** (`occurrences >= 2`, ordered by occurrences then cost) because "one-time blunders are
not a learning opportunity"; version `0.1.0`; the operator's bashrc `HERDR_KEEP_CWD` guard
is ratified; **the product goal is that someone becomes a better chess player, not that they
get an interesting analysis** — test every change against that.

---

## 4. Host and harness knowledge (the expensive part)

### The tracker is `br`, and one mistake creates a second board

`bd` (Beads Go/Dolt) was migrated to `br` (Beads Rust) on 2026-10-01, precedent `alley-ot7`
in the Alleyoop tracker. Archive and restore instructions:
`~/dev-env/beads-archives/chess/README.md`.

- **Never run `bd` here.** It would create a second, divergent store.
- `br` reads **`BD_ACTOR`** (not `BR_ACTOR` or `BEADS_ACTOR`) — verified by claim probes.
- **`BEADS_DIR` must point at `/home/ddc/dev-env/chess/.beads`.** Without it, `br` inside a
  linked worktree *silently auto-creates its own empty store* there, and the worker's
  tracker writes vanish. This happened once during dispatch.
- Only the **chief** runs `br sync --flush-only`, and only when no other lane is live.

### The launcher is local, and this is deliberate

The framework's `../alleyoop/tools/launch.py` supports only Claude Code and Codex. This
release runs Pi through OpenRouter, so **`tools/pi_worker.py` in this repository** assembles
the same launch context and starts the agent through Herdr's `pi` kind. The framework package
was **not** modified, and should not be.

    python3 tools/pi_worker.py worker   --roster .git/alleyoop/roster.json \
        --bead ID [--bead ID ...] --worktree PATH --open-pane w3
    python3 tools/pi_worker.py evaluator --roster .git/alleyoop/roster.json \
        --repo PATH --candidate FULL_SHA --open-pane w3

The roster lives at `.git/alleyoop/roster.json` (untracked, durable pointer on `chess-r0o`).

### Herdr on this host: four things that will waste an hour if you don't know them

1. **Panes ignore `--cwd`** unless the pane carries `HERDR_KEEP_CWD=1`. `~/.bashrc` ends with
   a guarded `cd ~/dev-env` (ratified by the operator); the launcher sets the variable on the
   pane it creates. A pane without it lands in `~/dev-env` and the launch is refused.
2. **The quiet channel is one-way.** Worker → chief works (a worker message arrives in your
   pane). **Chief → worker does not**: `herdr agent prompt` returns `agent_not_ready` on a
   live Pi agent, and `herdr agent send-keys` accepts key names only, never text. To reach a
   worker, **comment on its primary bead**. Full note: `chess-r0o` comment 3 and its
   correction.
3. **Worker sessions die silently.** 4 of 11 dispatched sessions ended without delivering;
   three of them were *blocked on a subprocess read that never returned*, not crashed.
   Consequences: (a) tell workers to commit as they go — every fix that survived was
   committed; (b) when one dies, check for stranded processes before re-dispatching.
4. **`ps | grep 'pi --provider'` is not a reliable liveness check** — Pi does not keep that in
   its argv, and I mis-read a dead session as a live one because of it. **Use the pane's
   context counters and whether files are appearing**, and `herdr pane read <id>`.

### Stockfish and python-chess traps

- Shared read-only engine: `~/.local/share/chessleak/stockfish/stockfish` (Stockfish 19),
  installed by `scripts/get_stockfish.sh`. Safe to share; **caches are not** — one sqlite
  eval cache per worktree.
- **Never pass `game=<anything>` to `SimpleEngine.analyse`** — it blocks forever waiting for a
  game result, and that killed a session. Never abandon an `analysis()` generator either.
  `SimpleEngine` has no public `ucinewgame`; the fix is
  `engine.protocol.send_line("ucinewgame")`.
- Every test that opens an engine uses the `EngineService` context manager. Wrap any ad-hoc
  probe in `try/finally: engine.quit()`.
- Kill only your own processes, **by PID**. Never `pkill` a pattern on this host.

### `--archive` and the report, if you touch them

`--archive` takes a full URL or `YYYY/MM` (resolved against the account's own archives
index); an unpublished month exits 2. `--max-games` bounds analysis, **not** downloading.

---

## 5. How this release actually went, in numbers

- 11 worker sessions dispatched, 4 died without delivering, 1 needed a second session for a
  repair after the first died mid-unit.
- Cost: the canary alone burned ~4.5M tokens of context across two sessions at `xhigh`.
  Context compaction is aggressive; treat 98% context as normal, not as a warning.
- Measured engine cost: **0.303 s/position at depth 18, 0.076 s at depth 12**
  (`Threads=1`, `Hash=128`). A full month archive is ~24 minutes at depth 18.
- The product works on real data: on the operator's own account (`kijuu11`), 60 games →
  **6 habits ordered 29, 10, 3, 3, 2, 2 occurrences**. The premise holds.

---

## 6. How I ran reviews, and what to keep doing

1. **Never review in the worker's tree.** Clean detached worktree at the exact head, own
   venv, run the suite yourself.
2. **Hand-check the contract rows.** For every frozen rule in the record, one by-hand check
   (`to_my_pov(white -30, 'black') → +30`; `mate == 0` after a move means the *opponent* was
   mated). Reading code is not verification.
3. **Re-read every assertion a worker changed.** In this release the changes were: an old
   test that *encoded* the F1 bug (legitimate, verified), and three book fixtures that moved
   because the repaired engine changed one measurement from 30 cp to 31 cp (legitimate,
   with before/after numbers). Both would have looked like sabotage or noise without checking.
   **Disclose every loosened assertion in the merge commit and on the bead.**
4. **Do not patch a worker's product code.** Where a session died or a repair was one
   command (`ruff format`), finishing it myself was correct *only* because it was disclosed
   in the commit message and the bead. Twice the chief authored a commit; both say so.
5. **Verify the notes write before you write it.** `br update --notes "$(cat f)"` accepts an
   empty string without complaint and I blanked the release bead's state twice that way. Do:
   write the JSON, parse it, assert non-empty, *then* call `br update`.
6. When a document and a ruling disagree, fix the document in the same commit — the design
   record still described the terminal rule that F1 deleted until I noticed.

---

## 7. If you dispatch anything more

There is no v1 work left. The obvious next candidates, in the operator's own framing:

- **`chess-sco` (P2) — positional similarity.** The leading candidate for the release after
  `0.1.0`, and central rather than cosmetic: *"the goal is to use this information to become
  a better chess player… positional similarity will be very important if it's leading to
  similar inaccuracies."* Identity today is the exact position, so a habit played into
  transposed or mirrored positions is counted several times as `occurrences=1` and hidden by
  the habits rule — similarity would **raise** the habit count, never lower it, which is why
  every report carries the lower-bound sentence. Start with transposition and colour
  symmetry, not embeddings, and the result must be explainable in one line.
- Do **not** reopen: severity bands, cluster identity, habits-only ranking, `--max-games`,
  the version, or the cassette-privacy ruling (committed cassettes stay on non-personal
  accounts because `origin` is a **public** GitHub repository — `kijuu11`'s games must never
  be recorded into a committed cassette).

Concurrency cap on this host was **three workers** while another release's team was live;
check `uptime` before dispatching engine-heavy work, and each worker gets its own worktree,
branch, `.venv` and `CHESSLEAK_CACHE_DIR`.