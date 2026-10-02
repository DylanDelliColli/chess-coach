"""Configuration for chessleak, frozen before the units that consume it.

Every other module of the release imports :class:`Config` from here, so the field
names, the defaults and the ``CHESSLEAK_*`` variables are a contract fixed by
the design record. A unit that needs another setting proposes it on its own bead
rather than editing this dataclass, so parallel units do not collide.

Defaults and the variables that override them:

======================  ======================  ============================  ===================
field                   default                 variable                      alias
``username``            ``""``                  ``CHESSLEAK_USERNAME``
``stockfish_path``      resolved below          ``CHESSLEAK_STOCKFISH_PATH``
``analysis_depth``      ``18``                  ``CHESSLEAK_ANALYSIS_DEPTH``  ``CHESSLEAK_DEPTH``
``opening_plies``       ``15``                  ``CHESSLEAK_OPENING_PLIES``
``cache_dir``           ``~/.cache/chessleak``  ``CHESSLEAK_CACHE_DIR``
``win_prob_k``          ``0.004``               ``CHESSLEAK_WIN_PROB_K``
``book_band_cp``        ``30``                  ``CHESSLEAK_BOOK_BAND_CP``
``top_n``               ``20``                  ``CHESSLEAK_TOP_N``
``max_games``           ``None``                (none: a run-bound, not a setting)
``archives``            ``()``                  (none: the whole history)
======================  ======================  ============================  ===================

``CHESSLEAK_ANALYSIS_DEPTH`` is the canonical name; ``CHESSLEAK_DEPTH`` is kept
as an alias and only read when the canonical name is unset.

**``max_games`` and ``archives`` are added by the CLI unit** (``chess-uow``, U8),
which is why they carry no ``CHESSLEAK_*`` variable: they bound *one run* rather
than describe the installation, so an environment variable would leave a stale
bound behind on every later command. They were added additively, with defaults,
after every other unit had merged, so nothing above them changed.
``max_games=None`` is unlimited; ``archives=()`` is the account's whole published
history, and a non-empty tuple is the list of monthly archive URLs to read
instead.

This module also exports :func:`position_key`, the one position-identity function
the release shares. ``board.fen()`` ends in the halfmove clock and the fullmove
number, so the same board reached by transposition at a different move count is a
different string; keying the eval cache and the clusters on that string splits one
position into several. ``engine.py`` and ``cluster.py`` import
:func:`position_key` from here rather than re-deriving it. (``pgnio.py`` does not:
``PlyRecord`` is frozen with no key field, so it carries the full FEN and its consumers
derive the key themselves. Corrected by the chief on 2026-10-01 at the wave boundary,
after U3 reported the discrepancy.)

``stockfish_path`` resolves in the order the design record froze:
``CHESSLEAK_STOCKFISH_PATH``, then the shared binary that
``scripts/get_stockfish.sh`` installs (``CHESSLEAK_STOCKFISH_ROOT``, default
``~/.local/share/chessleak/stockfish``), then ``stockfish`` on ``PATH``. When
nothing is found the shared location is returned anyway, so the failure a caller
sees names the one binary this project knows how to install. ``~`` is expanded
in both path fields.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Config",
    "position_key",
    "DEFAULT_ANALYSIS_DEPTH",
    "DEFAULT_BOOK_BAND_CP",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_OPENING_PLIES",
    "DEFAULT_STOCKFISH_DIR",
    "DEFAULT_TOP_N",
    "DEFAULT_WIN_PROB_K",
    "EVAL_CACHE_FILENAME",
    "default_stockfish_path",
    "stockfish_root",
    "resolve_stockfish_path",
]

#: Documented defaults. The path defaults keep the ``~`` so they read the same in
#: a dataclass signature, a CLI help string and this docstring.
DEFAULT_CACHE_DIR = "~/.cache/chessleak"
DEFAULT_STOCKFISH_DIR = "~/.local/share/chessleak/stockfish"
DEFAULT_ANALYSIS_DEPTH = 18
DEFAULT_OPENING_PLIES = 15
DEFAULT_WIN_PROB_K = 0.004
DEFAULT_BOOK_BAND_CP = 30
DEFAULT_TOP_N = 20

#: The eval cache filename the design record pins inside ``cache_dir``.
EVAL_CACHE_FILENAME = "evalcache.sqlite"

ENV_USERNAME = "CHESSLEAK_USERNAME"
ENV_STOCKFISH_PATH = "CHESSLEAK_STOCKFISH_PATH"
ENV_STOCKFISH_ROOT = "CHESSLEAK_STOCKFISH_ROOT"
#: Canonical name, then the alias the first cut of this module shipped.
ENV_ANALYSIS_DEPTH = "CHESSLEAK_ANALYSIS_DEPTH"
ENV_ANALYSIS_DEPTH_ALIAS = "CHESSLEAK_DEPTH"
ENV_OPENING_PLIES = "CHESSLEAK_OPENING_PLIES"
ENV_CACHE_DIR = "CHESSLEAK_CACHE_DIR"
ENV_WIN_PROB_K = "CHESSLEAK_WIN_PROB_K"
ENV_BOOK_BAND_CP = "CHESSLEAK_BOOK_BAND_CP"
ENV_TOP_N = "CHESSLEAK_TOP_N"

_ENGINE_NAME = "stockfish"


def _env(env: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    """Read a variable, treating an empty or whitespace-only value as unset."""
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _env(env, name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from None


def _depth_from_env(env: Mapping[str, str], default: int) -> int:
    """Read the analysis depth: canonical name first, then its alias.

    A non-numeric value raises ``ValueError`` naming whichever variable supplied
    it, so the message points at the name the operator actually set.
    """
    for name in (ENV_ANALYSIS_DEPTH, ENV_ANALYSIS_DEPTH_ALIAS):
        raw = _env(env, name)
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{name} must be an integer, got {raw!r}") from None
    return default


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _env(env, name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None


def _expand(path: str) -> str:
    return str(Path(path).expanduser())


def position_key(fen: str) -> str:
    """The identity of a position: placement, side to move, castling, ep square.

    ``board.fen()`` appends the halfmove clock and the fullmove number, so the
    same board reached by transposition at a different move count is a different
    string; keying an eval cache or a cluster on the raw FEN splits one position
    into several entries. The design record pins the key as the first four FEN
    fields. Nothing else in the release re-derives it.

    The en passant square stays in the key even when no capture is available for
    it, because FEN records the double push, not its consequences.

    The key is also what ``engine.py`` *searches*: a board is handed to Stockfish
    with its halfmove clock and fullmove number cleared, because Stockfish reads
    ``rule50`` from the FEN and would otherwise answer two different searches for
    one position. Nothing here derives a second identity for the same board.
    """
    return " ".join(fen.split()[:4])


def stockfish_root(env: Mapping[str, str] | None = None) -> Path:
    """The shared directory ``scripts/get_stockfish.sh`` installs into."""
    env = os.environ if env is None else env
    return Path(_env(env, ENV_STOCKFISH_ROOT, DEFAULT_STOCKFISH_DIR)).expanduser()


def default_stockfish_path() -> str:
    """The engine path used when nothing else is configured."""
    return str(stockfish_root() / _ENGINE_NAME)


def resolve_stockfish_path(env: Mapping[str, str] | None = None) -> str:
    """Resolve the Stockfish binary: explicit variable, shared install, then PATH."""
    env = os.environ if env is None else env

    explicit = _env(env, ENV_STOCKFISH_PATH)
    if explicit is not None:
        return _expand(explicit)

    shared = stockfish_root(env) / _ENGINE_NAME
    if shared.exists():
        return str(shared)

    on_path = shutil.which(_ENGINE_NAME)
    if on_path is not None:
        return on_path

    return str(shared)


@dataclass(frozen=True)
class Config:
    """Everything the pipeline needs to run, as one immutable value."""

    username: str = ""
    stockfish_path: str = field(default_factory=default_stockfish_path)
    analysis_depth: int = DEFAULT_ANALYSIS_DEPTH
    opening_plies: int = DEFAULT_OPENING_PLIES
    cache_dir: str = DEFAULT_CACHE_DIR
    win_prob_k: float = DEFAULT_WIN_PROB_K
    book_band_cp: int = DEFAULT_BOOK_BAND_CP
    top_n: int = DEFAULT_TOP_N
    #: How many of the account's most recent games this run analyses, or ``None``
    #: for all of them. ``download_all`` returns games newest first, so a bound
    #: keeps the most recent games - the ones whose openings the player is still
    #: playing. The bound is on *analysis*, not on downloading: the whole history
    #: is cached on the first run, so a later run costs no network at all.
    max_games: int | None = None
    #: The monthly archive URLs to read instead of enumerating the account's
    #: index. Empty means "the whole published history", which is the default for
    #: every real run; a non-empty tuple is how a caller analyses one month.
    archives: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a Config from ``CHESSLEAK_*`` variables (the process environment by default).

        A non-numeric value raises ``ValueError`` naming the variable, so a
        mistyped depth fails at the edge instead of deep inside the engine.
        """
        env = os.environ if env is None else env
        return cls(
            username=_env(env, ENV_USERNAME, "") or "",
            stockfish_path=resolve_stockfish_path(env),
            analysis_depth=_depth_from_env(env, DEFAULT_ANALYSIS_DEPTH),
            opening_plies=_env_int(env, ENV_OPENING_PLIES, DEFAULT_OPENING_PLIES),
            cache_dir=_expand(_env(env, ENV_CACHE_DIR, DEFAULT_CACHE_DIR) or DEFAULT_CACHE_DIR),
            win_prob_k=_env_float(env, ENV_WIN_PROB_K, DEFAULT_WIN_PROB_K),
            book_band_cp=_env_int(env, ENV_BOOK_BAND_CP, DEFAULT_BOOK_BAND_CP),
            top_n=_env_int(env, ENV_TOP_N, DEFAULT_TOP_N),
        )

    @property
    def cache_path(self) -> Path:
        """``cache_dir`` as a usable path (``~`` expanded), created on demand by callers."""
        return Path(self.cache_dir).expanduser()

    @property
    def evalcache_path(self) -> Path:
        """The persistent eval cache at ``<cache_dir>/evalcache.sqlite`` (design record)."""
        return self.cache_path / EVAL_CACHE_FILENAME
