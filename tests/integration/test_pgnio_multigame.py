"""Real multi-game PGN extraction end to end, no mocks.

``tests/fixtures/games_multi.pgn`` is a verbatim copy of twenty consecutive
games out of one real chess.com public monthly archive, and
``tests/fixtures/pgn_fixtures.manifest.json`` records which archive, which day
and which games. This test reads both files from disk, parses them with real
python-chess and runs the real extractor over every game: real PGN text, real
records, real FENs, no stub of anything the unit under test composes.
"""

from __future__ import annotations

import io
import json
import re
from collections import Counter
from pathlib import Path

import chess
import chess.pgn
import pytest
from tests.game_records import make_record

from src.chessleak.config import position_key
from src.chessleak.pgnio import extract_opening_plies

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MULTI_PGN = FIXTURES / "games_multi.pgn"
MANIFEST = FIXTURES / "pgn_fixtures.manifest.json"

#: The account whose public archive the fixture was copied from.
ACCOUNT = "jefferyx"
#: The v1 opening window (Config.opening_plies).
WINDOW = 15

#: chess.com tags openings with an ECMN code such as ``D30``.
ECO_CODE = re.compile(r"^[A-E]\d{2}$")


@pytest.fixture(scope="module")
def manifest() -> dict:
    """The recorded provenance of both PGN fixtures."""
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pgn_text() -> str:
    """The multi-game fixture's PGN text, read from disk."""
    return MULTI_PGN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pgn_chunks(pgn_text: str) -> list[str]:
    """The fixture split into one verbatim text block per game.

    The extractor is handed the bytes the fixture holds for that game, not a
    re-export, so the chess.com headers and ``{[%clk]}`` comments are what get
    parsed.
    """
    starts = [match.start() for match in re.finditer(r"(?m)^\[Event ", pgn_text)]
    assert len(starts) > 1, "the fixture does not look like a multi-game export"
    chunks = [
        pgn_text[start:end].rstrip("\n") + "\n"
        for start, end in zip(starts, starts[1:], strict=False)
    ]
    chunks.append(pgn_text[starts[-1] :].rstrip("\n") + "\n")
    return chunks


@pytest.fixture(scope="module")
def fixture_games(pgn_chunks: list[str]) -> list[chess.pgn.Game]:
    """Every game in the fixture, parsed by python-chess, in archive order."""
    games = []
    for chunk in pgn_chunks:
        games.append(chess.pgn.read_game(io.StringIO(chunk)))
    assert all(games), "a chunk of the fixture parsed to no game"
    return games


def record_for(pgn: str, entry: dict) -> object:
    """The record ``fetch.py`` would build for one archived game."""
    return make_record(
        id=entry["game_id"],
        pgn=pgn,
        my_color=entry["account_side"],
        eco=entry["eco_url"],
        white=entry["white"],
        black=entry["black"],
        result=entry["result"],
        time_control=entry["time_control"],
        rules="chess",
    )


def test_extract_real_multigame_pgn(
    fixture_games: list[chess.pgn.Game],
    pgn_chunks: list[str],
    manifest: dict,
) -> None:
    """Twenty real games become correctly tagged, legally chained ply records."""
    entry = manifest["games_multi.pgn"]
    entries = entry["games"]

    # The fixture is what the manifest says it is: real chess.com games, in the
    # recorded order, each carrying its own identifiers and archive metadata.
    assert manifest["source"]["account"] == ACCOUNT
    assert len(fixture_games) == len(pgn_chunks) == entry["game_count"] == len(entries) == 20
    assert all(not game.errors for game in fixture_games), "a fixture game failed to parse"
    for game, recorded in zip(fixture_games, entries, strict=True):
        game_id = game.headers["Link"].rsplit("/", 1)[-1]
        assert game_id == recorded["game_id"]
        assert game.headers["Link"] == recorded["url"]
        assert game.headers["Site"] == "Chess.com"
        assert game.headers["White"] == recorded["white"]
        assert game.headers["Black"] == recorded["black"]
        # The account's colour is read off the game, and it must match the
        # manifest: a fixture reordered or edited would fail here.
        assert recorded["account_side"] == (
            "white" if game.headers["White"] == ACCOUNT else "black"
        )
        # The manifest's archive ECO URL is the game's own ECOUrl tag, i.e. the
        # record's fallback label really is the archive's value.
        assert recorded["eco_url"] == game.headers["ECOUrl"]
    assert {recorded["account_side"] for recorded in entries} == {"white", "black"}, (
        "the fixture must exercise both colours"
    )

    expected_total = sum(min(WINDOW, len(list(game.mainline_moves()))) for game in fixture_games)
    per_game: dict[str, list] = {}
    for pgn, recorded in zip(pgn_chunks, entries, strict=True):
        per_game[recorded["game_id"]] = extract_opening_plies(record_for(pgn, recorded), WINDOW)

    # Total PlyRecords across games, counted from the real parse, not a constant.
    all_records = [record for records in per_game.values() for record in records]
    assert len(all_records) == expected_total == 20 * WINDOW

    mine = Counter(record.game_id for record in all_records if record.is_my_move)
    for game, recorded in zip(fixture_games, entries, strict=True):
        records = per_game[recorded["game_id"]]
        assert len(records) == min(WINDOW, len(list(game.mainline_moves())))
        # The account played the recorded colour in this real game, so its own
        # plies alternate with the opponent's from that colour's first turn.
        first_ply_is_mine = recorded["account_side"] == "white"
        assert mine[recorded["game_id"]] == sum(
            1 for i in range(len(records)) if (i % 2 == 0) == first_ply_is_mine
        )
    assert any(record.is_my_move for record in all_records)
    assert any(not record.is_my_move for record in all_records)

    # ECO is populated on every record of these real games, and it is the PGN
    # tag's code rather than the chess.com opening URL the archive carries.
    assert all(record.eco is not None for record in all_records)
    assert all(ECO_CODE.match(record.eco) for record in all_records)
    assert {record.eco for record in all_records} >= {"D30", "B07", "C02"}

    # Every fen_before is the position its own move is legal in, and the chain
    # of records is the real game line: nothing is invented or reordered.
    for game, recorded in zip(fixture_games, entries, strict=True):
        board = game.board()
        for index, record in enumerate(per_game[recorded["game_id"]]):
            assert record.ply_index == index
            assert record.fen_before == board.fen()
            move = chess.Move.from_uci(record.move_uci)
            assert move in board.legal_moves, f"{record.game_id} ply {index}: illegal {move}"
            assert record.move_san == board.san(move)
            board.push(move)
            assert record.fen_after == board.fen()

    # The opening really does recur across these games, which is what the
    # clustering unit consumes: one position key reached in several games.
    games_per_key = Counter()
    for recorded in entries:
        games_per_key.update({position_key(r.fen_before) for r in per_game[recorded["game_id"]]})
    assert max(games_per_key.values()) >= 2, "no opening position recurs in the fixture"
