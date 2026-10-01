"""Config defaults and CHESSLEAK_* environment overrides."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from src.chessleak.config import (
    DEFAULT_CACHE_DIR,
    DEFAULT_STOCKFISH_DIR,
    Config,
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
    monkeypatch.setenv("CHESSLEAK_DEPTH", "deep")

    with pytest.raises(ValueError, match="CHESSLEAK_DEPTH"):
        Config.from_env()

    monkeypatch.delenv("CHESSLEAK_DEPTH")
    monkeypatch.setenv("CHESSLEAK_TOP_N", "20.5")

    with pytest.raises(ValueError, match="CHESSLEAK_TOP_N"):
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
