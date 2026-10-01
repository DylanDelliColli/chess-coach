"""Real Stockfish over UCI: the canary's proof that this host can run the release.

No mock, no stub: a real engine process is launched from the path
``Config.stockfish_path`` resolves to and asked for a real evaluation. If this
fails, every later unit is built on a premise this repository does not meet, so
a missing binary is a hard failure carrying the fix, not a skip.
"""

from __future__ import annotations

import os

import chess
import chess.engine
import pytest

from src.chessleak.config import Config

pytestmark = pytest.mark.integration

# White to move: the black king on h8 hides behind its own g7/h7 pawns, white
# queen on d1, white king on h1. Qd8 is the only mate in one.
MATE_IN_ONE_FEN = "7k/6pp/8/8/8/8/5PPP/3Q2K1 w - - 0 1"


@pytest.fixture(scope="module")
def engine_path() -> str:
    """The engine binary this repository's config resolves to."""
    path = Config.from_env().stockfish_path
    if not os.path.exists(path):
        pytest.fail(
            f"no Stockfish binary at {path!r}: run scripts/get_stockfish.sh, or point "
            f"CHESSLEAK_STOCKFISH_PATH at an existing binary"
        )
    return path


@pytest.fixture(scope="module")
def engine(engine_path: str):
    """A real engine process, always quit at the end of the module."""
    proc = chess.engine.SimpleEngine.popen_uci(engine_path)
    try:
        yield proc
    finally:
        proc.quit()


def test_stockfish_binary_runs(engine: chess.engine.SimpleEngine) -> None:
    """The binary identifies itself and returns a score for the start position."""
    assert engine.id.get("name"), f"engine did not report an id: {engine.id!r}"

    info = engine.analyse(chess.Board(), chess.engine.Limit(depth=6))

    assert isinstance(info, dict) and info, "engine returned no analysis info"
    score = info["score"]
    assert score is not None, f"no score in the analysis info: {info!r}"
    # python-chess 1.10+ returns a PovScore, i.e. relative to the side to move;
    # .white() is what gives the white-POV centipawns the design record freezes.
    white_cp = score.white().score()
    assert isinstance(white_cp, int)
    # A real evaluation of the start position is a small positive centipawn
    # score with a first move in the principal variation, and never a mate.
    assert 0 < white_cp < 200, f"unexpected evaluation of the start position: {white_cp}"
    assert not score.is_mate(), f"unexpected mate score from the start position: {score}"
    assert info.get("pv"), "engine returned an empty principal variation"


def test_mate_in_one_is_played(engine: chess.engine.SimpleEngine) -> None:
    """A real mate-in-one is found, and the move returned really mates.

    The mate-in-one is the design record's named proof that the engine works on
    this host, so the engine is asked to solve a position with a known answer and
    the move it returns is verified by playing it.
    """
    board = chess.Board(MATE_IN_ONE_FEN)
    info = engine.analyse(board, chess.engine.Limit(depth=8))

    score = info["score"].white()  # white-POV, as the design record fixes it
    assert score.is_mate(), f"expected a mate score for {MATE_IN_ONE_FEN}, got {score}"
    assert score.mate() == 1, f"expected mate in one, got mate in {score.mate()}"

    best = info["pv"][0]
    after = board.copy()
    after.push(best)
    assert after.is_checkmate(), f"engine's best move {best} does not mate"
    assert not list(after.legal_moves)
