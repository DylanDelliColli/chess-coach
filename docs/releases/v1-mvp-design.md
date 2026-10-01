# Design record: chessleak v1 MVP

- Release, release bead and brief revision: chessleak v1 MVP, `chess-r0o`, brief
  `docs/releases/v1-mvp.md` SHA-256
  `a47c72f24adba2f0a964c2ae8dc27878d107406f251372c93a2f452a5404645c`.
- Base commit the record describes: `3cd05e8` on `master` (bd→br migration); the
  release branch `release/v1-mvp` is cut from it, with PRD and brief at `bee8805`.
- **Depth: light.** No authentication, no data-schema migration of user data, and
  no contract we do not already own: the only external dependency is chess.com's
  public read API, whose shape the beads already fix. So: this record plus one fresh
  helper's second opinion (recorded under *Alternatives considered*), not a
  full-depth independent-design round.
- Status: **chosen**, 2026-10-01, before the first dispatch.

## Product fit

Serves PRD outcome "surface the player's most consequential recurring opening
mistakes", for a player who already has hundreds of recorded chess.com games and
reviews them one at a time. It must not become a whole-game analyzer, an opponent
analyzer, or a game browser: everything here is about *this* player's habitual
opening leaks, ranked.

What would make it wrong: ranking a single catastrophic blunder above a habit the
player repeats every game; showing a cluster the player never actually reached; or
reporting win-probability numbers that flip sign depending on the player's color.

Two questions remain with the operator (on `chess-r0o`): which real account
validates v1 end to end (PRD R4), and confirmation of the `1.0.0` version. Neither
changes the interfaces below.

## Fit with the existing system

The repository is empty apart from the tracker and docs: there is no existing code
to integrate with, so this release defines the layout rather than extending one.
`src/chessleak/` with `config.py`, `fetch.py`, `pgnio.py`, `engine.py`,
`severity.py`, `book.py`, `cluster.py`, `report.py`, `cli.py`; `tests/unit/`,
`tests/integration/`, `tests/fixtures/`; `scripts/get_stockfish.sh`. Nothing else
should re-implement PGN walking, FEN construction, UCI handshaking or win-probability
maths: those live in the modules below and are consumed, not re-derived.

**`config.py` is the one module every other unit imports.** It lands first (canary)
and its field names are frozen below; a worker that needs a new field proposes it
on the bead rather than editing the dataclass, so parallel units do not collide.

## Interfaces and contracts

Frozen before dispatch. Engine scores are **always white's point of view**,
whatever the side to move; conversion to the player's perspective happens in
`severity.py` and nowhere else. That single rule removes the sign bugs the epic
warns about.

| Contract | Module (owner) | Shape | Consumers |
| --- | --- | --- | --- |
| `Config` | `config.py` (U1) | dataclass: `username, stockfish_path, analysis_depth=18, opening_plies=15, cache_dir, win_prob_k=0.004, book_band_cp=30, top_n=20`; `Config.from_env()` reads `CHESSLEAK_*`, `expanduser` on paths | every unit, `cli.py` |
| `GameRecord` | `fetch.py` (U4) | `id, pgn, eco, white, black, result, time_control, my_color, end_time, white_rating, black_rating` | `pgnio.py`, `cli.py` |
| `PlyRecord` | `pgnio.py` (U3) | `game_id, ply_index, fen_before, move_uci, move_san, is_my_move, eco` | `severity.py`, `book.py`, `cluster.py` |
| `EvalResult` | `engine.py` (U2) | `cp: int\|None, mate: int\|None, best_move: str (UCI), depth: int`; `cp` and `mate` are mutually exclusive, `cp is None` when a mate score is returned | `severity.py`, `book.py` |
| `EngineService` | `engine.py` (U2) | context manager; `analyse(fen: str) -> EvalResult`; serialized engine access; persistent sqlite cache keyed `(fen, depth)` | `severity.py`, `book.py`, `cli.py` |
| `Severity` | `severity.py` (U5) | `cp_loss: int, winprob_drop: float, klass: str` where `klass ∈ {ok, inaccuracy, mistake, blunder}` | `cluster.py` |
| `DeviationFlag` | `book.py` (U5) | `game_id, ply_index, fen_before, my_move (SAN), best_move (SAN), cp_gap: int` | `cluster.py` |
| `Cluster` | `cluster.py` (U6) | `eco, fen_before, occurrences, my_moves: Counter, best_move, avg_winprob_drop, max_winprob_drop, deviation_count, composite_score` | `report.py`, `cli.py` |
| `render_report` | `report.py` (U7) | `render_report(clusters, top_n, out_path, summary) -> Path`; `summary` is a `dict[str, int\|float\|str]` carrying at least `username, games_analyzed, positions_evaluated, flagged_mistakes, cache_hit_rate` | `cli.py` |

Function-level decisions the beads leave open, settled here so parallel units agree:

- `cp_to_winprob(cp, k)` → `1/(1+exp(-k*cp))`; mates map to ±1.0; symmetric:
  `w(x) + w(-x) == 1`.
- `move_severity(eval_best, eval_after, my_color)` — both arguments are
  **white-POV** `EvalResult`s; the function negates when `my_color == "black"` and
  classifies by `winprob_drop` at thresholds 0.30 blunder, 0.15 mistake, 0.07
  inaccuracy.
- `first_deviation(ply_records, engine, band_cp)` — `engine` is duck-typed on
  `analyse(fen) -> EvalResult`, so the unit test's stub is legitimate and the
  integration test uses a real `EngineService`. SAN for both moves comes from the
  board, not from the PGN.
- `aggregate(scored_moves, deviations) -> list[Cluster]` where `scored_moves` is a
  sequence of `(PlyRecord, Severity)` pairs for the player's moves only, plus
  `rank_clusters(clusters) -> list[Cluster]` sorting by `composite_score` desc.
  `composite_score = occurrences * avg_winprob_drop + 0.05 * deviation_count`.
- `analyse` is called for **every** ply's `fen_before`, opponent plies included:
  the engine's best move is needed to judge the player's next move.
- Eval cache: sqlite at `<cache_dir>/evalcache.sqlite`, key `(fen, depth)`, written
  after each engine call. `cache_hit_rate` is a `cli.py` concern, not `engine.py`'s.

## Data and migration

No user-data schema and no migration. Two local caches, both per-worker by
convention (see *Host and resource limits*): chess.com archive JSON keyed by
archive URL, and the sqlite eval cache. Deleting either cache costs time, never
correctness.

## Host and resource limits

- **Python environment.** Each worktree gets its own virtualenv (`.venv`) from the
  host's Python 3.13 (the beads require 3.11+); `pip`'s cache is shared, so this
  costs seconds, not minutes. No global install.
- **Stockfish.** One shared, read-only binary under
  `~/.local/share/chessleak/stockfish/`, installed by `scripts/get_stockfish.sh`,
  which prints the resolved path. `Config.stockfish_path` resolves, in order:
  `CHESSLEAK_STOCKFISH_PATH`, that shared path, then `PATH`. Sharing a read-only
  binary is safe; sharing a writable cache is not, which is why caches are
  per-worktree.
- **CPU.** The engine is configured with `Threads=2` and `Hash=128` per process.
  Three workers each running their own engine must not oversubscribe the 24 threads
  the host shares with another release's team.
- **chess.com.** Descriptive `User-Agent` mandatory — without it the API returns
  **403** (verified 2026-10-01); with it, 200. Requests are serial.
- **Tracker.** `br`, with `BD_ACTOR` set per worker and `BEADS_DIR` pointed at the
  shared store. A worker that finds no `BEADS_DIR` will silently create its own
  empty store; the launch sets it, and the worker's first response must confirm it.

## Risks and unknowns

1. *Stockfish does not exist on this host.* No binary anywhere; apt and the official
   GitHub releases are both reachable, so U1 must install and prove one
   (`get_stockfish.sh`, then the mate-in-1 integration test). This is the release's
   single point of failure and the reason U1 is the canary.
2. *python-chess is not installed anywhere either.* Handled by per-worktree venvs.
3. *chess.com account choice for the live test.* An account with zero archives
   exists (a verified username returned `{"archives":[]}`); U4 must pick a small
   public account that actually has games and record the cassette.
4. *Sign conventions.* White-POV-only scores, pinned above; the integration tests
   for black-side play are the guard.
5. *SQLite eval cache contention.* One cache file per worker; concurrent writers to
   one file would produce `database is locked` failures under three engines.
6. *Depth of analysis.* `analysis_depth=18` over thousands of games is slow;
   opening-phase-only keeps it tractable, and the FEN cache makes repeat runs cheap.
   If the canary shows wall-clock problems, the fix is a documented depth default
   change, not silent per-unit overrides.

## Test strategy

- Unit: `tests/unit/` — pure logic (win-probability curve, thresholds, clustering,
  book deviation with a stubbed engine, config defaults and `CHESSLEAK_*`
  overrides, CLI flag parsing).
- Integration, real composition only: real Stockfish over UCI (mate-in-1, a real
  hanging-piece blunder classified `blunder`, deviation at a known ply, eval cache
  reused across two `EngineService` instances); real PGN parsing on a real multi-game
  chess.com export; real HTTP recorded once into `tests/fixtures/cassettes/` and
  replayed; real filesystem for report output; real sqlite on disk.
- The pipeline's proof is `tests/integration/test_cli_e2e.py`: cassette HTTP + real
  Stockfish + real fs, producing a report with at least one ranked cluster.
- Real-journey checks per the brief: layout-faithful replicas end to end before
  first readiness; one real input through the real processing and report; an
  uncoached operator walkthrough before acceptance (blocked on PRD R4).
- `pytest` collection and both suites run as the required checks on every unit.

## Decomposition

| Unit | Beads | Owns | Blocked by | Wave |
| --- | --- | --- | --- | --- |
| U1 (canary) | `chess-bb8` | `pyproject.toml`, package skeleton, `config.py`, `scripts/get_stockfish.sh`, pytest config, `tests/` layout | — | 0 |
| U2 | `chess-4uy` | `engine.py`, eval cache | U1 | 1 |
| U3 | `chess-xfs` | `pgnio.py` | U1 | 1 |
| U4 | `chess-3if` | `fetch.py`, archive cache, cassette | U1 | 1 |
| U5 | `chess-crg`, `chess-mn6` | `severity.py`, `book.py` | U2, U3 | 2 |
| U6 | `chess-usk` | `cluster.py` | U3, U5 | 3 |
| U7 | `chess-2m3` | `report.py` | U3 (PlyRecord/ECO only); may start in wave 3 alongside U6 because `Cluster` is frozen above | 3 |
| U8 | `chess-uow` | `cli.py`, end-to-end test | U2–U7 | 4 |

Wave 1 runs three workers at once (U2, U3, U4) — the host's ceiling while another
release's team is active. Wave 3 runs two (U6, U7). U5 is one worker with two beads:
they share the per-move evaluation path and ship as a single review.

**Canary: U1.** It proves the premise — a real engine on this host, a real venv,
a real test run — before three workers commit to a design that assumes it. Its
findings revise this record and the undispatched beads before wave 1.

## Alternatives considered

Second opinion from a fresh helper (same model and effort as the workers, no
knowledge of this record's reasoning) is recorded here when it lands; its findings
and what changed as a result are appended to this section before the canary merges.

The one alternative design worth naming: have `cli.py` own severity and perspective
conversion, leaving `severity.py` a pure function of already-converted numbers. It
was rejected because three units would then each need to know the sign rule, and
the black-side bug it invites is exactly the failure the PRD calls out.

## Rulings needed

1. Which real account validates v1 end to end (PRD R4). Recommended default: the
   operator names their own account for the uncoached walkthrough; a worker records
   a small public account's cassette for CI. Blocking nothing until first readiness.
2. Tag version `1.0.0` at acceptance. Recommended default: `1.0.0`, the first
   operator-visible release. Non-blocking.