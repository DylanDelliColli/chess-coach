"""chessleak: surface a player's most consequential recurring opening mistakes.

v1 MVP, opening phase only. See ``docs/releases/v1-mvp.md`` for the release
brief and ``docs/releases/v1-mvp-design.md`` for the module contracts.

The package is importable as ``src.chessleak`` because the release brief froze
the console entry point as ``chessleak = src.chessleak.cli:main``.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
