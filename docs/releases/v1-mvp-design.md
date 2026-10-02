# Design record: chessleak v1 MVP

- Release, release bead and brief revision: chessleak v1 MVP, `chess-r0o`, brief
  `docs/releases/v1-mvp.md` SHA-256
  `c84e58d6e05b13679cf432b66b269e1a6a2e5e25cf2e7b2bbcd08ee694605915` (revision 2,
  2026-10-01). Revision 1 of this record cited `a47c72f2...`, the brief hash before
  its editorial unit-count correction; no product commitment changed in that edit.
- Base commit the record describes: `3cd05e8` on `master` (bd→br migration); the
  release branch `release/v1-mvp` carries the PRD and brief at `bee8805` and this
  record's first revision at `29a5fb5`.
- **Depth: light.** No authentication, no data-schema migration of user data, and no
  contract we do not already own: the only external dependency is chess.com's public
  read API. So: this record plus one fresh helper's second opinion.
- Status: **revised**, 2026-10-01, after that helper's adversarial review and before
  the first wave. Revision 1 (`29a5fb5`) was the record the canary started against;
  the canary's own findings are appended below when it reports.

## Product fit

**The product goal, stated by the operator on 2026-10-02, is that someone becomes a better
chess player — not that they get an interesting analysis of their games.** Every future
change is measured against that: a feature that describes their games without helping them
improve is out of scope. It is why the report shows habits only (a repeated position is a
habit, and a habit can be changed; a one-time blunder is a fact about one game), and why
positional similarity — the mechanism that detects "you do this every time" when the
repetition is spread across equivalent positions — is the leading candidate for the release
after `0.1.0` (`chess-sco`), not a cosmetic clustering improvement.

Serves PRD outcome "surface the player's most consequential recurring opening
mistakes", for a player who already has hundreds of recorded chess.com games and
reviews them one at a time. It must not become a whole-game analyzer, an opponent
analyzer, or a game browser: everything here is about *this* player's habitual
opening leaks, ranked.

What would make it wrong: ranking a single catastrophic blunder above a habit the
player repeats every game; showing a cluster the player never actually reached; or
reporting win-probability numbers that flip sign depending on the player's color.

Questions still with the operator (on `chess-r0o`): which real account validates v1
end to end (PRD R4), the tag version, the severity banding question (Q3 below), the
cluster-identity reading of PRD decision 1 (Q4), and the new `--max-games` surface
(Q5). None of them changes the interfaces frozen here except where noted.

## Fit with the existing system

The repository is empty apart from the tracker and docs: there is no existing code to
integrate with, so this release defines the layout rather than extending one.
`src/chessleak/` with `config.py`, `fetch.py`, `pgnio.py`, `engine.py`, `severity.py`,
`book.py`, `cluster.py`, `report.py`, `cli.py`; `tests/unit/`, `tests/integration/`,
`tests/fixtures/`; `scripts/get_stockfish.sh`. Nothing else should re-implement PGN
walking, FEN construction, position identity, UCI handshaking or win-probability
maths: those live in the modules below and are consumed, not re-derived.

**`config.py` is the one module every other unit imports.** It lands first (canary)
and its field names are frozen below. It also carries one shared function,
`position_key()` (see *Interfaces*), because it is the single identity function every
unit needs and the canary is the one unit that lands before anybody can import
anything. A worker that needs a new `Config` field proposes it on the bead rather
than editing the dataclass; the chief folds amendments into `config.py` at wave
boundaries so parallel units never collide on it.

## Interfaces and contracts

Frozen before wave 1. Engine scores are **always white's point of view**, whatever
the side to move; conversion to the player's perspective happens in exactly one
shared helper, `severity.to_my_pov()`, which `book.py` may also import. That single
rule removes the sign bugs the PRD names.

python-chess's default `info["score"]` is *side-to-move* POV, so `engine.py` must
read `info["score"].white()` explicitly. Reading `.relative` instead sign-flips every
black-to-move score — silently, and in exactly the direction the PRD calls out.

| Contract | Module (owner) | Shape | Consumers |
| --- | --- | --- | --- |
| `Config` | `config.py` (U1) | see *Config* below | every unit, `cli.py` |
| `position_key(fen)` | `config.py` (U1) | `" ".join(fen.split()[:4])` — piece placement, side, castling, ep. Not the halfmove clock or fullmove number | `pgnio.py`, `engine.py`, `cluster.py` |
| `GameRecord` | `fetch.py` (U4) | `id, pgn, eco, white, black, result, white_result, black_result, time_control, my_color, end_time, white_rating, black_rating, rules: str, initial_setup: str` | `pgnio.py`, `cli.py` |
| `download_all(username, cache_dir)` | `fetch.py` (U4) | `list[GameRecord]`; caches the archives **index** by username as well as each monthly archive by URL, so a second run makes no HTTP request at all (O1) | `cli.py` |
| `PlyRecord` | `pgnio.py` (U3) | `game_id, ply_index, fen_before, fen_after, move_uci, move_san, is_my_move, eco: str \| None` | `severity.py`, `book.py`, `cluster.py` |
| `extract_opening_plies(game_record, max_plies)` | `pgnio.py` (U3) | `list[PlyRecord]` | `severity.py`, `book.py`, `cli.py` |
| `EvalResult` | `engine.py` (U2) | `cp: int \| None, mate: int \| None, best_move: str \| None (UCI), depth: int`; `cp` and `mate` are mutually exclusive; `best_move` is `None` on a terminal position | `severity.py`, `book.py` |
| `EngineService` | `engine.py` (U2) | `EngineService(stockfish_path, depth, cache_path, *, options: dict[str,str] \| None = None)`; context manager; `analyse(fen) -> EvalResult`; serialized engine access; counters `hits: int` and `misses: int`; sqlite cache at `cache_path` keyed `(position_key(fen), depth)` | `severity.py`, `book.py`, `cli.py` |
| `cp_to_winprob(cp, k)` | `severity.py` (U5) | `1/(1+exp(-k*cp))`, cp only; mate mapping lives in `move_severity` | `report.py` (display) |
| `to_my_pov(eval, my_color)` | `severity.py` (U5) | `EvalResult` converted to the player's perspective | `book.py` |
| `move_severity(eval_best, eval_after, my_color)` | `severity.py` (U5) | `Severity`; both arguments white-POV; classified in **centipawn** bands (operator, 2026-10-02), with `winprob_drop` shown for display only; a terminal `eval_after` short-circuits to `winprob_drop = 1.0` and `blunder` without needing a best move; a mate that appears or disappears across the move is a `blunder` whatever the centipawn figure reads | `cluster.py` |
| `Severity` | `severity.py` (U5) | `cp_loss: int, winprob_drop: float, klass: str` where `klass ∈ {ok, inaccuracy, mistake, blunder}`, decided by `cp_loss` alone against the operator's bands (< 50 / 50-100 / 100-200 / ≥ 200) | `cluster.py` |
| `DeviationFlag` | `book.py` (U5) | `game_id, ply_index, fen_before, my_move: str (SAN), best_move: str (SAN), cp_gap: int` with `cp_gap >= 0` meaning "worse for the player" | `cluster.py` |
| `first_deviation(ply_records, engine, band_cp)` | `book.py` (U5) | called **once per game** with that game's window; `engine` is duck-typed on `analyse(fen) -> EvalResult`, so the unit test's stub is legitimate | `cli.py` |
| `Cluster` | `cluster.py` (U6) | `eco: str \| None, fen_before, occurrences, my_moves: collections.Counter[str] (SAN), best_move: str (SAN), avg_winprob_drop, max_winprob_drop, deviation_count, worst_klass: str, composite_score: float` | `report.py`, `cli.py` |
| `aggregate` / `rank_clusters` / `rank_habits` | `cluster.py` (U6) | `aggregate(scored_moves, deviations, best_moves) -> list[Cluster]` (unsorted), `rank_clusters(clusters) -> list[Cluster]` (composite desc), `rank_habits(clusters) -> list[Cluster]` (habits only: `occurrences >= 2`, occurrences desc then composite desc) | `report.py`, `cli.py` |
| `render_report` | `report.py` (U7) | `render_report(clusters, top_n, out_path, summary) -> Path`; re-sorts defensively so unsorted input cannot produce wrong ranks; renders habits only, so `top_n` caps the habit list | `cli.py` |
| `analyze` / `main` | `cli.py` (U8) | positional `<username>` is canonical (PRD), `--username` an alias, plus `--max-games` | operator |

Decisions the beads left open, settled here:

- **Position identity.** `board.fen()` includes the halfmove clock and fullmove
  number, so the same board reached by transposition at a different move number is a
  different string. Measured on one real month archive: 4,738 distinct full FENs vs
  4,634 position keys — 104 engine analyses and 104 recurrences lost to that alone.
  Both the cluster key and the eval-cache key use `position_key()`. Full FEN is kept
  for display only. `board.fen()`'s default `en_passant="legal"` normalisation is part
  of the key: a hand-written fixture key with a different ep spelling never matches.
- **Cluster identity is the position, not the ECO.** The helper measured that 321 of
  811 recurring positions in one real month carry more than one game-level ECO tag, so
  keying on `(eco, fen)` fragments 40% of recurrences into `occurrences=1` clusters
  that vanish from a frequency ranking. Clusters key on `position_key(fen_before)`;
  `eco` is a display label, the most frequent tag among contributing games, `None`
  when absent. This is the operator's PRD decision 1 read as layered bucketing rather
  than a compound key; **Q4** asks the operator to confirm the reading.
- **`eco` is optional in real data.** ~12% of games in a real month carry no ECO in
  either the archive or the PGN tag. Precedence: the PGN `[ECO]` tag wins over the
  archive `eco` URL; `None` renders as `—` in the report.
- **Only mistakes are aggregated.** `aggregate` admits a player's move only when
  `klass != "ok"` or a `DeviationFlag` exists at that `(game_id, ply_index)`.
  `occurrences` counts admitted moves, so correct play never occupies the ranking.
- **A mate that appears or disappears is a blunder, whatever the centipawns read**
  (`chess-k1s`). The ruled classification is in centipawns, and a mate score
  carries no centipawn value, so the bands alone cannot express the largest error
  in a game: a move that walks away from a proved mate, or walks into one, measures
  `cp_loss = 0` and would come out `ok`. Measured on the real engine it is 0 cp
  against 0.474 of win probability. So `move_severity` short-circuits, beside the
  terminal one above it: a mate appearing or disappearing across the move is a
  `blunder`, with the distance read in neither direction - a player who mates in
  four after a move that mated in three has kept the win, and one already being
  mated in two has lost nothing the move cost. The win-probability drop is still
  the ordinary computed figure there, which is what the report shows.
- **The report shows habits only** (`chess-iql`, operator ruling 2026-10-02): a
  position reached **once** is not rendered at all - "for now, focus only on
  habits", because a one-time blunder is not a learning opportunity however bad it
  is - and what remains is ordered by `occurrences` descending, then by composite
  descending. `top_n` caps the habit list and the page is never padded with the
  clusters left out. Measured on the committed 85-game cassette at the e2e test's
  30-game bound (`chess-r0o`): 82 clusters, of which one recurs, and under the
  composite order that habit ranked fourth, behind positions reached once - 19 of
  the top 20 entries were one-offs. `summary` therefore carries
  `one_off_positions_omitted` (`cluster.py` `rank_habits`, `report.py` header).
- **The habit list is a lower bound**, and the header says so: cluster identity is
  `position_key`, so a position reached twice by transposition, or once per side of
  a mirrored board, is two clusters rather than one. Positional similarity
  (deferred on `chess-sco`) can only raise these counts, so the sentence may not be
  dropped while that bead is open.
- **`best_move` reaches the report through a mapping.** `PlyRecord` and `Severity`
  carry no engine move, so `aggregate` takes
  `best_moves: Mapping[tuple[str, int], str]` keyed `(game_id, ply_index)` in SAN,
  produced by U5 where the board is already in hand.
- **Composite.** `composite_score = occurrences * (avg_winprob_drop + 0.05 * deviation_rate)`
  with `deviation_rate = deviation_count / occurrences`. The review showed a flat
  `+0.05 * deviation_count` bonus swings its effective weight ~20× with cluster size.
  The 0.05 weight is to be re-derived once **Q3** settles the severity scale.
- **Non-standard games are skipped, visibly.** `rules != "chess"` or a non-standard
  `initial_setup` can never recur, so each would inject a one-off cluster. They are
  skipped and counted in `summary.games_skipped`, which the report header prints.
  Measured share in one real month: 65 of 548 games.
- **`result`.** Keep chess.com's per-colour `white_result`/`black_result` strings
  verbatim (`win`, `resigned`, `timeout`, `repetition`, `checkmated`, …); `result` is
  the PGN-style `1-0` / `0-1` / `1/2-1/2` summary the bead asks for.
- **`summary` fields**, computed in `cli.py` and rendered by `report.py`:
  `games_analyzed` (games successfully parsed), `games_skipped`, `positions_evaluated`
  (distinct position keys analysed), `flagged_mistakes` (admitted moves whose
  `worst_klass` is `mistake` or `blunder`, or that carry a deviation),
  `one_off_positions_omitted` (clusters the run produced that `rank_habits`
  withheld, added by `chess-iql` with the habits-only ruling) and `cache_hit_rate`
  (`hits / (hits + misses)`).
- **One engine per run.** `cli.py` opens exactly one `EngineService` for the whole run
  and reuses it, so the FEN cache is shared across games.
- **Exit codes.** 0 success, 1 runtime failure, 2 usage error.

### Config

```python
@dataclass Config:
    username: str = ""
    stockfish_path: str = ""        # default_factory: CHESSLEAK_STOCKFISH_PATH,
                                    # else ~/.local/share/chessleak/stockfish/stockfish,
                                    # else "stockfish" on PATH
    analysis_depth: int = 18
    opening_plies: int = 15
    cache_dir: str = "~/.cache/chessleak"
    win_prob_k: float = 0.004
    book_band_cp: int = 30
    top_n: int = 20
```

`Config()` must work with no arguments, because `chess-bb8`'s `test_config_defaults`
asserts the documented defaults; the bead declared `username`/`stockfish_path`
without defaults. `Config.from_env()` reads `CHESSLEAK_USERNAME`,
`CHESSLEAK_STOCKFISH_PATH`, `CHESSLEAK_ANALYSIS_DEPTH`, `CHESSLEAK_OPENING_PLIES`,
`CHESSLEAK_CACHE_DIR`, `CHESSLEAK_WIN_PROB_K`, `CHESSLEAK_BOOK_BAND_CP`,
`CHESSLEAK_TOP_N`, and `expanduser`s paths. The bead's test is written against
`CHESSLEAK_DEPTH`; the canonical name is `CHESSLEAK_ANALYSIS_DEPTH` and
`CHESSLEAK_DEPTH` is accepted as an alias so the named test holds.

## Data and migration

No user-data schema and no migration. Two local caches, both per-worker by convention
(see *Host and resource limits*): the chess.com archives **index** and monthly
archives under `<cache_dir>`, and the sqlite eval cache. Deleting either costs time,
never correctness.

## Host and resource limits

- **Python environment.** Each worktree gets its own virtualenv (`.venv`) from the
  host's Python 3.13 (the beads require 3.11+); pip's cache is shared, so this costs
  seconds. No global install.
- **Stockfish.** One shared, read-only binary under
  `~/.local/share/chessleak/stockfish/`, installed by `scripts/get_stockfish.sh`,
  which prints the resolved path. A read-only binary is safe to share; a writable
  cache is not, which is why caches are per-worktree.
- **CPU.** `EngineService` defaults to `{"Threads": "2", "Hash": "128"}`. Three
  workers each running an engine must not oversubscribe the 24 threads this host
  shares with another release's team.
- **chess.com.** A descriptive `User-Agent` is mandatory — without one the API returns
  **403** (verified 2026-10-01); with one, 200. Requests stay serial.
- **Network determinism.** The default test mode replays cassettes with
  `record_mode="none"`; live recording is gated behind `CHESSLEAK_LIVE=1`. The required
  per-unit check must therefore never touch the network by default.
- **Remote, added mid-release.** `origin` was established by the operator on
  2026-10-01, after U1–U4 had merged locally. Nothing about a unit's contract or test
  strategy changes; the chief pushes `release/v1-mvp` after each merge so the work is
  not stranded on one machine, and the operator alone merges `master` and tags.
- **The quiet channel is bead comments, not Herdr.** `herdr agent prompt` rejects Pi
  agents on this host (Herdr reports no session id for the Pi kind) and `send-keys`
  takes key names only, so neither side can push a message. Workers record done,
  blocked-on-authority and unresolved-conflict signals on their own bead plus one line
  on `chess-r0o`; the chief writes to a worker by commenting on its primary bead and
  pulls state at wave boundaries. Recorded on `chess-r0o` comment 3.
- **Tracker.** `br`, with `BD_ACTOR` per worker and `BEADS_DIR` pointed at the shared
  store. (`BD_ACTOR` is the variable name br reads — verified by claim probes on
  2026-10-01 — despite the `bd` lineage of the name.) A worker that finds no
  `BEADS_DIR` silently creates a second, empty store: this happened once during the
  canary launch and is why `tools/pi_worker.py --open-pane` sets it on the pane.

## Risks and unknowns

1. *Stockfish does not exist on this host.* No binary anywhere; apt and the official
   GitHub releases are both reachable, so U1 must install and prove one. This is the
   release's single point of failure and the reason U1 is the canary.
2. *python-chess is not installed anywhere either.* Handled by per-worktree venvs.
3. *Which account becomes the cassette.* U4 selects a public account with at least 50
   games in a single month and publishes the username, archive URL and recording date
   on its bead; U8's e2e test asserts the cassette exists, is non-empty, and that its
   username matches the one the test uses. `chessbumper` (one archive, seven games,
   verified live 2026-10-01) is the known-good fallback for the live-fetch test, but
   is too thin for a recurrence assertion.
4. *Depth-18 wall clock.* One account has 153 monthly archives and a single month is
   ~8,200 (game, ply) pairs over ~4,700 distinct position keys, each needing depth 18
   at `Threads=2`. The e2e test therefore bounds itself with `--max-games 30` and
   `--depth 12` (budget: under five minutes); depth 18 stays the real-journey setting.
   The canary's measured per-position cost goes here when it reports.
5. *Sign conventions.* White-POV-only scores plus `to_my_pov`; the black-to-move
   integration test is the guard, and the review showed the existing mate-in-1
   assertion (`mate == 1`) passes under either convention when the fixture is
   white-to-move, so the test must also cover black.
6. *SQLite eval cache contention.* One cache file per worker; concurrent writers to
   one file would produce `database is locked` failures under three engines.
7. *The severity scale may not match the operator's expectations.* See **Q3**.

## Test strategy

- Unit: `tests/unit/` — pure logic (win-probability curve, thresholds, clustering,
  book deviation with a stubbed engine, config defaults and `CHESSLEAK_*` overrides,
  CLI flag parsing). `tests/unit/test_report.py` must import and construct the **real**
  `chessleak.cluster.Cluster`, including a real `collections.Counter`, so a look-alike
  dataclass cannot pass before U6 lands.
- Integration, real composition only: real Stockfish over UCI (mate-in-1 **from both
  sides**, a real hanging-piece blunder classified `blunder`, deviation at a known
  ply, eval cache reused across two `EngineService` instances); real PGN parsing on a
  real multi-game chess.com export; real HTTP recorded once into
  `tests/fixtures/cassettes/` and replayed by default; real filesystem for report
  output; real sqlite on disk.
- The two seam tests the beads name and the first revision of this record omitted:
  `tests/integration/test_cluster_pipeline.py::test_real_extract_to_cluster` and
  `tests/integration/test_report_e2e_fragment.py::test_report_from_real_clusters`.
- The pipeline's proof is `tests/integration/test_cli_e2e.py`: cassette HTTP + real
  Stockfish + real fs, asserting a report with **at least one cluster whose
  `avg_winprob_drop > 0` or `deviation_count > 0`** (not merely `occurrences >= 1`, which
  a no-op severity path satisfies), a non-zero win%-lost figure in the body, a real
  position and ECO, the cassette present and non-empty, and `EngineService.hits > 0`
  after a second run.
- A position-identity assertion: two games reaching the same position by transposition
  yield one cluster and one cache hit under the `position_key` key.
- Fixtures are owned: U3 owns `game_sample.pgn` and `games_multi.pgn` (the latter
  extracted from the real archive U4 records); U4 owns `archive_sample.json` (a
  layout-faithful replica, for unit tests only) and the cassette (the real input). The
  brief's line stands: replicas are for unit tests, the cassette is the real thing.
- Real-journey checks per the brief: layout-faithful replicas end to end before first
  readiness; one real input through the real processing and report; an uncoached
  operator walkthrough before acceptance (blocked on PRD R4).
- `pytest` collection and both suites are the required checks on every unit.

## Decomposition

| Unit | Beads | Owns | Blocked by (tracker) | Wave |
| --- | --- | --- | --- | --- |
| U1 (canary) | `chess-bb8` | `pyproject.toml`, package skeleton, `config.py` incl. `position_key`, `scripts/get_stockfish.sh`, pytest config, `tests/` layout | — | 0 |
| U2 | `chess-4uy` | `engine.py`, eval cache | U1 | 1 |
| U3 | `chess-xfs` | `pgnio.py`, the two PGN fixtures | U1 | 1 |
| U4 | `chess-3if` | `fetch.py`, archive + index cache, `archive_sample.json`, the cassette | U1 | 1 |
| U5 | `chess-crg`, `chess-mn6` | `severity.py`, `book.py` | U2, U3 | 2 |
| U6 | `chess-usk` | `cluster.py` | U3, U5 | 3 |
| U7 | `chess-2m3` | `report.py` | U6 | 4 |
| U8 | `chess-uow` | `cli.py`, end-to-end test | U2–U7 | 5 |

Eight units over six waves. Wave 1 runs three workers at once — the host's ceiling
while another release's team is active. Wave 3's U7 **follows** U6: the operator's
tracker has `chess-2m3` blocked by `chess-usk`, and this revision no longer claims the
two can run in parallel. If the operator approves dropping that blocker — the
`Cluster` shape is frozen here, so the report seam is real but narrow — U7 moves into
wave 3 and the release shortens by one wave. U5 is one worker with two beads: they
share the per-move evaluation path and ship as a single review.

**Canary: U1.** It proves the premise — a real engine on this host, a real venv, a real
test run — before three workers commit to a design that assumes it. Its findings
revise this record and the undispatched beads before wave 1.

## Canary findings (U1, `chess-bb8`, merged `f15830c`)

Folded after the canary merged, before wave 1, as the framework requires.

1. **The premise held, and it was the right canary.** No engine existed anywhere on
   this host. `Stockfish 19` is now installed at `~/.local/share/chessleak/stockfish/`
   from the official `sf_19` linux-x86-64-universal asset; `scripts/get_stockfish.sh`
   prints the apt route (`stockfish 16`) as a fallback. A from-scratch `.venv` takes
   8.6 s with pip's cache shared, so the per-worktree environment is cheap.
2. **The white-POV rule is a real trap, now measured.** python-chess >= 1.10 returns a
   side-to-move `PovScore`; on a black-to-move board, `score.relative` is `+30` where
   `score.white()` is `-30`. It only looks correct on a white-to-move fixture, which is
   why the beads' `mate == 1` assertion passes under either convention. `engine.py` must
   read `info["score"].white()`. Binding on U2 and U5.
3. **A worker branched before the record's revision, and lost an item.** This unit's
   branch predated revision 2, and one of the four amendment items was missed
   (`position_key`). Chief amendments travel as bead comments and are read whenever the
   worker next reads its bead — not continuously. Wave-1 dispatches start from the
   current release tip so this costs nothing, but the lesson stands: a running worker
   cannot be interrupted, so amendments must be additive and self-contained.
4. **Cost.** The canary unit took two sessions and roughly 4.5M tokens of context on
   `stealth/space-bunny-alpha` at `xhigh` for a scaffold. Measured, not estimated; the
   retrospective compares this with the other units' cost before drawing conclusions.
5. **Additions the canary made beyond its bead**, both accepted: `scripts/setup_env.sh`
   (per-worktree venv + editable install in one command) and keeping the literal `~` in
   `Config.cache_dir`'s default, expanded by `cache_path` and `from_env`.

## Unit findings (folded at each wave boundary)

### U2 `chess-4uy`, merged `647123e`

- **Per-position cost, measured on this host** (Stockfish 19, `Threads=2`, `Hash=128`,
  55 real opening positions, fresh cache): depth 18 mean **0.303 s**, median 0.256 s,
  max 1.205 s; depth 12 mean **0.076 s**, median 0.024 s. Risk 4's estimate is
  therefore confirmed: one month archive (~4,700 distinct position keys) is roughly
  **24 minutes at depth 18**, and U8's `--max-games 30 --depth 12` budget sits well
  inside five minutes. Within a single game transposition reuse is modest (52 distinct
  positions, 3 hits across four 15-ply windows); the win comes across games.
- **python-chess 1.11.2 score API, binding on U5.** `chess.engine.Score` is an abstract
  base class: `Score(cp=30, mate=None)` raises `TypeError`. The concrete values are
  `Cp`, `Mate` and the `MateGiven` singleton, and `PovScore` has no `.score()` or
  `.mate()` of its own. U5's `book.py` stub engine must build `PovScore(Cp(x),
  board.turn)` and read `score.white()`, or its unit test does not exercise the sign
  rule at all.
- **Terminal positions are answered by the board, not the engine**: checkmate is
  `mate=0, cp=None`; stalemate, insufficient material and the automatic draw rules are
  `cp=0, mate=None`; claim-based endings are deliberately not terminal. `best_move` is
  `None` throughout. `severity.move_severity` may detect a terminal evaluation from
  either `mate == 0` or `best_move is None`.
- **Cache invalidation on an engine change is not modelled**: the key is exactly
  `(position_key, depth)` as this record freezes, so a different Stockfish build at the
  same depth keeps serving old rows. Left as specified and flagged; a future revision
  could add an engine-version column.

### U3 `chess-xfs`, merged `20fd88e`

- **`read_game` does not raise on a bad move**: python-chess collects into
  `Game.errors` and stops there. A caller that forgets to check `errors` analyses a
  corrupt export as a shorter game. `cli.py` must check it.
- **ECO labels can be chess.com opening URLs.** Precedence is the frozen one (PGN
  `[ECO]` tag, then the archive value, then `None`), so a cluster whose contributing
  games are mixed can carry a full URL as its most frequent label. Raised as
  `chess-egx` (P3): U6 picks the label, U7 renders it, and it must be decided before
  the report's ranked table exists.
- `PlyRecord.game_id` is a `str` even when the archive id is an integer, so
  `cluster.py`'s `(game_id, ply_index)` key is stable.
- The `config.py` docstring listed `pgnio.py` as a `position_key` consumer; it is not,
  and the docstring now says so (chief, wave boundary).

## Alternatives considered

### The fresh helper's second opinion (light-depth requirement)

Run 2026-10-01 on Pi with `stealth/space-bunny-alpha` at `xhigh` effort, per brief R5,
with no knowledge of this record's reasoning. It read the PRD, the brief, this record,
all nine beads and the tracker graph, and validated several claims against live data
(python-chess 1.11.2 source; one real chess.com month archive: 548 games). It returned
three blockers, fourteen majors and a set of minors. Verified clean: the brief hash in
this record matches the file and the hash on `chess-r0o`; the base-commit and
`bee8805` claims match the actual Git graph.

Accepted and folded into this revision: the `Cluster.best_move` source
(`best_moves` mapping); position identity (`position_key`) for both the cluster key and
the eval cache; cluster identity by position with ECO demoted to a label;
optional ECO with pinned precedence; cache-hit counters; the missing constructors and
the `options` parameter; `fen_after` on `PlyRecord`; single ownership of sorting;
the full `CHESSLEAK_*` table with the `CHESSLEAK_DEPTH` alias; `Config()` defaults;
variant and initial-setup filtering with visible skip counts; per-colour results; SAN
keying; per-game `first_deviation`; defined `summary` fields; terminal positions with
`best_move: str | None`; the deviation-rate composite; explicit white-POV reading plus
a black-side integration test; the shared `to_my_pov` helper; both seam tests; the
tighter e2e assertions; the cassette account policy and the `CHESSLEAK_LIVE` gate;
fixture ownership; the bounded cassette; the corrected unit and wave counts.

Raised to the operator rather than decided here: **Q3** the severity banding (with
`win_prob_k = 0.004` and the bead's 0.07/0.15/0.30 thresholds, "blunder" needs roughly
a 3.5-pawn loss, so a 100 cp error classifies `inaccuracy` — against the conventional
50/100/200 cp bands any chess player recognises), **Q4** the cluster-identity reading
of PRD decision 1, and **Q5** the new `--max-games` CLI surface.

Deferred to the canary: its measured per-position analysis cost for Risk 4, and
whether `scripts/get_stockfish.sh` resolves to an apt package or the official release
binary.

### The one alternative design worth naming

Have `cli.py` own severity and perspective conversion, leaving `severity.py` a pure
function of already-converted numbers. Rejected: three units would each need to know
the sign rule, and the black-side bug it invites is exactly the failure the PRD names.

## Rulings needed

**All six are now ruled on by the operator (2026-10-02); see the release bead.**

1. **Q3 — severity banding: RULED.** Classify in centipawns — `ok < 50`,
   `inaccuracy 50–100`, `mistake 100–200`, `blunder ≥ 200` — and show win-probability
   loss as a display figure. This supersedes the operator's original 2026-06-05
   win-probability thresholds (0.07/0.15/0.30 at `k = 0.004`), which meant roughly
   70/155/347 cp. Implemented as `chess-k1s`; `win_prob_k` stays, for display only.
2. **Q4 — cluster identity: CONFIRMED.** The position is the cluster's identity; ECO is
   its most frequent display label. No change.
3. **Q5 — `--max-games`: APPROVED.** Default unlimited.
4. **Validation account: `kijuu11`**, the operator's own, for the uncoached walkthrough
   and the live end-to-end run. Committed cassettes stay on non-personal accounts,
   because this repository's remote is public.
5. **Tag version: `0.1.0`**, not `1.0.0`. `src/chessleak/__init__.py` must agree.
6. **Q6 — what the report is about: habits only.** "For now, focus only on habits"
   (verbatim, 2026-10-02). The report contains only positions reached more than
   once, ordered by occurrences descending and then by composite descending;
   one-occurrence clusters are withheld, counted in the header, and the header
   states that the list is a lower bound. Implemented as `chess-iql`, which also
   added `summary.one_off_positions_omitted` above.