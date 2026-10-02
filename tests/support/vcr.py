"""Shared VCR setup for tests that touch the chess.com public API.

The release brief and the design record fix one policy for every lane:

* the default test mode **replays** a recorded cassette with
  ``record_mode="none"``, so a default suite run makes no network request at all;
* recording is gated behind ``CHESSLEAK_LIVE=1``, which is how a cassette is
  first recorded from the real API.

    CHESSLEAK_LIVE=1 python -m pytest tests/integration/test_fetch_live.py

Cassettes live in ``tests/fixtures/cassettes/``, named after the public account
they were recorded from. They hold only what the chess.com Published Data API
publishes for that account; nothing here authenticates to anything.

``chessbumper``'s cassette is the small end-to-end fetch proof (one archive, a
handful of games); ``bobbyfischer``'s is the bounded monthly archive the
end-to-end pipeline test replays (85 games, one month). ``U4`` (bead ``chess-3if``)
owns both.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import vcr

__all__ = [
    "CASSETTE_DIR",
    "LIVE_ENV_VAR",
    "cassette",
    "cassette_path",
    "chessleak_vcr",
    "live_enabled",
]

#: Repository root, derived from this file (``tests/support/vcr.py``).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where every recorded cassette lives.
CASSETTE_DIR = REPO_ROOT / "tests" / "fixtures" / "cassettes"

#: The variable that turns a run into a recording run.
LIVE_ENV_VAR = "CHESSLEAK_LIVE"

#: Headers never written into a cassette. The project authenticates to nothing,
#: so these are belt-and-braces: a cookie echoed by a CDN must not land in git.
FILTERED_HEADERS = ["authorization", "cookie", "set-cookie", "proxy-authorization"]


def live_enabled() -> bool:
    """True when this run may record (``CHESSLEAK_LIVE=1``)."""
    return os.environ.get(LIVE_ENV_VAR, "").strip() == "1"


def cassette_path(name: str) -> Path:
    """The file a named cassette is stored in (whether or not it exists yet)."""
    return CASSETTE_DIR / name


def chessleak_vcr(**overrides: Any) -> vcr.VCR:
    """A :class:`vcr.VCR` configured with the release's replay/record policy.

    Requests are matched on method and URL (vcr's default), never on headers, so
    a different ``User-Agent`` or an added header cannot break a replay.
    """
    settings: dict[str, Any] = {
        "cassette_library_dir": str(CASSETTE_DIR),
        "record_mode": "once" if live_enabled() else "none",
        # Record decoded bodies: a cassette then replays without depending on
        # the CDN's content coding.
        "decode_compressed_response": True,
        "filter_headers": FILTERED_HEADERS,
    }
    settings.update(overrides)
    return vcr.VCR(**settings)


@contextmanager
def cassette(name: str, **overrides: Any) -> Iterator[Any]:
    """Use the named cassette, replaying it (or recording it when live).

    Yields the cassette object, whose ``play_count`` lets a test prove that a
    second run made no HTTP request at all. (vcrpy 8.3 has no ``write_count``;
    ``write_protected`` is the flag that says a replay could not have written
    into the committed fixture.)
    """
    with chessleak_vcr(**overrides).use_cassette(name) as loaded:
        yield loaded
