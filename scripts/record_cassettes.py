#!/usr/bin/env python
"""Record this release's chess.com cassettes from the real API.

The suite replays cassettes (``record_mode="none"`` by default); a cassette is
written only by this script, which requires ``CHESSLEAK_LIVE=1`` so that a
casual ``pytest`` run can never reach the network:

    CHESSLEAK_LIVE=1 python scripts/record_cassettes.py                 # both
    CHESSLEAK_LIVE=1 python scripts/record_cassettes.py chessbumper     # one

What it records, and why those accounts:

``chessbumper``
    A tiny public account: the archives index and its single month archive
    (``.../games/2014/08``, 7 games). Enough to exercise the whole path —
    including the index cache — in a cassette small enough to read.
``bobbyfischer``
    A public account with a bounded month: the index and
    ``.../games/2023/11``, 85 games. This is the archive the end-to-end
    pipeline test (``U8``) replays, and it satisfies the design record's
    requirement of a real month with at least 50 games.

Requests go through :mod:`src.chessleak.fetch`, so what is recorded is exactly
what the pipeline reads: a descriptive ``User-Agent``, serial and spaced.

Cookies are stripped from every recorded response afterwards. This project
authenticates to nothing, so a cassette has no business holding a session token
(a CDN's ``__cf_bm`` cookie), and vcrpy's ``filter_headers`` only filters
*requests* for the httpx stub. The rewrite goes through vcrpy's own
serializer, so the result is a cassette vcrpy can still read.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import vcr as vcr_support  # noqa: E402

from src.chessleak.fetch import archives_url, fetch_archive, list_archives  # noqa: E402

#: The cassette each account is recorded into, and the one monthly archive of
#: that account the cassette carries.
TARGETS: dict[str, str] = {
    "chessbumper": "https://api.chess.com/pub/player/chessbumper/games/2014/08",
    "bobbyfischer": "https://api.chess.com/pub/player/bobbyfischer/games/2023/11",
}

#: Response headers that must never be committed, whatever the service sent.
STRIPPED_RESPONSE_HEADERS = ("cookie", "set-cookie")


def strip_secret_headers(path: Path) -> int:
    """Rewrite a cassette without cookie-like response headers.

    Returns how many headers were removed. Uses vcrpy's deserializer and
    serializer, so the file stays a cassette vcrpy can replay.
    """
    from vcr.serializers import yamlserializer

    data = yamlserializer.deserialize(path.read_text(encoding="utf-8"))
    removed = 0
    for interaction in data.get("interactions", []):
        response = interaction.get("response", {})
        headers = response.get("headers", {})
        for name in STRIPPED_RESPONSE_HEADERS:
            if headers.pop(name, None) is not None:
                removed += 1
    path.write_text(yamlserializer.serialize(data), encoding="utf-8")
    return removed


def record(username: str, archive_url: str) -> None:
    """Record one account's index and one monthly archive, then scrub cookies."""
    cassette = vcr_support.cassette_path(f"{username}.yaml")
    with vcr_support.cassette(f"{username}.yaml", record_mode="all"):
        archives = list_archives(username)
        games = fetch_archive(archive_url, username)

    if archive_url not in archives:
        raise SystemExit(f"{username}: {archive_url} is not in the account's archive list")
    if not games:
        raise SystemExit(f"{username}: {archive_url} returned no games")

    removed = strip_secret_headers(cassette)
    print(
        f"recorded {cassette.name}: account {username}, "
        f"index {archives_url(username)} ({len(archives)} archives), "
        f"archive {archive_url} ({len(games)} games), "
        f"{cassette.stat().st_size} bytes, {removed} cookie headers stripped"
    )


def main(argv: list[str]) -> int:
    if not vcr_support.live_enabled():
        print(
            f"refusing to touch the network: set {vcr_support.LIVE_ENV_VAR}=1 to record",
            file=sys.stderr,
        )
        return 1
    wanted = argv[1:] or list(TARGETS)
    unknown = [name for name in wanted if name not in TARGETS]
    if unknown:
        print(f"unknown account(s): {', '.join(unknown)}; known: {', '.join(TARGETS)}")
        return 2
    for username in wanted:
        record(username, TARGETS[username])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
