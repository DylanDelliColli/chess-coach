"""The chess.com fetcher: mapping, cache and error behaviour, with no real HTTP.

The archive replica this file parses is ``tests/fixtures/archive_sample.json``,
built by ``U4`` from real chess.com responses (account ``bobbyfischer``). Six of
its eight games are verbatim API responses; two are clones of a real game with
one field changed, to cover shapes the account does not itself contain:

* a mixed-case spelling of the account name (chess.com preserves the case a
  player registered), which must still derive ``my_color``;
* an unrated game whose ``white.rating`` / ``black.rating`` are ``null``.

The replica also contains a draw, two games with no ``eco`` key at all (one of
which still carries the ``[ECO]`` tag in its PGN, which is the precedence case
``pgnio.py`` owns) and two non-``chess`` variants.

Every test here uses a stub client, so no test in this file touches the network;
the real HTTP path is covered by ``tests/integration/test_fetch_live.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chess
import httpx
import pytest

from src.chessleak.fetch import (
    CACHE_SUBDIR_ARCHIVES,
    CACHE_SUBDIR_INDEX,
    MAX_ATTEMPTS,
    FetchError,
    GameRecord,
    HttpStatusError,
    HttpxClient,
    UnknownAccountError,
    UnknownArchiveError,
    archive_cache_path,
    archives_url,
    cache_key,
    default_headers,
    derive_my_color,
    download_all,
    eco_label,
    fetch_archive,
    game_record_from_archive_json,
    games_from_archive_json,
    index_cache_path,
    is_month_selector,
    list_archives,
    month_archive_url,
    resolve_archive,
    result_summary,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_ARCHIVE = FIXTURES / "archive_sample.json"

ACCOUNT = "bobbyfischer"
INDEX_URL = archives_url(ACCOUNT)
ARCHIVE_URL = "https://api.chess.com/pub/player/bobbyfischer/games/2023/11"
OTHER_ARCHIVE_URL = "https://api.chess.com/pub/player/bobbyfischer/games/2023/12"
OTHER_ACCOUNT_INDEX_URL = archives_url("chessbumper")


class StubClient:
    """A ``TextClient`` serving canned response text and recording every URL asked for."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses: dict[str, Any] = dict(responses or {})
        self.calls: list[str] = []

    def get_text(self, url: str) -> str:
        self.calls.append(url)
        try:
            body = self.responses[url]
        except KeyError:
            raise AssertionError(f"unexpected HTTP request: {url}") from None
        if isinstance(body, Exception):
            raise body
        return body


def sample_games() -> list[dict[str, Any]]:
    return json.loads(SAMPLE_ARCHIVE.read_text(encoding="utf-8"))["games"]


def sample_text(games: list[dict[str, Any]] | None = None) -> str:
    return json.dumps({"games": sample_games() if games is None else games})


def sample_client() -> StubClient:
    """A stub serving the replica for the 2023/11 archive URL only."""
    return StubClient({ARCHIVE_URL: sample_text()})


def two_archive_client(**overrides: Any) -> StubClient:
    """A stub serving the index and two monthly archives of the replica.

    The index lists the archives the way chess.com does: oldest month first,
    which here is 2023/11 then 2023/12.
    """
    client = StubClient(
        {
            INDEX_URL: json.dumps({"archives": [ARCHIVE_URL, OTHER_ARCHIVE_URL]}),
            ARCHIVE_URL: sample_text(),
            OTHER_ARCHIVE_URL: sample_text(sample_games()[:3]),
        }
    )
    for url, body in overrides.pop("responses", {}).items():
        client.responses[url] = body
    return client


def by_url(records: list[GameRecord], url: str) -> GameRecord:
    (record,) = [r for r in records if r.id == url]
    return record


# --- mapping ---------------------------------------------------------------


def test_gamerecord_from_archive_json() -> None:
    """Every field of ``GameRecord`` comes out of the replica archive, correctly."""
    records = games_from_archive_json(json.loads(SAMPLE_ARCHIVE.read_text()), ACCOUNT)

    assert len(records) == len(sample_games()) == 8

    white_win = by_url(records, "https://www.chess.com/game/live/82112974006")
    assert white_win.white == "bobbyfischer"
    assert white_win.black == "lardow"
    assert white_win.white_result == "resigned"
    assert white_win.black_result == "win"
    assert white_win.result == "0-1"
    assert white_win.my_color == "white"
    assert white_win.white_rating == 121
    assert white_win.black_rating == 170
    assert white_win.time_control == "180"
    assert white_win.rules == "chess"
    assert white_win.initial_setup == chess.STARTING_FEN
    assert white_win.end_time is not None and white_win.end_time > 1_600_000_000
    assert white_win.eco == "Four-Knights-Game"
    assert white_win.pgn.startswith("[Event ")
    assert f'[Link "{white_win.id}"]' in white_win.pgn

    black_loss = by_url(records, "https://www.chess.com/game/live/94052559659")
    assert black_loss.my_color == "black"
    assert black_loss.result == "1-0"
    assert black_loss.white == "GMW2U"
    assert black_loss.black == "bobbyfischer"

    draw = by_url(records, "https://www.chess.com/game/live/82103728406")
    assert draw.result == "1/2-1/2"
    assert draw.white_result == draw.black_result == "agreed"
    assert draw.my_color == "white"

    # A game with no ``eco`` key at all: the archive offers nothing, so the
    # field is None and the PGN tag (if any) is what pgnio.py will fall back on.
    no_archive_eco_but_pgn_tag = by_url(records, "https://www.chess.com/game/live/100799725125")
    assert no_archive_eco_but_pgn_tag.eco is None
    assert "[ECO " in no_archive_eco_but_pgn_tag.pgn

    no_eco_anywhere = by_url(records, "https://www.chess.com/game/live/101199155865")
    assert no_eco_anywhere.eco is None
    assert "[ECO " not in no_eco_anywhere.pgn

    # Variants are carried verbatim; deciding to skip them is pgnio.py's job,
    # and it can only do that if the field survives the mapping.
    variant = by_url(records, "https://www.chess.com/game/live/100158741597")
    assert variant.rules == "oddschess"

    # The mixed-case clone: the account's name is spelled differently, and
    # matching is case-insensitive, so this is still the player's black game.
    mixed_case = by_url(records, "https://www.chess.com/game/live-mixedcase-94052559659")
    assert mixed_case.black == "Bobbyfischer"
    assert mixed_case.my_color == "black"

    # The unrated clone: ratings are ``null`` in the API, so they map to None
    # rather than to 0 (which would read as a real 0-rated game).
    unrated = by_url(records, "https://www.chess.com/game/live-unrated-94052559659")
    assert unrated.white_rating is None
    assert unrated.black_rating is None


def test_game_record_tolerates_missing_optional_fields() -> None:
    """A minimal game object maps to the documented defaults, not to a crash."""
    record = game_record_from_archive_json(
        {
            "url": "https://www.chess.com/game/live/1",
            "pgn": '[Event "x"]\n\n*',
            "white": {"username": "someone"},
            "black": {"username": "else"},
        },
        "someone",
    )

    assert record.eco is None
    assert record.end_time is None
    assert record.white_rating is None
    assert record.black_rating is None
    assert record.result == "1/2-1/2"
    assert record.white_result == ""
    assert record.black_result == ""
    assert record.time_control == ""
    assert record.my_color == "white"
    # Absent ``rules``/``initial_setup`` mean an ordinary standard game, not a
    # variant with a custom starting position (which downstream units skip).
    assert record.rules == "chess"
    assert record.initial_setup == chess.STARTING_FEN


def test_game_record_is_immutable() -> None:
    """Records are frozen values shared by every unit that consumes them."""
    record = game_record_from_archive_json({"url": "u", "white": {}, "black": {}})
    with pytest.raises(AttributeError):
        record.pgn = "tampered"  # type: ignore[misc]


def test_games_from_archive_json_rejects_a_payload_that_is_not_an_archive() -> None:
    """A wrong-shaped response raises rather than silently yielding no games."""
    with pytest.raises(FetchError) as excinfo:
        games_from_archive_json({"archives": []})
    assert "games" in str(excinfo.value)


@pytest.mark.parametrize(
    ("white_result", "black_result", "expected"),
    [
        ("win", "resigned", "1-0"),
        ("win", "checkmated", "1-0"),
        ("win", "timeout", "1-0"),
        ("resigned", "win", "0-1"),
        ("timeout", "win", "0-1"),
        ("agreed", "agreed", "1/2-1/2"),
        ("stalemate", "stalemate", "1/2-1/2"),
        ("repetition", "repetition", "1/2-1/2"),
        ("abandoned", "win", "0-1"),
        ("", "", "1/2-1/2"),
        (None, None, "1/2-1/2"),
    ],
)
def test_result_summary(white_result: str | None, black_result: str | None, expected: str) -> None:
    """chess.com's per-colour result words become one PGN-style result."""
    assert result_summary(white_result, black_result) == expected


def test_result_summary_ignores_case_and_padding() -> None:
    assert result_summary(" Win ", "resigned") == "1-0"
    assert result_summary("resigned", "WIN") == "0-1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.chess.com/openings/Four-Knights-Game", "Four-Knights-Game"),
        ("https://www.chess.com/openings/Englund-Gambit-2.dxe5", "Englund-Gambit-2.dxe5"),
        ("Four-Knights-Game", "Four-Knights-Game"),
        ("B90", "B90"),
        ("", None),
        (None, None),
    ],
)
def test_eco_label(raw: str | None, expected: str | None) -> None:
    """The archive's ``eco`` is a chess.com URL; the label is its last segment."""
    assert eco_label(raw) == expected


def test_derive_my_color_matches_case_insensitively() -> None:
    assert derive_my_color("BobbyFischer", "opponent", "bobbyfischer") == "white"
    assert derive_my_color("opponent", "BOBBYFISCHER", "bobbyfischer") == "black"
    assert derive_my_color("opponent", "opponent", "bobbyfischer") is None
    assert derive_my_color("opponent", "opponent", "") is None
    assert derive_my_color("opponent", "opponent", None) is None
    # Same name on both sides cannot happen on chess.com; white wins the tie so
    # the record is never left without a perspective.
    assert derive_my_color("bobbyfischer", "bobbyfischer", "bobbyfischer") == "white"


# --- cache keys and layout -------------------------------------------------


def test_cache_key_is_stable_filesystem_safe_and_collision_free() -> None:
    """The cache is keyed by URL, so the key must be stable and path-safe."""
    assert cache_key(INDEX_URL) == cache_key(INDEX_URL)
    assert cache_key(INDEX_URL) != cache_key(OTHER_ACCOUNT_INDEX_URL)

    key = cache_key(ARCHIVE_URL)
    assert key.endswith(".json")
    assert set(key) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    assert "/" not in key and "\\" not in key and ".." not in key


def test_cache_paths_are_separate_for_the_index_and_the_archives(tmp_path: Path) -> None:
    index = index_cache_path(tmp_path, ACCOUNT)
    archive = archive_cache_path(tmp_path, ARCHIVE_URL)

    assert index.parent.name == CACHE_SUBDIR_INDEX
    assert archive.parent.name == CACHE_SUBDIR_ARCHIVES
    assert index != archive
    assert index_cache_path(tmp_path, "BobbyFischer") == index
    assert archive_cache_path(tmp_path, ARCHIVE_URL + "?x=1") != archive


# --- cache behaviour -------------------------------------------------------


def test_cache_skips_redownload(tmp_path: Path) -> None:
    """A second ``download_all`` is served entirely from disk: no request at all."""
    first = two_archive_client()
    first_run = download_all(ACCOUNT, tmp_path, client=first)
    assert first.calls == [INDEX_URL, OTHER_ARCHIVE_URL, ARCHIVE_URL]
    assert len(first_run) == 8

    second = StubClient()  # any HTTP request raises AssertionError
    second_run = download_all(ACCOUNT, tmp_path, client=second)

    assert second.calls == []
    assert second_run == first_run


def test_second_run_reads_the_index_and_archives_from_disk_verbatim(tmp_path: Path) -> None:
    """The cache holds the response bytes as they arrived, under the URL's key."""
    raw = two_archive_client()
    download_all(ACCOUNT, tmp_path, client=raw)

    index_file = index_cache_path(tmp_path, ACCOUNT)
    archive_file = archive_cache_path(tmp_path, ARCHIVE_URL)
    assert index_file.read_text(encoding="utf-8") == raw.responses[INDEX_URL]
    assert archive_file.read_text(encoding="utf-8") == raw.responses[ARCHIVE_URL]


def test_cache_write_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    download_all(ACCOUNT, tmp_path, client=two_archive_client())
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == sorted(
        [
            index_cache_path(tmp_path, ACCOUNT).name,
            archive_cache_path(tmp_path, ARCHIVE_URL).name,
            archive_cache_path(tmp_path, OTHER_ARCHIVE_URL).name,
        ]
    )


def test_corrupt_cache_file_is_refetched(tmp_path: Path) -> None:
    """A cache is disposable: unreadable content costs one request, not a crash."""
    archive_file = archive_cache_path(tmp_path, ARCHIVE_URL)
    archive_file.parent.mkdir(parents=True)
    archive_file.write_text("{not json", encoding="utf-8")

    records = fetch_archive(ARCHIVE_URL, ACCOUNT, cache_dir=tmp_path, client=sample_client())

    assert len(records) == 8
    assert archive_cache_path(tmp_path, ARCHIVE_URL).exists()


def test_list_archives_uses_the_cached_index(tmp_path: Path) -> None:
    """``list_archives`` returns the API's own order: oldest month first."""
    download_all(ACCOUNT, tmp_path, client=two_archive_client())
    client = StubClient()
    assert list_archives(ACCOUNT, cache_dir=tmp_path, client=client) == [
        ARCHIVE_URL,
        OTHER_ARCHIVE_URL,
    ]
    assert client.calls == []


def test_list_archives_without_a_cache_dir_always_asks() -> None:
    """``list_archives(username)`` with no cache_dir is the bead's plain HTTP call."""
    client = two_archive_client()
    assert list_archives(ACCOUNT, client=client) == [ARCHIVE_URL, OTHER_ARCHIVE_URL]
    assert list_archives(ACCOUNT, client=client) == [ARCHIVE_URL, OTHER_ARCHIVE_URL]
    assert client.calls == [INDEX_URL, INDEX_URL]


def test_list_archives_returns_nothing_for_an_account_with_no_games() -> None:
    """``firouzj`` publishes ``{"archives": []}``: an empty list, not an error."""
    client = StubClient({archives_url("emptyaccount"): json.dumps({"archives": []})})
    assert list_archives("emptyaccount", client=client) == []


def test_download_all_orders_newest_first_and_deduplicates(tmp_path: Path) -> None:
    """Months come back newest first, and a game listed twice appears once."""
    older = {
        "url": "https://www.chess.com/game/live/older",
        "pgn": "*",
        "end_time": 1_700_000_000,
        "white": {"username": ACCOUNT, "result": "win"},
        "black": {"username": "opp", "result": "resigned"},
    }
    newer = {**older, "url": "https://www.chess.com/game/live/newer", "end_time": 1_800_000_000}
    duplicated = {**older, "url": "https://www.chess.com/game/live/dup", "end_time": 1_750_000_000}
    client = StubClient(
        {
            INDEX_URL: json.dumps({"archives": [ARCHIVE_URL, OTHER_ARCHIVE_URL]}),
            OTHER_ARCHIVE_URL: json.dumps({"games": [newer, duplicated]}),
            ARCHIVE_URL: json.dumps({"games": [older, newer]}),
        }
    )

    records = download_all(ACCOUNT, tmp_path, client=client)

    assert [r.id for r in records] == [
        "https://www.chess.com/game/live/newer",
        "https://www.chess.com/game/live/dup",
        "https://www.chess.com/game/live/older",
    ]
    assert client.calls == [INDEX_URL, OTHER_ARCHIVE_URL, ARCHIVE_URL]


def test_download_all_can_be_given_archives_directly(tmp_path: Path) -> None:
    """An explicit archive list skips the index request entirely."""
    client = sample_client()
    records = download_all(ACCOUNT, tmp_path, archives=[ARCHIVE_URL], client=client)

    assert client.calls == [ARCHIVE_URL]
    assert len(records) == 8
    assert all(r.my_color is not None for r in records)


# --- naming an archive: a URL, or a month (chess-iql) -----------------------


def test_a_bare_month_resolves_to_the_archives_own_url(tmp_path: Path) -> None:
    """``--archive 2023/11`` is the natural thing to type, and it now works.

    The defect ``chess-iql`` recorded: a bare month went to the client as a URL and
    died in httpx with *"Request URL is missing an 'http://' or 'https://'
    protocol"*. The month is matched against the account's own index, so the URL
    fetched is one the service published, and the index is cached like any other
    response so a second month costs nothing.
    """
    client = two_archive_client()

    records = download_all(ACCOUNT, tmp_path, archives=["2023/11"], client=client)

    assert client.calls == [INDEX_URL, ARCHIVE_URL], "the index, then the month it named"
    assert len(records) == 8
    assert by_url(records, "https://www.chess.com/game/live/100799725125").my_color is not None
    # Both documents are real files on disk, keyed the way they always are.
    assert index_cache_path(tmp_path, ACCOUNT).is_file()
    assert archive_cache_path(tmp_path, ARCHIVE_URL).is_file()

    # A second month of the same account reuses the cached index: the only request
    # is the new month's archive, and neither the index nor the first month is
    # fetched again.
    again = StubClient({OTHER_ARCHIVE_URL: sample_text(sample_games()[:3])})
    download_all(ACCOUNT, tmp_path, archives=["2023/11", "2023/12"], client=again)
    assert again.calls == [OTHER_ARCHIVE_URL], "the index and the first month came from disk"


def test_a_full_url_is_passed_through_and_never_consults_the_index() -> None:
    """The existing form is unchanged, which is what keeps a bounded run bounded.

    Naming the month as a URL must still cost exactly one request: a cassette
    replay of that run plays one interaction, and an offline run has nothing to
    resolve.
    """
    client = StubClient()

    assert resolve_archive(ARCHIVE_URL, ACCOUNT, client=client) == ARCHIVE_URL
    assert client.calls == []
    assert resolve_archive(f"  {ARCHIVE_URL}  ", ACCOUNT, client=client) == ARCHIVE_URL
    assert client.calls == [], "surrounding whitespace is trimmed, not rejected"


def test_a_month_selector_is_a_year_a_slash_and_a_real_month() -> None:
    assert is_month_selector("2023/11")
    assert is_month_selector(" 2014/08 ")
    for value in ("2023/13", "23/11", "2023-11", "2023/11/01", "november", ARCHIVE_URL, ""):
        assert not is_month_selector(value), value


def test_a_month_the_account_never_published_is_named_as_such() -> None:
    """A month outside the index is a fact about the account, said plainly."""
    client = two_archive_client()

    with pytest.raises(UnknownArchiveError) as caught:
        month_archive_url(ACCOUNT, "2019/02", client=client)

    assert "2019/02" in str(caught.value)
    assert ACCOUNT in str(caught.value)
    assert client.calls == [INDEX_URL], "one index request, then the answer"


def test_a_selector_that_is_neither_a_url_nor_a_month_is_refused() -> None:
    """The run is stopped before the network, with a message that says what to type."""
    client = StubClient()

    with pytest.raises(UnknownArchiveError) as caught:
        resolve_archive("last-month", ACCOUNT, client=client)

    assert "YYYY/MM" in str(caught.value)
    assert client.calls == [], "nothing was fetched to find that out"


def test_an_archive_selector_failure_is_a_fetch_error() -> None:
    """``cli.py`` catches ``FetchError`` subclasses to reach its usage exit code."""
    assert issubclass(UnknownArchiveError, FetchError)
    assert issubclass(UnknownAccountError, HttpStatusError)


def test_download_all_defaults_to_the_configured_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``CHESSLEAK_CACHE_DIR`` is what an unspecified ``cache_dir`` means."""
    monkeypatch.setenv("CHESSLEAK_CACHE_DIR", str(tmp_path / "from-env"))

    download_all(ACCOUNT, client=two_archive_client())

    assert archive_cache_path(tmp_path / "from-env", ARCHIVE_URL).exists()


def test_fetch_archive_leaves_my_color_unset_without_a_username(tmp_path: Path) -> None:
    """The bead's ``fetch_archive(url)`` shape works; ``my_color`` is then unknown."""
    records = fetch_archive(ARCHIVE_URL, client=sample_client())
    assert len(records) == 8
    assert {r.my_color for r in records} == {None}

    records = fetch_archive(ARCHIVE_URL, cache_dir=tmp_path, client=sample_client())
    assert len(records) == 8
    assert records[0].my_color is None


# --- errors ----------------------------------------------------------------


def test_unknown_account_raises_a_named_error(tmp_path: Path) -> None:
    """A 404 on the index means no such public account, which the CLI maps to usage."""
    url = archives_url("nosuchplayer")
    client = StubClient({url: HttpStatusError(url, 404)})

    with pytest.raises(UnknownAccountError) as excinfo:
        list_archives("nosuchplayer", cache_dir=tmp_path, client=client)

    assert "nosuchplayer" in str(excinfo.value)
    assert excinfo.value.status_code == 404
    assert excinfo.value.url == url
    assert excinfo.value.username == "nosuchplayer"
    # Nothing was cached for a request that failed.
    assert not index_cache_path(tmp_path, "nosuchplayer").exists()


def test_archive_404_is_not_reported_as_an_unknown_account() -> None:
    """Only the index 404 means "no such account"; a missing month is a fetch error."""
    url = archives_url(ACCOUNT) + "/1999/01"
    client = StubClient({url: HttpStatusError(url, 404)})

    with pytest.raises(HttpStatusError) as excinfo:
        fetch_archive(url, ACCOUNT, client=client)

    assert not isinstance(excinfo.value, UnknownAccountError)


def test_unexpected_status_is_reported_with_its_code_and_url() -> None:
    url = archives_url(ACCOUNT)
    client = StubClient({url: HttpStatusError(url, 503, "upstream is down")})

    with pytest.raises(HttpStatusError) as excinfo:
        list_archives(ACCOUNT, client=client)

    assert excinfo.value.status_code == 503
    assert "upstream is down" in str(excinfo.value)
    assert url in str(excinfo.value)


# --- the real client, driven by a stub transport ----------------------------


def test_default_headers_describe_the_client_to_chess_com() -> None:
    """chess.com answers 403 without a descriptive User-Agent, so this is a contract."""
    headers = default_headers()

    assert "chessleak" in headers["User-Agent"]
    assert "chess.com" in headers["User-Agent"]
    assert headers["Accept"] == "application/json"


def test_client_sends_the_user_agent_and_returns_the_body() -> None:
    """One GET through a stub transport: the headers really carry the User-Agent."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"archives": []})

    client = HttpxClient(min_interval=0.0, transport=httpx.MockTransport(handler))
    try:
        assert client.get_text(INDEX_URL) == '{"archives":[]}'
    finally:
        client.close()

    assert len(seen) == 1
    assert "chessleak" in seen[0].headers["user-agent"]


def test_client_retries_a_rate_limited_request() -> None:
    """A 429 is retried rather than raised: the whole point of being polite."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"archives": ["u"]})

    client = HttpxClient(min_interval=0.0, backoff=0.0, transport=httpx.MockTransport(handler))
    try:
        assert client.get_text(INDEX_URL) == '{"archives":["u"]}'
    finally:
        client.close()

    assert calls == 2


def test_client_gives_up_after_the_attempt_budget() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "try later"})

    client = HttpxClient(min_interval=0.0, backoff=0.0, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpStatusError) as excinfo:
            client.get_text(INDEX_URL)
    finally:
        client.close()

    assert excinfo.value.status_code == 503
    assert calls == MAX_ATTEMPTS


def test_client_retries_a_dropped_connection() -> None:
    """A connection error is a retry, not a failure: the network hiccups."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("connection reset", request=request)
        return httpx.Response(200, json={"archives": []})

    client = HttpxClient(min_interval=0.0, backoff=0.0, transport=httpx.MockTransport(handler))
    try:
        assert client.get_text(INDEX_URL) == '{"archives":[]}'
    finally:
        client.close()

    assert calls == 3


def test_client_reports_a_dropped_connection_after_the_attempt_budget() -> None:
    """When the network never comes back, the failure names the URL and the reason."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    client = HttpxClient(min_interval=0.0, backoff=0.0, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpStatusError) as excinfo:
            client.get_text(INDEX_URL)
    finally:
        client.close()

    assert "transport error" in str(excinfo.value)
    assert INDEX_URL in str(excinfo.value)


def test_client_does_not_retry_a_404() -> None:
    """Retrying a missing account would only hammer the service."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"code": 0, "message": "User not found."})

    client = HttpxClient(min_interval=0.0, backoff=0.0, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(HttpStatusError) as excinfo:
            client.get_text(INDEX_URL)
    finally:
        client.close()

    assert "User not found." in str(excinfo.value)
    assert calls == 1


def test_client_waits_between_requests() -> None:
    """Requests stay serial and spaced, so a 153-archive account is not a burst."""
    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = HttpxClient(
        min_interval=0.25,
        sleep=record_sleep,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    try:
        client.get_text(INDEX_URL)  # nothing to wait for: the clock has not moved
        client.get_text(INDEX_URL)
        client.get_text(INDEX_URL)
    finally:
        client.close()

    # The first request sets the pace; every later one waits out the remainder.
    assert len(sleeps) == 2
    assert all(0 < seconds <= 0.25 for seconds in sleeps)


def test_sample_archive_is_a_layout_faithful_replica() -> None:
    """The replica mirrors the API's month-archive shape, key for key."""
    payload = json.loads(SAMPLE_ARCHIVE.read_text(encoding="utf-8"))

    assert set(payload) == {"games"}
    real_keys = {
        "url",
        "pgn",
        "time_control",
        "end_time",
        "rated",
        "tcn",
        "uuid",
        "initial_setup",
        "fen",
        "time_class",
        "rules",
        "eco",
        "white",
        "black",
    }
    optional = {"accuracies", "start_time", "eco"}
    for game in payload["games"]:
        assert set(game) <= real_keys | optional
        assert set(game) >= real_keys - optional
        assert set(game["white"]) >= {"username", "result", "@id"}
        assert set(game["black"]) >= {"username", "result", "@id"}
        assert game["pgn"].strip()
