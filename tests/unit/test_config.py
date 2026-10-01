"""Config defaults, CHESSLEAK_* environment overrides and position_key."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import chess
import pytest

from src.chessleak.config import (
    DEFAULT_CACHE_DIR,
    DEFAULT_STOCKFISH_DIR,
    Config,
    position_key,
    resolve_stockfish_path,
)

pytestmark = pytest.mark.unit


def test_config_defaults() -> None:
    """Config() yields the defaults the design record froze before dispatch."""
    cfg = Config()

    assert cfg.username == ""
    assert cfg.analysis_depth == 18
    assert cfg.opening_plies == 15
    assert cfg.cache_dir == DEFAULT_CACHE_DIR == "~/.cache/chessleak"
    assert cfg.win_prob_k == pytest.approx(0.004)
    assert cfg.book_band_cp == 30
    assert cfg.top_n == 20
    # The default engine is the shared binary installed by
    # scripts/get_stockfish.sh, which is the second entry of the resolution
    # order; the field is expanded so a caller can launch it directly.
    assert cfg.stockfish_path == str(Path(DEFAULT_STOCKFISH_DIR).expanduser() / "stockfish")


def test_config_is_frozen() -> None:
    """Other units share this dataclass, so a field cannot change under them."""
    cfg = Config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.analysis_depth = 20  # type: ignore[misc]


def test_config_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CHESSLEAK_DEPTH=22 gives analysis_depth == 22, and the rest follow."""
    for name in list(os.environ):
        if name.startswith("CHESSLEAK_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHESSLEAK_USERNAME", "magnuscarlsen")
    monkeypatch.setenv("CHESSLEAK_DEPTH", "22")
    monkeypatch.setenv("CHESSLEAK_OPENING_PLIES", "9")
    monkeypatch.setenv("CHESSLEAK_CACHE_DIR", "~/somewhere/chessleak-cache")
    monkeypatch.setenv("CHESSLEAK_WIN_PROB_K", "0.01")
    monkeypatch.setenv("CHESSLEAK_BOOK_BAND_CP", "25")
    monkeypatch.setenv("CHESSLEAK_TOP_N", "5")

    cfg = Config.from_env()

    assert cfg.analysis_depth == 22
    assert cfg.username == "magnuscarlsen"
    assert cfg.opening_plies == 9
    assert cfg.win_prob_k == pytest.approx(0.01)
    assert cfg.book_band_cp == 25
    assert cfg.top_n == 5
    # expanduser on paths.
    assert cfg.cache_dir == str(Path("~/somewhere/chessleak-cache").expanduser())
    assert "~" not in cfg.cache_dir


def test_config_from_env_without_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no CHESSLEAK_* in the environment, from_env() gives the defaults."""
    for name in list(os.environ):
        if name.startswith("CHESSLEAK_"):
            monkeypatch.delenv(name, raising=False)

    cfg = Config.from_env()

    assert cfg.analysis_depth == 18
    assert cfg.opening_plies == 15
    assert cfg.top_n == 20
    # from_env expands paths, Config() keeps the documented literal.
    assert cfg.cache_dir == str(Path(DEFAULT_CACHE_DIR).expanduser())


def test_config_env_rejects_non_numeric_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mistyped value fails loudly, naming the variable, not with a TypeError."""
    _clear_chessleak_env(monkeypatch)
    monkeypatch.setenv("CHESSLEAK_DEPTH", "deep")

    with pytest.raises(ValueError, match="CHESSLEAK_DEPTH"):
        Config.from_env()

    monkeypatch.delenv("CHESSLEAK_DEPTH")
    monkeypatch.setenv("CHESSLEAK_TOP_N", "20.5")

    with pytest.raises(ValueError, match="CHESSLEAK_TOP_N"):
        Config.from_env()


def _fen_after(san_moves: str) -> str:
    """The FEN reached by playing a real game fragment written in SAN.

    Move numbers ("1.", "2.", ...) are stripped, so the fragments below read like
    the notation in a book.
    """
    board = chess.Board()
    for token in san_moves.split():
        if token.rstrip(".").isdigit():
            continue
        board.push(board.parse_san(token))
    return board.fen()


def _clear_chessleak_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("CHESSLEAK_"):
            monkeypatch.delenv(name, raising=False)


#: Two routes to one position that differ only in the move counters. Each pair
#: plays a knight out and back at the start, so both knights are home again and
#: the identical position arrives two full moves later in the game.
TRANSPOSITIONS = (
    ("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6", "1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Nf3 Nc6 5. Bb5 a6"),
    ("1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5", "1. Nf3 Nf6 2. Ng1 Ng8 3. e4 e5 4. Nf3 Nc6 5. Bc4 Bc5"),
)


@pytest.mark.parametrize(("direct", "transposed"), TRANSPOSITIONS, ids=range(len(TRANSPOSITIONS)))
def test_position_key_ignores_the_move_counters(direct: str, transposed: str) -> None:
    """The same board at a different move number is one key, not two.

    ``board.fen()`` ends in the halfmove clock and the fullmove number, so a
    transposed position arrived at a different move count is a different string.
    Keying caches and clusters on the raw FEN splits those apart, which is what
    this function exists to prevent.
    """
    direct_fen = _fen_after(direct)
    transposed_fen = _fen_after(transposed)

    assert direct_fen != transposed_fen, "the two routes must differ in their counters"

    # The routes really are the same position, established without the key.
    direct_board = chess.Board(direct_fen)
    transposed_board = chess.Board(transposed_fen)
    assert direct_board.board_fen() == transposed_board.board_fen()
    assert direct_board.turn == transposed_board.turn
    assert direct_board.castling_rights == transposed_board.castling_rights
    assert direct_board.fen().split()[:4] == transposed_board.fen().split()[:4]
    assert {m.uci() for m in direct_board.legal_moves} == {
        m.uci() for m in transposed_board.legal_moves
    }

    assert position_key(direct_fen) == position_key(transposed_fen)
    assert position_key(direct_fen) == " ".join(direct_fen.split()[:4])


def test_position_key_ignores_the_halfmove_clock() -> None:
    """A knight out-and-back changes the halfmove clock but not the position."""
    start = chess.Board().fen()
    after_tempo_moves = _fen_after("1. Nf3 Nf6 2. Ng1 Ng8")

    assert start.split()[4:] != after_tempo_moves.split()[4:]
    assert chess.Board(after_tempo_moves).board_fen() == chess.Board(start).board_fen()
    assert position_key(start) == position_key(after_tempo_moves)


def test_position_key_separates_different_positions() -> None:
    """Every field the key keeps is one that changes the position.

    Literal FENs: ``position_key`` is a pure string function, so the cases that
    python-chess will not walk to on demand are spelled out here.
    """
    placement = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R"
    other_placement = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R2QK2R"
    with_ep = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"

    assert position_key(f"{placement} w KQkq - 0 1") != position_key(
        f"{other_placement} w KQkq - 0 1"
    ), "a different piece placement must be a different key"
    assert position_key(f"{placement} w KQkq - 0 1") != position_key(f"{placement} b KQkq - 0 1"), (
        "the side to move is part of the position"
    )
    assert position_key(f"{placement} w KQkq - 0 1") != position_key(f"{placement} w Kk - 0 1"), (
        "castling rights are part of the position"
    )
    assert position_key(with_ep) != position_key(with_ep.replace(" d6 ", " - ")), (
        "the en passant square is part of the position"
    )


def test_analysis_depth_reads_the_canonical_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """CHESSLEAK_ANALYSIS_DEPTH is the canonical name (design record revision 2)."""
    _clear_chessleak_env(monkeypatch)
    monkeypatch.setenv("CHESSLEAK_ANALYSIS_DEPTH", "22")

    assert Config.from_env().analysis_depth == 22


def test_analysis_depth_prefers_canonical_over_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """With both names set the canonical one wins."""
    _clear_chessleak_env(monkeypatch)
    monkeypatch.setenv("CHESSLEAK_DEPTH", "30")
    assert Config.from_env().analysis_depth == 30

    monkeypatch.setenv("CHESSLEAK_ANALYSIS_DEPTH", "22")
    assert Config.from_env().analysis_depth == 22


def test_analysis_depth_rejects_non_numeric_canonical_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mistyped canonical value names the canonical variable."""
    _clear_chessleak_env(monkeypatch)
    monkeypatch.setenv("CHESSLEAK_ANALYSIS_DEPTH", "deep")

    with pytest.raises(ValueError, match="CHESSLEAK_ANALYSIS_DEPTH"):
        Config.from_env()


def test_stockfish_path_resolution_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CHESSLEAK_STOCKFISH_PATH wins, then the shared binary, then PATH."""
    monkeypatch.setenv("CHESSLEAK_STOCKFISH_PATH", "~/explicit/engine")
    assert resolve_stockfish_path() == str(Path("~/explicit/engine").expanduser())

    monkeypatch.delenv("CHESSLEAK_STOCKFISH_PATH")
    monkeypatch.setenv("CHESSLEAK_STOCKFISH_ROOT", str(tmp_path))
    (tmp_path / "stockfish").write_text("#!/bin/sh\n")
    assert resolve_stockfish_path() == str(tmp_path / "stockfish")

    # Nothing installed anywhere: the documented shared path is the answer, so a
    # caller gets one clear error from the engine instead of a bare FileNotFound.
    monkeypatch.setenv("CHESSLEAK_STOCKFISH_ROOT", str(tmp_path / "not-installed"))
    monkeypatch.setattr("src.chessleak.config.shutil.which", lambda _name: None)
    assert resolve_stockfish_path() == str(tmp_path / "not-installed" / "stockfish")
