"""The version this release is tagged with, pinned where it is written down.

The operator ruled on 2026-10-02 that the first release is ``0.1.0``, and
``docs/releases/v1-mvp.md`` carries the same figure in its acceptance section.
The number lives in two files, and a distribution whose metadata disagrees with
its own package is a thing nobody notices until a bug report names the wrong
version, so the two are pinned against each other here rather than trusted.

The package is importable as ``src.chessleak`` (the frozen console entry point),
so this is an import of the working tree, like every other test in the suite.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import src.chessleak

pytestmark = pytest.mark.unit

#: The ruled first release, from docs/releases/v1-mvp.md and the release bead.
FIRST_RELEASE = "0.1.0"

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_package_claims_the_ruled_first_release() -> None:
    """``__version__`` is 0.1.0 - the tag the operator chose, not 1.0.0."""
    assert src.chessleak.__version__ == FIRST_RELEASE


def test_the_distribution_metadata_agrees_with_the_package() -> None:
    """``pyproject.toml`` carries the same version, so an install cannot disagree."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert metadata["name"] == "chessleak"
    assert metadata["version"] == FIRST_RELEASE
