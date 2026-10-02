"""The real chess.com fetch path, replayed from cassettes recorded once.

These tests make no mocks of the transport, the disk or the clock. What they do
use is a **cassette**: the first run recorded real HTTP from the chess.com
Published Data API, and every later run replays those exact bytes. With the
default ``record_mode="none"`` a request that is not in the cassette fails the
test instead of reaching the network, so this file is deterministic offline.

Record or refresh the cassettes with ``scripts/record_cassettes.py``:

    CHESSLEAK_LIVE=1 python scripts/record_cassettes.py

Cassettes owned by ``U4`` (``chess-3if``):

``chessbumper.yaml``
    account ``chessbumper``, archives index + its single month archive
    ``.../player/chessbumper/games/2014/08``, 7 games, recorded 2026-10-01.
    Small enough to exercise the whole path, including the index cache.
``bobbyfischer.yaml``
    account ``bobbyfischer``, archives index + the bounded month archive
    ``.../player/bobbyfischer/games/2023/11``, 85 games, recorded 2026-10-01.
    This is the archive the end-to-end pipeline test (U8) replays.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import chess
import chess.pgn
import pytest
from tests.support import vcr as vcr_support

from src.chessleak.fetch import (
    archive_cache_path,
    archives_url,
    download_all,
    fetch_archive,
    index_cache_path,
    is_month_selector,
    list_archives,
    month_archive_url,
)

pytestmark = pytest.mark.integration

CHESSBUMPER = "chessbumper"
CHESSBUMPER_ARCHIVE = "https://api.chess.com/pub/player/chessbumper/games/2014/08"
BOBBYFISCHER = "bobbyfischer"
BOBBYFISCHER_ARCHIVE = "https://api.chess.com/pub/player/bobbyfischer/games/2023/11"
#: The same month as the operator would type it (``chess-iql``).
BOBBYFISCHER_ARCHIVE_MONTH = "2023/11"

CHESSBUMPER_CASSETTE = "chessbumper.yaml"
BOBBYFISCHER_CASSETTE = "bobbyfischer.yaml"

EXPECTED_GAMES = {CHESSBUMPER: 7, BOBBYFISCHER: 85}


def test_list_and_fetch_real_archive() -> None:
    """Real HTTP, replayed: an account's archives list, and real games from one.

    Asserts the whole point of the unit: the API answers with an archive list,
    the month archive maps to ``GameRecord``s whose PGN is a real, complete game
    that python-chess can parse.
    """
    with vcr_support.cassette(BOBBYFISCHER_CASSETTE) as cassette:
        archives = list_archives(BOBBYFISCHER)
        games = fetch_archive(BOBBYFISCHER_ARCHIVE, BOBBYFISCHER)

    assert cassette.play_count >= 2, "the cassette should carry the index and the archive"
    assert len(archives) >= 1
    assert BOBBYFISCHER_ARCHIVE in archives
    assert all(url.startswith("https://api.chess.com/pub/player/") for url in archives)

    assert len(games) == EXPECTED_GAMES[BOBBYFISCHER]
    assert len({g.id for g in games}) == len(games), "game ids must be unique"
    for game in games:
        assert game.id.startswith("https://www.chess.com/game/")
        assert game.pgn.strip(), f"{game.id} has an empty pgn"
        assert game.my_color in {"white", "black"}, f"{game.id}: {game.my_color!r}"
        assert game.result in {"1-0", "0-1", "1/2-1/2"}
        assert game.rules and game.initial_setup

    # Real composition: the PGN this module hands over is a real chess game.
    first = games[0]
    parsed = chess.pgn.read_game(io.StringIO(first.pgn))
    assert parsed is not None, f"python-chess could not parse the pgn of {first.id}"
    assert parsed.headers["White"] == first.white
    assert parsed.headers["Black"] == first.black
    assert parsed.headers["Result"] == first.result
    assert list(parsed.mainline_moves()), f"{first.id} parsed to a game with no moves"


def test_both_colours_and_both_sides_of_the_result_appear_in_real_data() -> None:
    """A real month contains the player's wins as white and as black."""
    with vcr_support.cassette(BOBBYFISCHER_CASSETTE):
        games = fetch_archive(BOBBYFISCHER_ARCHIVE, BOBBYFISCHER)

    assert {g.my_color for g in games} == {"white", "black"}
    assert {g.result for g in games} <= {"1-0", "0-1", "1/2-1/2"}
    assert any(g.result == "1-0" and g.my_color == "black" for g in games)
    assert any(g.result == "0-1" and g.my_color == "white" for g in games)
    assert all(g.end_time for g in games)
    assert all(g.eco is not None for g in games), "this archive has an eco for every game"


def test_download_all_caches_the_real_archive_and_the_second_run_makes_no_http(
    tmp_path: Path,
) -> None:
    """The release's O1 promise, on real data and a real filesystem.

    First run: the index and the month archive are fetched over the recorded HTTP
    and written to disk. Second run: the cassette's play counter does not move,
    because every byte came from the cache.
    """
    archives = [BOBBYFISCHER_ARCHIVE]

    with vcr_support.cassette(BOBBYFISCHER_CASSETTE) as cassette:
        first = download_all(BOBBYFISCHER, tmp_path, archives=archives)
        after_first = cassette.play_count

        second = download_all(BOBBYFISCHER, tmp_path, archives=archives)
        after_second = cassette.play_count

    assert after_first >= 1
    assert after_second == after_first, "the second download_all went back to the network"
    assert second == first
    assert len(first) == EXPECTED_GAMES[BOBBYFISCHER]

    # Real files on real disk, one per URL, holding the response as it arrived.
    cached_archive = archive_cache_path(tmp_path, BOBBYFISCHER_ARCHIVE)
    assert cached_archive.is_file()
    payload = json.loads(cached_archive.read_text(encoding="utf-8"))
    assert len(payload["games"]) == EXPECTED_GAMES[BOBBYFISCHER]
    assert payload["games"][0]["pgn"].startswith("[Event ")

    # And the newest game first, which is what a --max-games bound wants.
    assert first == sorted(first, key=lambda g: g.end_time, reverse=True)


def test_download_all_of_a_whole_account_is_served_from_cache(tmp_path: Path) -> None:
    """A one-archive account: the full path, index included, then a no-HTTP rerun."""
    with vcr_support.cassette(CHESSBUMPER_CASSETTE) as cassette:
        first = download_all(CHESSBUMPER, tmp_path)
        after_first = cassette.play_count

        second = download_all(CHESSBUMPER, tmp_path)
        after_second = cassette.play_count

    assert after_first == 2, "one index request and one archive request"
    assert after_second == after_first
    assert len(first) == len(second) == EXPECTED_GAMES[CHESSBUMPER]
    assert second == first

    # The index really was cached under the account, not just used.
    index = json.loads(index_cache_path(tmp_path, CHESSBUMPER).read_text(encoding="utf-8"))
    assert index["archives"] == [CHESSBUMPER_ARCHIVE]


def test_a_second_process_would_read_the_same_cache(tmp_path: Path) -> None:
    """The cache is on disk, not in memory: a fresh download_all with no HTTP reads it."""
    with vcr_support.cassette(CHESSBUMPER_CASSETTE):
        download_all(CHESSBUMPER, tmp_path)

    # No HTTP is possible here: the cassette is opened with record_mode="none"
    # for the whole block, so a request that is not in it raises instead of
    # reaching the network. The only way this passes is a complete cache.
    with vcr_support.cassette(CHESSBUMPER_CASSETTE, record_mode="none") as cassette:
        cached = download_all(CHESSBUMPER, tmp_path)
        assert cassette.play_count == 0

    assert len(cached) == EXPECTED_GAMES[CHESSBUMPER]
    assert all(game.my_color in {"white", "black"} for game in cached)


def test_a_bare_month_selects_the_same_real_archive_a_url_does(tmp_path: Path) -> None:
    """``--archive 2023/11`` against the real recorded API, and no stub in between.

    The defect ``chess-iql`` recorded was that a bare month reached httpx as a URL
    and died with *"Request URL is missing an 'http://' or 'https://' protocol"*.
    Here the month is resolved through the account's own recorded index, so the
    archive that comes back is the one chess.com published, byte for byte, and the
    games are the same 85 the full-URL path fetches. Two interactions are played -
    the index and the month - against ``record_mode="none"``, so a resolution that
    guessed a URL instead of asking the index would fail rather than reach the net.
    """
    assert is_month_selector(BOBBYFISCHER_ARCHIVE_MONTH), "the month the operator types"

    with vcr_support.cassette(BOBBYFISCHER_CASSETTE) as cassette:
        games = download_all(BOBBYFISCHER, tmp_path, archives=[BOBBYFISCHER_ARCHIVE_MONTH])
        assert cassette.play_count == 2, "the index, then the month archive it named"

    assert len(games) == EXPECTED_GAMES[BOBBYFISCHER], "the same 85 real games"
    assert all(game.my_color is not None for game in games)

    # Both documents landed on real disk, keyed by the URL they came from, and the
    # archive is cached under the index's own URL: a resolution that guessed a URL
    # would have asked for an address the cassette does not hold.
    assert index_cache_path(tmp_path, BOBBYFISCHER).is_file()
    assert archive_cache_path(tmp_path, BOBBYFISCHER_ARCHIVE).is_file()

    # A second run needs neither document: the month resolves from the cached index
    # and the archive comes off disk.
    with vcr_support.cassette(BOBBYFISCHER_CASSETTE) as cassette:
        again = download_all(BOBBYFISCHER, tmp_path, archives=[BOBBYFISCHER_ARCHIVE_MONTH])
        assert cassette.play_count == 0, "the second run went to the network"
    assert again == games

    # And the resolution itself is the index's answer, asked for directly. A new
    # cassette block, because vcrpy plays each recorded interaction once per block.
    with vcr_support.cassette(BOBBYFISCHER_CASSETTE) as cassette:
        resolved = month_archive_url(BOBBYFISCHER, BOBBYFISCHER_ARCHIVE_MONTH, cache_dir=tmp_path)
        assert cassette.play_count == 0, "served from the index cached above"
    assert resolved == BOBBYFISCHER_ARCHIVE


def test_cassettes_are_present_and_non_empty() -> None:
    """The design record's cassette requirement: recorded, real, and committed."""
    for name in (CHESSBUMPER_CASSETTE, BOBBYFISCHER_CASSETTE):
        path = vcr_support.cassette_path(name)
        assert path.is_file(), f"missing cassette {path}: record it with CHESSLEAK_LIVE=1"
        assert path.stat().st_size > 1000, f"cassette {path.name} is suspiciously small"

    text = vcr_support.cassette_path(BOBBYFISCHER_CASSETTE).read_text(encoding="utf-8")
    assert BOBBYFISCHER_ARCHIVE in text
    assert archives_url(BOBBYFISCHER) in text


def test_cassettes_carry_no_session_material() -> None:
    """This project authenticates to nothing, so a cassette must hold no cookie."""
    for name in (CHESSBUMPER_CASSETTE, BOBBYFISCHER_CASSETTE):
        text = vcr_support.cassette_path(name).read_text(encoding="utf-8")
        assert "set-cookie" not in text.lower(), f"{name} recorded a cookie"
        assert "authorization" not in text.lower(), f"{name} recorded a credential"
        assert "__cf_bm" not in text, f"{name} recorded a CDN session token"
