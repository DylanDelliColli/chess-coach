"""chess.com public game history: fetch it once, then read it from disk.

This module owns the release's only external dependency, the chess.com Published
Data API (``https://api.chess.com/pub``), which needs **no authentication** and
publishes a player's whole public history as monthly JSON archives. Three
functions make up the surface the rest of the release uses:

* :func:`list_archives` — the archive (month) URLs for one account;
* :func:`fetch_archive` — the :class:`GameRecord` list of one monthly archive;
* :func:`download_all` — every archive of one account, cached on disk.

**The cache is the point.** chess.com returns 403 without a descriptive
``User-Agent`` and asks callers to stay serial, so this module never bursts:
:class:`HttpxClient` spaces requests (:data:`DEFAULT_MIN_INTERVAL`) and retries a
429 or a 5xx rather than hammering the service. :func:`download_all` writes each
response to ``<cache_dir>`` verbatim, keyed by the URL it came from
(:func:`archive_cache_path`), and the archives **index** under the index URL
(:func:`index_cache_path`), so a second run over an unchanged cache performs no
HTTP request at all — outcome O1 of the release. The cache is disposable:
deleting it costs time, never correctness, and an unreadable cache file is
treated as a miss rather than an error.

**Order.** The API lists archives oldest month first; :func:`download_all`
returns games **newest first** (``end_time`` descending), so a caller bounding
the run (``cli.py``'s ``--max-games``) keeps the most recent games.

**Ownership of the fields.** :class:`GameRecord` is frozen by the design record
and carries the two result strings chess.com publishes (``white_result`` /
``black_result``) verbatim alongside the PGN-style ``result`` summary
(:func:`result_summary`). ``eco`` is the *archive's* value normalised to its
label (:func:`eco_label`); the PGN's ``[ECO]`` tag takes precedence and is
read by ``pgnio.py``, which owns PGN parsing. ``my_color`` is derived by
matching the account name case-insensitively (:func:`derive_my_color`) and is
``None`` when the caller did not say whose history it is reading.

**How an archive is named.** A monthly archive can be named two ways, and both
reach the same document: the full URL, which is what the index hands out and what
``download_all`` uses when it walks the account's whole history, or the bare
month the operator would type - ``2023/11`` - which :func:`resolve_archive` turns
into a URL by asking the account's own archives index. The index is the authority
for which months exist, so a month resolves to a URL the service itself
published and a month that was never published is a fact about the account rather
than a guess at its URL shape. A full URL is passed through untouched and costs no
index request, which is what keeps a bounded, offline, cassette-replayed run
replaying exactly the interactions that were recorded.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import chess
import httpx

from src.chessleak.config import Config

__all__ = [
    "ARCHIVES_PATH_TEMPLATE",
    "CACHE_SUBDIR_ARCHIVES",
    "CACHE_SUBDIR_INDEX",
    "DEFAULT_MIN_INTERVAL",
    "DEFAULT_TIMEOUT",
    "MAX_ATTEMPTS",
    "PUB_API_BASE",
    "USER_AGENT",
    "FetchError",
    "GameRecord",
    "HttpStatusError",
    "HttpxClient",
    "TextClient",
    "UnknownAccountError",
    "UnknownArchiveError",
    "archive_cache_path",
    "archives_url",
    "cache_key",
    "default_headers",
    "derive_my_color",
    "download_all",
    "eco_label",
    "fetch_archive",
    "game_record_from_archive_json",
    "games_from_archive_json",
    "index_cache_path",
    "is_archive_url",
    "is_month_selector",
    "list_archives",
    "month_archive_url",
    "resolve_archive",
    "result_summary",
]

#: Root of the chess.com Published Data API. Nothing here ever authenticates.
PUB_API_BASE = "https://api.chess.com/pub"

#: The archives index of one account, which lists its monthly archive URLs.
ARCHIVES_PATH_TEMPLATE = "/player/{username}/games/archives"

#: chess.com answers **403** to a request without a descriptive User-Agent
#: (verified live 2026-10-01), so this string is part of the contract with the
#: service, not decoration.
USER_AGENT = (
    "chessleak/1.0 (opening-phase mistake analyzer for a chess.com player; "
    "reads the chess.com Published Data API; chess.com is the data source)"
)

DEFAULT_TIMEOUT = 30.0
#: Requests stay serial and spaced: this is the politeness budget, not a knob the
#: pipeline turns.
DEFAULT_MIN_INTERVAL = 0.5
MAX_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
#: Statuses worth waiting out. A 404 is not: retrying a missing account only
#: adds load.
RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})

#: Cache layout under ``Config.cache_dir``. The index and the monthly archives
#: are separate directories because they are separate documents.
CACHE_SUBDIR_INDEX = "archives_index"
CACHE_SUBDIR_ARCHIVES = "archives"

#: The opening label chess.com puts in the ``[ECOUrl]``/``eco`` field ends in
#: this kind of segment; the value is kept whole (see :func:`eco_label`).
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9]+")

#: A monthly archive named the way an operator types it: ``YYYY/MM``. The month is
#: range-checked, so ``2023/13`` is rejected as a mistyped month rather than looked
#: for in the index. One pattern, owned here, because ``cli.py``'s argument parser
#: validates a ``--archive`` value with the same rule before the run starts.
MONTH_SELECTOR = re.compile(r"^\d{4}/(?:0[1-9]|1[0-2])$")


class FetchError(RuntimeError):
    """Anything this module could not do: a bad status, an unusable payload."""


class HttpStatusError(FetchError):
    """A request came back with a status this module will not accept."""

    def __init__(self, url: str, status_code: int, message: str = "") -> None:
        self.url = url
        self.status_code = status_code
        detail = f": {message}" if message else ""
        super().__init__(f"{url} returned HTTP {status_code}{detail}")


class UnknownAccountError(HttpStatusError):
    """The archives index does not exist, i.e. there is no such public account.

    Raised only for a 404 on the *index*; a missing month archive stays an
    :class:`HttpStatusError`. ``cli.py`` maps this one to a usage error.
    """

    def __init__(self, username: str, url: str) -> None:
        self.username = username
        super().__init__(url, 404, f"chess.com has no public game history for {username!r}")


class UnknownArchiveError(FetchError):
    """The archive the caller named is not one the account has published.

    Two ways to get here, both about what the operator typed rather than about
    anything that went wrong mid-run: a ``--archive`` value that is neither a URL
    nor a ``YYYY/MM`` month, and a month the account's index does not list (an
    account with no games that month, or a typo). ``cli.py`` maps this to a usage
    error for the same reason it maps :class:`UnknownAccountError` there: the fix
    is at the command line.
    """

    def __init__(self, selector: str, username: str, detail: str = "") -> None:
        self.selector = selector
        self.username = username
        message = f"{selector!r} is not a monthly archive of {username!r}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class TextClient(Protocol):
    """What this module needs from an HTTP client (so tests can supply one)."""

    def get_text(self, url: str) -> str: ...


def default_headers() -> dict[str, str]:
    """The headers every chess.com request carries."""
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


class HttpxClient:
    """Serial, polite HTTP GET over :mod:`httpx`.

    One request at a time, at least :attr:`min_interval` apart, retried on a 429
    or a 5xx (honouring ``Retry-After`` when the service sends one) up to
    :data:`MAX_ATTEMPTS` times. The underlying connection is kept alive between
    requests and released by :meth:`close`.
    """

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        attempts: int = MAX_ATTEMPTS,
        backoff: float = RETRY_BACKOFF,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval = min_interval
        self.attempts = max(1, attempts)
        self.backoff = backoff
        self._transport = transport
        self._sleep = sleep
        self._last_request: float | None = None
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        """The shared connection, opened on first use."""
        if self._client is None:
            headers = default_headers()
            headers["User-Agent"] = self.user_agent
            self._client = httpx.Client(
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    def _wait_turn(self) -> None:
        """Keep the request rate under one every :attr:`min_interval` seconds."""
        if self._last_request is not None:
            remaining = self.min_interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = time.monotonic()

    def get_text(self, url: str) -> str:
        """GET ``url`` and return the body as text, retrying politely.

        A 429 or a 5xx is retried after the service's own ``Retry-After`` (or an
        exponential backoff); a dropped connection is retried the same way. A
        404 is raised at once, because retrying a missing document only adds
        load.
        """
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self._wait_turn()
            retry_after: float | None = None
            try:
                response = self._http().get(url)
            except httpx.TransportError as exc:
                last_error = HttpStatusError(url, 0, f"transport error: {exc}")
            else:
                if response.status_code == 200:
                    return response.text
                last_error = HttpStatusError(url, response.status_code, _body_message(response))
                if response.status_code not in RETRY_STATUS:
                    raise last_error
                retry_after = _retry_after(response)
            if attempt < self.attempts:
                self._sleep(self.backoff**attempt if retry_after is None else retry_after)
        assert last_error is not None  # the loop either returns or sets last_error
        raise last_error

    def close(self) -> None:
        """Release the connection. A client this module created is closed by it."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> HttpxClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _body_message(response: httpx.Response) -> str:
    """chess.com's error payload (``{"code": 0, "message": "..."}``) as one line."""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(payload, Mapping) and payload.get("message"):
        return str(payload["message"])
    return response.text.strip()[:200]


def _retry_after(response: httpx.Response) -> float | None:
    """The service's own pacing hint, when it sent a usable one."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return max(0.0, min(seconds, 60.0))


@contextmanager
def _client_scope(client: TextClient | None = None) -> Iterator[TextClient]:
    """Use the caller's client, or make one this call owns and closes."""
    if client is not None:
        yield client
        return
    owned = HttpxClient()
    try:
        yield owned
    finally:
        owned.close()


# --- the record ------------------------------------------------------------


@dataclass(frozen=True)
class GameRecord:
    """One game as chess.com publishes it, mapped for the pipeline.

    The field set is frozen by the design record: ``id, pgn, eco, white, black,
    result, white_result, black_result, time_control, my_color, end_time,
    white_rating, black_rating, rules, initial_setup``.

    ``result`` is the PGN-style ``1-0`` / ``0-1`` / ``1/2-1/2`` summary, while
    ``white_result`` / ``black_result`` keep chess.com's own words verbatim
    (``win``, ``resigned``, ``timeout``, ``agreed``, …) because the report shows
    how a game ended.

    ``eco`` is the archive's opening label, or ``None`` when the archive has none
    (roughly one game in eight); ``pgnio.py`` prefers the PGN's ``[ECO]`` tag.

    ``my_color`` is ``"white"``, ``"black"``, or ``None`` when the caller did not
    name the account (``fetch_archive(url)``).

    ``rules`` and ``initial_setup`` decide whether a game can recur at all, so
    they are carried rather than filtered here: an absent value means an ordinary
    standard game.
    """

    id: str
    pgn: str
    eco: str | None
    white: str
    black: str
    result: str
    white_result: str
    black_result: str
    time_control: str
    my_color: str | None
    end_time: int | None
    white_rating: int | None
    black_rating: int | None
    rules: str
    initial_setup: str

    @property
    def opponent(self) -> str:
        """The player this record is *not* about, whichever colour the caller is."""
        if self.my_color == "white":
            return self.black
        if self.my_color == "black":
            return self.white
        return ""

    @property
    def is_standard_chess(self) -> bool:
        """True when the game is ordinary chess from the standard position.

        A variant or a custom starting position can never recur across the
        player's games, so the design record has every consumer skip those. The
        judgment lives here on the record; deciding to skip a run of games is
        ``cli.py``'s job, and it counts them in ``summary.games_skipped``.
        """
        return self.rules == "chess" and self.initial_setup == chess.STARTING_FEN


def derive_my_color(white: str | None, black: str | None, username: str | None) -> str | None:
    """Which side of a game the account owner played, or ``None`` if neither.

    The match is case-insensitive, because chess.com keeps the case a player
    registered and the caller usually types the name in lower case. Same name on
    both sides cannot happen on chess.com; white wins that tie so a record is
    never left without a perspective.
    """
    if not username or not username.strip():
        return None
    wanted = username.strip().casefold()
    if white and white.strip().casefold() == wanted:
        return "white"
    if black and black.strip().casefold() == wanted:
        return "black"
    return None


def result_summary(white_result: str | None, black_result: str | None) -> str:
    """chess.com's two result words as one PGN-style result.

    chess.com reports the outcome per colour ("win" for the winner, and then how
    the game ended for the loser). Exactly one side can be ``"win"``; if neither
    is, the game was drawn. The words themselves are kept verbatim on the record.
    """
    if (white_result or "").strip().casefold() == "win":
        return "1-0"
    if (black_result or "").strip().casefold() == "win":
        return "0-1"
    return "1/2-1/2"


def eco_label(eco: str | None) -> str | None:
    """The opening label in the archive's ``eco`` field.

    chess.com publishes an opening *URL* whose last segment is the label
    (``Four-Knights-Game``, ``Englund-Gambit-2.dxe5``); that segment is what a
    report can show when the PGN carried no ``[ECO]`` tag. A blank or missing
    value is ``None``: about one real game in eight has no ECO anywhere, and the
    report renders that as ``—``.
    """
    if eco is None:
        return None
    label = eco.strip()
    if not label:
        return None
    return urlsplit(label).path.rstrip("/").rsplit("/", 1)[-1] or None


def _result_word(value: Any) -> str:
    """chess.com's result word, kept verbatim (whitespace trimmed)."""
    return str(value).strip() if value is not None else ""


def _int_or_none(value: Any) -> int | None:
    """An integer field, or ``None`` for the API's ``null`` (an unrated game).

    A missing rating must stay ``None`` rather than become ``0``: zero is a real
    rating and would read as a genuinely terrible player.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def game_record_from_archive_json(
    game: Mapping[str, Any], username: str | None = None
) -> GameRecord:
    """Map one game object of a monthly archive to a :class:`GameRecord`."""
    if not isinstance(game, Mapping):
        raise FetchError(f"expected a game object, got {type(game).__name__}")
    white = game.get("white") or {}
    black = game.get("black") or {}
    if not isinstance(white, Mapping) or not isinstance(black, Mapping):
        raise FetchError(f"game {game.get('url')!r} has a malformed player object")
    white_name = str(white.get("username") or "")
    black_name = str(black.get("username") or "")
    return GameRecord(
        id=str(game.get("url") or ""),
        pgn=str(game.get("pgn") or ""),
        eco=eco_label(game.get("eco")),
        white=white_name,
        black=black_name,
        result=result_summary(white.get("result"), black.get("result")),
        white_result=_result_word(white.get("result")),
        black_result=_result_word(black.get("result")),
        time_control=str(game.get("time_control") or ""),
        my_color=derive_my_color(white_name, black_name, username),
        end_time=_int_or_none(game.get("end_time")),
        white_rating=_int_or_none(white.get("rating")),
        black_rating=_int_or_none(black.get("rating")),
        # Absent means "an ordinary game": the design record skips variants, not
        # games whose archive entry is merely terse.
        rules=str(game.get("rules") or "chess"),
        initial_setup=str(game.get("initial_setup") or chess.STARTING_FEN),
    )


def games_from_archive_json(payload: Any, username: str | None = None) -> list[GameRecord]:
    """Map a whole monthly archive document to :class:`GameRecord`\\ s."""
    games = payload.get("games") if isinstance(payload, Mapping) else None
    if games is None:
        shape = sorted(payload) if isinstance(payload, Mapping) else type(payload).__name__
        raise FetchError(f"expected a monthly archive with a 'games' list, got {shape}")
    if not isinstance(games, Sequence):
        raise FetchError(f"expected 'games' to be a list, got {type(games).__name__}")
    return [game_record_from_archive_json(game, username) for game in games]


# --- cache layout ----------------------------------------------------------


def archives_url(username: str) -> str:
    """The archives index URL of one account."""
    return f"{PUB_API_BASE}{ARCHIVES_PATH_TEMPLATE.format(username=username)}"


def cache_key(url: str) -> str:
    """A stable, path-safe filename for a cached URL.

    Readable on purpose (the slug of the URL) and collision-free on purpose (the
    slug alone could map ``/a/b`` and ``/a_b`` to the same name), so the key is
    slug plus a short hash of the exact URL.
    """
    parsed = urlsplit(url)
    slug = _FILENAME_SAFE.sub("_", f"{parsed.netloc}{parsed.path}").strip("_")[:96]
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}.json"


def index_cache_path(cache_dir: str | Path, username: str) -> Path:
    """Where an account's archives index is cached.

    The name is folded to lower case, because chess.com treats usernames
    case-insensitively: one account must not end up with two index caches
    because the operator typed the name differently than the environment did.
    """
    url = archives_url(username.strip().casefold())
    return Path(cache_dir).expanduser() / CACHE_SUBDIR_INDEX / cache_key(url)


def archive_cache_path(cache_dir: str | Path, url: str) -> Path:
    """Where one monthly archive is cached, keyed by the URL it came from."""
    return Path(cache_dir).expanduser() / CACHE_SUBDIR_ARCHIVES / cache_key(url)


def _cache_dir(cache_dir: str | Path | None) -> Path | None:
    """The cache root the caller asked for; ``None`` means "do not cache"."""
    return None if cache_dir is None else Path(cache_dir).expanduser()


def _default_cache_dir() -> Path:
    """The cache root :func:`download_all` uses when the caller named none.

    ``Config.from_env().cache_dir``, so ``CHESSLEAK_CACHE_DIR`` moves the whole
    pipeline's cache the same way it moves the eval cache.
    """
    return Path(Config.from_env().cache_dir).expanduser()


def _read_cache(path: Path) -> str | None:
    """A cached response body, or ``None`` when there is nothing usable.

    A cache is a convenience, so a missing file, an unreadable one and one cut
    short by an interrupted write all mean the same thing: fetch it again.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _write_cache(path: Path, text: str) -> None:
    """Store a response body verbatim, atomically.

    The bytes are written as they arrived (this is the archive the design record
    calls raw), through a temporary file in the same directory so an interrupted
    write can never leave a half-written cache file behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _cached_json(url: str, path: Path | None, cache_dir: Path | None, client: TextClient) -> Any:
    """The parsed JSON of ``url``: from the cache when it is there, else HTTP.

    ``path`` and ``cache_dir`` are both ``None`` when the caller did not ask for
    caching, in which case this is a plain request.
    """
    if cache_dir is None or path is None:
        return _decode(client.get_text(url), url)
    cached = _read_cache(path)
    if cached is not None:
        try:
            return json.loads(cached)
        except ValueError:
            pass  # unreadable cache: fall through and fetch it again
    text = client.get_text(url)
    _write_cache(path, text)
    return _decode(text, url)


def _decode(text: str, url: str) -> Any:
    """Parse a response body, naming the URL when it is not JSON."""
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FetchError(f"{url} did not return JSON: {exc}") from None


# --- the public API --------------------------------------------------------


def list_archives(
    username: str,
    *,
    cache_dir: str | Path | None = None,
    client: TextClient | None = None,
) -> list[str]:
    """The account's monthly archive URLs, oldest month first (the API's order).

    With ``cache_dir`` the index is cached under the index URL, which is what
    lets :func:`download_all` make no HTTP request at all on a second run. An
    account that has published no games yields an empty list; an account that
    does not exist raises :class:`UnknownAccountError`.
    """
    url = archives_url(username)
    root = _cache_dir(cache_dir)
    with _client_scope(client) as active:
        try:
            payload = _cached_json(
                url,
                None if root is None else index_cache_path(root, username),
                root,
                active,
            )
        except HttpStatusError as exc:
            if exc.status_code == 404:
                raise UnknownAccountError(username, url) from None
            raise
    archives = payload.get("archives") if isinstance(payload, Mapping) else None
    if archives is None:
        raise FetchError(f"{url} did not return an 'archives' list")
    return [str(item) for item in archives]


def fetch_archive(
    url: str,
    username: str | None = None,
    *,
    cache_dir: str | Path | None = None,
    client: TextClient | None = None,
) -> list[GameRecord]:
    """Every game of one monthly archive, mapped to :class:`GameRecord`.

    ``username`` is whose history this is: it is what :func:`derive_my_color`
    matches against, and without it every record's ``my_color`` is ``None``.
    With ``cache_dir`` the archive is cached under its own URL.
    """
    root = _cache_dir(cache_dir)
    with _client_scope(client) as active:
        payload = _cached_json(
            url, None if root is None else archive_cache_path(root, url), root, active
        )
    return games_from_archive_json(payload, username)


def is_archive_url(value: str) -> bool:
    """Whether ``value`` is an absolute http(s) URL with a host."""
    parsed = urlsplit(value.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_month_selector(value: str) -> bool:
    """Whether ``value`` is a bare ``YYYY/MM`` month, the way an operator types one."""
    return MONTH_SELECTOR.match(value.strip()) is not None


def month_archive_url(
    username: str,
    month: str,
    *,
    cache_dir: str | Path | None = None,
    client: TextClient | None = None,
) -> str:
    """The URL of one ``YYYY/MM`` month of an account, from its own archives index.

    The index is the authority on which months an account has published, so the
    month is matched against it rather than pasted into a URL template: the answer
    is a URL the service itself handed out, and a month it never published is
    reported as such instead of producing a 404 from a guessed address.

    :raises UnknownArchiveError: ``month`` is not in the index, so the account has
        no public archive for it.
    """
    wanted = month.strip()
    published = list_archives(username, cache_dir=cache_dir, client=client)
    suffix = f"/games/{wanted}"
    for url in published:
        if urlsplit(url).path.endswith(suffix):
            return url
    raise UnknownArchiveError(
        wanted,
        username,
        f"that month is not among the {len(published)} month(s) the account has published",
    )


def resolve_archive(
    selector: str,
    username: str,
    *,
    cache_dir: str | Path | None = None,
    client: TextClient | None = None,
) -> str:
    """One ``--archive`` value as the URL to fetch.

    A full URL is returned untouched and costs nothing - no index request, so a run
    that names its month outright replays exactly the interactions that were
    recorded and no others. A bare ``YYYY/MM`` month is resolved through the
    account's index (:func:`month_archive_url`); that is the one case where a
    bounded run needs a second request, and it buys the run the ability to name a
    month the way a person says it.

    :raises UnknownArchiveError: the value is neither a URL nor a month, or the
        month is not one the account published.
    """
    value = selector.strip()
    if is_archive_url(value):
        return value
    if is_month_selector(value):
        return month_archive_url(username, value, cache_dir=cache_dir, client=client)
    raise UnknownArchiveError(
        selector,
        username,
        "expected a monthly archive URL or a YYYY/MM month such as 2023/11",
    )


def download_all(
    username: str,
    cache_dir: str | Path | None = None,
    *,
    archives: Sequence[str] | None = None,
    client: TextClient | None = None,
) -> list[GameRecord]:
    """Every game of one account, cached on disk, newest game first.

    Enumerates the archives (unless ``archives`` gives them outright), downloads
    each one that is not cached yet, and returns the whole history as one list.
    A second run over an unchanged cache makes no HTTP request: the archives
    index is cached by account and each monthly archive by URL. ``cache_dir``
    defaults to ``Config.cache_dir``, so this is the one call that always caches.

    Each entry of ``archives`` is a selector rather than necessarily a URL: a full
    URL is used as it stands, and a bare ``YYYY/MM`` month is resolved against the
    account's index (:func:`resolve_archive`). Games are returned newest first
    (``end_time`` descending), and a game listed in two archives appears once, so
    a caller that bounds the run keeps the most recent games.
    """
    root = _cache_dir(cache_dir) or _default_cache_dir()
    with _client_scope(client) as active:
        if archives is None:
            urls = list(reversed(list_archives(username, cache_dir=root, client=active)))
        else:
            urls = [
                resolve_archive(selector, username, cache_dir=root, client=active)
                for selector in archives
            ]
        games: list[GameRecord] = []
        seen: set[str] = set()
        for url in urls:
            for record in fetch_archive(url, username, cache_dir=root, client=active):
                if record.id in seen:
                    continue
                seen.add(record.id)
                games.append(record)
    games.sort(key=lambda record: record.end_time or 0, reverse=True)
    return games
