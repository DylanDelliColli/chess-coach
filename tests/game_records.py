"""Building ``fetch.GameRecord`` values for tests that have no fetcher.

``pgnio.py`` is written against the *shape* of the record the design record
froze for ``fetch.GameRecord`` (``id``, ``pgn``, ``eco``, ``my_color``, …) and
imports nothing from ``fetch.py``, so the extraction unit can be exercised
before or after the fetch unit lands, and downstream units can build records
without a network round trip.

:func:`record_type` returns ``fetch.GameRecord`` when that module is importable
and a local stand-in with the same field names otherwise, so a test written
against this helper keeps passing either way.
"""

from __future__ import annotations

import dataclasses
from typing import Any

__all__ = ["GameRecord", "make_record", "record_type"]

#: The field names the design record freezes for ``fetch.GameRecord``. Values
#: the caller does not supply get these neutral defaults; the frozen names the
#: installed ``GameRecord`` does not have are dropped rather than passed.
_DEFAULTS: dict[str, Any] = {
    "id": "",
    "pgn": "",
    "eco": None,
    "white": "",
    "black": "",
    "result": "",
    "white_result": "",
    "black_result": "",
    "time_control": "",
    "my_color": "",
    "end_time": 0,
    "white_rating": None,
    "black_rating": None,
    "rules": "chess",
    "initial_setup": "",
}


@dataclasses.dataclass(frozen=True)
class GameRecord:
    """Stand-in for ``fetch.GameRecord``, used until (and unless) it exists."""

    id: str = ""
    pgn: str = ""
    eco: str | None = None
    white: str = ""
    black: str = ""
    result: str = ""
    white_result: str = ""
    black_result: str = ""
    time_control: str = ""
    my_color: str = ""
    end_time: int = 0
    white_rating: int | None = None
    black_rating: int | None = None
    rules: str = "chess"
    initial_setup: str = ""


def record_type() -> type:
    """The real ``fetch.GameRecord`` when it has landed, else the stand-in."""
    try:
        from src.chessleak.fetch import GameRecord as FetchGameRecord
    except ImportError:
        return GameRecord
    return FetchGameRecord


def make_record(**overrides: Any) -> Any:
    """Build a record with the frozen field names, ignoring ones the type lacks."""
    values = {**_DEFAULTS, **overrides}
    cls = record_type()
    known = {f.name for f in dataclasses.fields(cls)} if dataclasses.is_dataclass(cls) else None
    if known is not None:
        values = {k: v for k, v in values.items() if k in known}
    return cls(**values)
