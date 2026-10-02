# PRD — chessleak: opening-phase recurring-mistake analyzer

Authority: operator. Transcribed from the operator's own epic bead `chess-r0o`
(created 2026-06-05, design decisions locked the same day), with the operator's
2026-10-01 answers to the chief's release questions added as **R1**–**R5**. Nothing
here is an agent addition; where engineering needs a decision this document does
not settle, it is an open question for the operator, not a default.

## Problem

A chess.com player has thousands of recorded games. Their opening play repeats, and
so do their opening mistakes. A single blunder is noise; the same bad move in the
same opening, game after game, is a habit worth fixing. Existing game review shows
one game at a time and never says "you do this every time".

## Goal

Export a player's full game history and surface their most consequential,
**recurring** mistakes in frequently-occurring opening positions.

## v1 scope

**Opening phase only** (first ~15 plies). Whole-game analysis is a later epic
(`chess-r0o` child epic, not in v1).

Stack: Python 3.11+, `python-chess`, Stockfish over UCI via
`chess.engine.SimpleEngine`.

## Locked design decisions (operator, 2026-06-05)

1. **Clustering is layered**: bucket by ECO opening code *and* cluster by exact
   board FEN through the opening phase. Opening FENs genuinely recur across games,
   so identical-FEN aggregation works here.
2. **Severity is two-layered**:
   - *Primary*: win-probability-weighted drop. Centipawns → win probability via a
     logistic curve; weight by how much the player's winning chances fell.
   - *Secondary*: an early-game book-deviation trigger. A move that leaves
     engine-best/book in the opening is flagged even when the win% drop is modest,
     because recurring small deviations are habitual leaks worth surfacing.
3. **Cluster ranking is frequency × average severity**, so habitual leaks outrank
   one-off disasters.

## Pipeline

fetch + cache → opening-phase extract → Stockfish evaluation (FEN-cached) →
severity + book deviation → cluster/aggregate → ranked markdown report → CLI
orchestration.

## v1 acceptance criterion (operator)

`chessleak analyze <username>` produces a ranked markdown report of the player's
most consequential **recurring** opening mistakes — win-probability-weighted plus
early-game book-deviation flags — clustered by ECO + exact FEN, validated end to
end against a real account with real Stockfish.

## Test doctrine (operator, from the epic and the host baseline)

Every child module ships unit *and* integration tests. Integration tests exercise
real composition — a real Stockfish process, real HTTP (recorded), a real
filesystem — and **never mock** the engine, the transport or the disk in the
assertion path.

## Operator answers, 2026-10-01 (R1–R5)

- **R1 — product sources.** The epic `chess-r0o` is the PRD; this file is its
  transcription, and `docs/releases/v1-mvp.md` is the release brief derived from
  it. Operator approved the chief's proposed plan ("agree with your proposal").
- **R2 — no Git remote.** The repository has no remote, so pull requests are
  impossible. Integration is by local merge into the release branch, with review
  evidence recorded on the beads. The operator merges the accepted release into
  `master` and tags it.
- **R3 — release authority.** The chief merges into the release branch only. The
  operator merges into `master` and tags. No deployment exists or is planned: this
  is a local CLI tool.
- **R4 — validation account.** Open: the operator has not yet named a real account
  for the end-to-end validation. Until it is named, a worker records a small public
  account's archive as a VCR cassette for deterministic replay, and the operator's
  own account is used for the final real-journey validation if the operator names
  one.
- **R5 — models.** Agents do not use OpenAI or Anthropic models for this release.
  Workers run `stealth/space-bunny-alpha` (OpenRouter, via the Pi harness) at
  `xhigh` effort. The operator is testing that model.

## Open questions for the operator

1. ~~Which real chess.com account validates v1 end to end (R4)?~~ **Answered
   2026-10-02: `kijuu11`**, the operator's own account, for the uncoached
   walkthrough and the live end-to-end run. Committed cassettes stay on
   non-personal accounts, because the repository's remote is public.
2. ~~Confirm the v1 semantic version to tag at acceptance.~~ **Answered
   2026-10-02: `0.1.0`**, not the `1.0.0` proposed here. `pyproject.toml` and
   `src/chessleak/__init__.py` both carry it, and `tests/unit/test_version.py`
   pins the two against each other.