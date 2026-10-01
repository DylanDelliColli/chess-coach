"""Opening-phase extraction: ply count, colour tagging, FEN progression, ECO, skips.

Real python-chess over the real one-game fixture this unit owns
(``tests/fixtures/game_sample.pgn``, a verbatim copy of one public chess.com
game; see ``tests/fixtures/pgn_fixtures.manifest.json``). The multi-game fixture
is exercised by ``tests/integration/test_pgnio_multigame.py``.
"""

from __future__ import annotations

import dataclasses
import io
import logging
from pathlib import Path

import chess
import chess.pgn
import pytest
from tests.game_records import make_record

from src.chessleak.pgnio import PlyRecord, extract_opening_plies, parse_game

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_PGN = FIXTURES / "game_sample.pgn"

#: The account the fixture games belong to. The sample game is one the account
#: played as Black, so a colour test that hard-codes "even plies are mine"
#: cannot pass.
ACCOUNT = "jefferyx"
MY_COLOR = "black"

#: The v1 opening window (Config.opening_plies).
WINDOW = 15


@pytest.fixture(scope="module")
def sample_text() -> str:
    """The fixture's PGN text, read from disk."""
    return SAMPLE_PGN.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sample_game(sample_text: str) -> chess.pgn.Game:
    """The fixture parsed by python-chess, asserted to have parsed cleanly."""
    game = chess.pgn.read_game(io.StringIO(sample_text))
    assert game is not None, f"{SAMPLE_PGN} did not parse"
    assert not game.errors, f"{SAMPLE_PGN} has parse errors: {game.errors}"
    return game


def shortened_pgn(game: chess.pgn.Game, plies: int) -> str:
    """The fixture game, re-exported by python-chess with only ``plies`` plies.

    The real fixture is longer than one opening window, so the rule that a
    window is capped by the game needs a short game to bite on; the moves come
    out of the fixture itself rather than being invented.
    """
    short = chess.pgn.Game(headers=dict(game.headers))
    node = short.add_variation(list(game.mainline_moves())[0])
    for move in list(game.mainline_moves())[1:plies]:
        # Follow the line; add_variation on the game itself would start a new
        # root variation each time rather than continue this one.
        node = node.add_variation(move)
    return str(short)


def test_extract_plies_count_and_mymove(sample_game: chess.pgn.Game, sample_text: str) -> None:
    """A full window, tagged by the record's colour, with shorter windows honoured."""
    mainline = list(sample_game.mainline_moves())
    assert len(mainline) > WINDOW, "the sample game must be longer than one opening window"
    assert sample_game.headers["Black"] == ACCOUNT, "the sample game must be one ACCOUNT played"

    record = make_record(
        id="182588301475",
        pgn=sample_text,
        my_color=MY_COLOR,
        eco="https://www.chess.com/openings/Queens-Gambit-Declined-Semi-Slav-Defense-Quiet-Variation",
        white=sample_game.headers["White"],
        black=ACCOUNT,
        result=sample_game.headers["Result"],
    )

    records = extract_opening_plies(record, WINDOW)

    assert len(records) == min(WINDOW, len(mainline))
    assert {r.ply_index for r in records} == set(range(WINDOW))
    assert [r.game_id for r in records] == ["182588301475"] * WINDOW
    # ACCOUNT played Black here, so the odd plies are the account's. A parser
    # that assumes "even plies are mine" fails this.
    assert [r.is_my_move for r in records] == [i % 2 == 1 for i in range(WINDOW)]

    # The other colour over the same game inverts every flag and nothing else.
    as_white = extract_opening_plies(
        make_record(id=record.id, pgn=sample_text, my_color="white"), WINDOW
    )
    assert [r.is_my_move for r in as_white] == [not r.is_my_move for r in records]
    assert [r.fen_before for r in as_white] == [r.fen_before for r in records]

    # A narrower window is a prefix of the wider one, not a resampling.
    narrow = extract_opening_plies(record, 8)
    assert len(narrow) == 8
    assert narrow == records[:8]

    # A window wider than the game stops at the end of the game.
    short = extract_opening_plies(
        make_record(id=record.id, pgn=shortened_pgn(sample_game, 3), my_color=MY_COLOR), WINDOW
    )
    assert len(short) == 3
    assert [r.move_uci for r in short] == [m.uci() for m in mainline[:3]]


def test_fen_before_progression(sample_game: chess.pgn.Game, sample_text: str) -> None:
    """Every record's fen_before is the legal position before its own move."""
    records = extract_opening_plies(
        make_record(id="182588301475", pgn=sample_text, my_color=MY_COLOR), WINDOW
    )

    board = sample_game.board()
    for index, record in enumerate(records):
        assert record.ply_index == index
        assert record.fen_before == board.fen()

        move = chess.Move.from_uci(record.move_uci)
        assert move in board.legal_moves, f"ply {index}: {record.move_uci} is not legal here"
        assert record.move_san == board.san(move)

        board.push(move)
        assert record.fen_after == board.fen()
        if index + 1 < len(records):
            # The chain is continuous: no ply starts from a position the
            # previous ply did not end in.
            assert records[index + 1].fen_before == record.fen_after

    # The window really is the opening of the game it came from.
    expected = sample_game.board()
    for move in list(sample_game.mainline_moves())[:WINDOW]:
        expected.push(move)
    assert records[-1].fen_after == expected.fen()
    # Each SAN string is unambiguous in the position it is written for, so the
    # report's move text and the engine's UCI move name the same move.
    for record in records:
        from_fen = chess.Board(record.fen_before).parse_san(record.move_san)
        assert from_fen.uci() == record.move_uci


def test_eco_precedence(sample_game: chess.pgn.Game, sample_text: str) -> None:
    """The PGN tag wins over the archive value, which is the last resort."""
    assert sample_game.headers.get("ECO"), "the sample fixture must carry an ECO tag"
    tagged = sample_game.headers["ECO"]
    archive_eco = (
        "https://www.chess.com/openings/Queens-Gambit-Declined-Semi-Slav-Defense-Quiet-Variation"
    )

    records = extract_opening_plies(
        make_record(id="1", pgn=sample_text, my_color=MY_COLOR, eco=archive_eco), 2
    )
    assert [r.eco for r in records] == [tagged, tagged]

    untagged_pgn = sample_text.replace(f'[ECO "{tagged}"]\n', "")
    assert chess.pgn.read_game(io.StringIO(untagged_pgn)).headers.get("ECO") is None
    fell_back = extract_opening_plies(
        make_record(id="1", pgn=untagged_pgn, my_color=MY_COLOR, eco=archive_eco), 2
    )
    assert [r.eco for r in fell_back] == [archive_eco, archive_eco]

    # An ECMN "?" means unknown, not a code.
    unknown = extract_opening_plies(
        make_record(
            id="1",
            pgn=untagged_pgn.replace("[Round", '[ECO "?"]\n[Round', 1),
            my_color=MY_COLOR,
            eco=archive_eco,
        ),
        1,
    )
    assert [r.eco for r in unknown] == [archive_eco]

    absent = extract_opening_plies(
        make_record(id="1", pgn=untagged_pgn, my_color=MY_COLOR, eco=None), 2
    )
    assert [r.eco for r in absent] == [None, None]


def test_parse_game_returns_the_game(sample_game: chess.pgn.Game, sample_text: str) -> None:
    """parse_game hands back the python-chess game, headers intact."""
    game = parse_game(make_record(id="1", pgn=sample_text, my_color=MY_COLOR))

    assert game is not None
    assert game.headers["Black"] == ACCOUNT
    assert len(list(game.mainline_moves())) == len(list(sample_game.mainline_moves()))


def test_ply_record_is_a_frozen_dataclass(sample_text: str) -> None:
    """Downstream units index records by value; nothing may mutate them."""
    records = extract_opening_plies(make_record(id="1", pgn=sample_text, my_color=MY_COLOR), 1)

    assert dataclasses.is_dataclass(records[0])
    assert [f.name for f in dataclasses.fields(records[0])] == [
        "game_id",
        "ply_index",
        "fen_before",
        "fen_after",
        "move_uci",
        "move_san",
        "is_my_move",
        "eco",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        records[0].is_my_move = True  # type: ignore[misc]


@pytest.mark.parametrize(
    ("pgn", "reason"),
    [
        ("", "empty"),
        ("   \n\n", "empty"),
        ('[Event "x"]\n[White "a"]\n[Black "b"]\n[Result "*"]\n\n1. e4 e5 2. Bh6 *\n', "illegal"),
        ('[Event "x"]\n[White "a"]\n[Black "b"]\n[Result "*"]\n\n1. e4 e5 2. Qxf7 *\n', "illegal"),
    ],
    ids=["empty", "whitespace-only", "illegal-move", "impossible-capture"],
)
def test_unusable_games_are_skipped_and_logged(
    pgn: str, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A game that cannot be parsed yields no records and says why, once."""
    with caplog.at_level(logging.WARNING, logger="src.chessleak.pgnio"):
        records = extract_opening_plies(make_record(id="77", pgn=pgn, my_color=MY_COLOR), WINDOW)

    assert records == []
    assert parse_game(make_record(id="77", pgn=pgn, my_color=MY_COLOR)) is None
    messages = [r.getMessage() for r in caplog.records if r.name == "src.chessleak.pgnio"]
    assert messages, "a skipped game must be logged, not dropped silently"
    assert any("77" in m for m in messages), f"the log must name the game: {messages}"
    assert any(reason in m for m in messages), f"the log must give the reason: {messages}"


def test_unknown_colour_tags_nothing_as_mine(
    sample_text: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A record whose my_color is not a colour is warned about, not guessed at."""
    with caplog.at_level(logging.WARNING, logger="src.chessleak.pgnio"):
        records = extract_opening_plies(
            make_record(id="5", pgn=sample_text, my_color="Sideways"), 4
        )

    assert len(records) == 4
    assert not any(r.is_my_move for r in records)
    assert any("5" in r.getMessage() for r in caplog.records)


def test_extract_returns_empty_for_zero_window(sample_text: str) -> None:
    """A window of zero plies is a legal, empty answer rather than an error."""
    assert extract_opening_plies(make_record(id="1", pgn=sample_text, my_color=MY_COLOR), 0) == []


def test_records_are_ply_records(sample_text: str) -> None:
    """The return type is the frozen PlyRecord, ready for severity.py/cluster.py."""
    record = extract_opening_plies(make_record(id="9", pgn=sample_text, my_color=MY_COLOR), 2)

    assert all(isinstance(r, PlyRecord) for r in record)
    assert [r.ply_index for r in record] == [0, 1]
    assert record[0].fen_before == chess.STARTING_FEN


def test_game_id_is_a_string_even_when_the_archive_id_is_an_int(sample_text: str) -> None:
    """cluster.py keys best_moves by (game_id, ply_index), so the id is a str.

    chess.com game ids are integers in the archive; PlyRecord.game_id is typed
    str so every consumer indexes the same mapping with the same key.
    """
    records = extract_opening_plies(
        make_record(id=182588301475, pgn=sample_text, my_color=MY_COLOR), 2
    )

    assert [r.game_id for r in records] == ["182588301475", "182588301475"]
    assert all(isinstance(r.game_id, str) for r in records)
