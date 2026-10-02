"""chessleak: surface a player's most consequential recurring opening mistakes.

v1 MVP, opening phase only. See ``docs/releases/v1-mvp.md`` for the release
brief and ``docs/releases/v1-mvp-design.md`` for the module contracts.

The package is importable as ``src.chessleak`` because the release brief froze
the console entry point as ``chessleak = src.chessleak.cli:main``.
"""

from __future__ import annotations

#: The version this release is tagged with. The operator ruled on 2026-10-02
#: that the first release is 0.1.0; ``pyproject.toml`` carries the same figure
#: and ``tests/unit/test_version.py`` pins the two against each other.
__version__ = "0.1.0"

__all__ = ["__version__"]
