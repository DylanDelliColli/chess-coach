"""Shared pytest setup for chessleak.

The repository is a ``src``-layout project whose console entry point is
``chessleak = src.chessleak.cli:main`` (frozen by the release brief), so the
importable path of the package is ``src.chessleak``.  Putting the repository root
on ``sys.path`` makes the tests run against the working tree whether or not the
package has been installed into the active environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
