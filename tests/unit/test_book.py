"""The book trigger: which player move first leaves engine-best, and by how much.

The stub engine here is duck-typed on ``analyse(fen) -> EvalResult``, which is
what the design record freezes for ``first_deviation``'s ``engine`` argument, and
it builds its answers out of the *real* python-chess score types:
``PovScore(Cp(x), board.turn)`` read through ``.white()``, exactly as
``engine.py`` does. A stub that handed back plain integers would pass while the
sign rule was broken, because the trap only shows on a board where the other side
is to move.

The records are real :class:`PlyRecord` values produced by the real extractor
from real PGN text, so this file exercises the seam between the two units rather
than a look-alike dataclass.
"""

from __future__ import annotations

import dataclasses
import io
import logging

import chess
import chess.engine as ce
import chess.pgn
import pytest
from tests.game_records import make_record

from src.chessleak.book import MATE_CP, DeviationFlag, first_deviation
from src.chessleak.config import DEFAULT_BOOK_BAND_CP, Config, position_key
from src.chessleak.engine import EvalResult
from src.chessleak.pgnio import extract_opening_plies

pytestmark = pytest.mark.unit

DEPTH = 18
BAND = DEFAULT_BOOK_BAND_CP

#: Seven quiet Italian plies the player follows, then the move that leaves the
#: band. This is the same opening the real-engine test walks, so the unit test
#: and the integration test describe one situation.
BOOK_LINE = "1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a5 8. Nxe5"

#: A black-player line that ends in a pawn the engine wanted kept.
BLACK_LINE = "1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 Nf6 5. Nxf6+ gxf6 6. Nf3"

#: A line whose last move is mate (Fool's mate), for the finished-position cases.
MATE_LINE = "1. f3 e5 2. g4 Qh4+"


class StubEngine:
    """Fixed evaluations keyed by position, built the way ``engine.py`` builds them.

    ``replies`` maps a position's ``position_key`` to an integer centipawn value
    *in white's point of view*, or to a whole :class:`EvalResult` for the cases
    where the evaluation is not a plain centipawn score. An integer reply is
    wrapped in a real ``PovScore`` and read back through ``.white()``, so the
    value comes out as white's score whichever side is to move. The best move of
    an integer reply is an arbitrary legal move; the tests that care about the
    named move build the :class:`EvalResult` themselves.
    """

    def __init__(self, replies: dict[str, int | EvalResult]) -> None:
        self.replies = replies
        self.asked: list[str] = []

    def analyse(self, fen: str) -> EvalResult:
        self.asked.append(fen)
        board = chess.Board(fen)
        reply = self.replies[position_key(board.fen())]
        if isinstance(reply, EvalResult):
            return reply
        # The engine's raw score is the side to move's, and PovScore's first
        # argument is written in its second argument's point of view: a white
        # score of `reply` on a black-to-move board is therefore Cp(-reply) from
        # black's side. Reading .white() is the read that means "white's
        # evaluation of this position", which is the sign rule this whole unit
        # depends on - .relative() would hand back the side-to-move figure and
        # sign-flip every black ply.
        side_to_move_cp = reply if board.turn == chess.WHITE else -reply
        score = ce.PovScore(ce.Cp(side_to_move_cp), board.turn)
        assert score.white().score() == reply, "the stub must answer as engine.py reads"
        assert score.relative.score() == side_to_move_cp, (
            "the side-to-move read is the other sign: that is the trap, not the answer"
        )
        best = sorted(m.uci() for m in board.legal_moves)
        return EvalResult(
            cp=score.white().score(),
            mate=None,
            best_move=best[0] if best else None,
            depth=DEPTH,
        )


def line_plies(line: str, *, my_color: str = "white", game_id: str = "unit-game"):
    """Real ply records for a numbered SAN line, extracted by the real extractor.

    The line is re-numbered from its moves rather than from its tokens: a numbered
    line and an unnumbered one have different token parities, so numbering by
    token index silently replaces every white move with a move number.
    """
    moves = [token for token in line.split() if not token.endswith(".")]
    parts: list[str] = []
    for index, token in enumerate(moves):
        if index % 2 == 0:
            parts.append(f"{index // 2 + 1}.")
        parts.append(token)
    numbered = " ".join(parts)
    pgn = (
        '[Event "book trigger unit fixture"]\n'
        '[Site "?"]\n'
        '[Date "2026.10.01"]\n'
        '[White "unit"]\n'
        '[Black "unit"]\n'
        '[Result "*"]\n\n'
        f"{numbered} *\n"
    )
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None and not game.errors, f"fixture PGN did not parse: {line!r}"

    record = make_record(id=game_id, pgn=pgn, my_color=my_color)
    plies = extract_opening_plies(record, max_plies=len(moves))
    assert len(plies) == len(moves), f"expected {len(moves)} plies, got {len(plies)}"
    return plies


def replies_for(
    plies,
    *,
    value: int = 30,
    after: dict[str, int | EvalResult] | None = None,
    before: dict[str, EvalResult] | None = None,
) -> dict:
    """A reply table that answers every position the walk asks about.

    ``value`` is the centipawn answer in white's point of view for every position
    in the line, so each move looks free unless an override names it: ``after``
    for the position after a move, ``before`` for the engine's evaluation of the
    position a move was played from (where the best move itself matters).
    """
    table: dict[str, int | EvalResult] = {}
    for ply in plies:
        table[position_key(ply.fen_before)] = value
        table[position_key(ply.fen_after)] = value
    for fen, answer in (after or {}).items():
        table[position_key(fen)] = answer
    for fen, answer in (before or {}).items():
        table[position_key(fen)] = answer
    return table


def best_in(fen: str, san: str, *, cp: int | None = 0, mate: int | None = None) -> EvalResult:
    """An evaluation of ``fen`` whose best move is the named one, in UCI."""
    board = chess.Board(fen)
    move = next(m for m in board.legal_moves if board.san(m) == san)
    return EvalResult(cp=cp, mate=mate, best_move=move.uci(), depth=DEPTH)


# -- the named behaviour -----------------------------------------------------


def test_first_deviation_index() -> None:
    """The first out-of-band player move is flagged; the in-band ones are not.

    Seven player moves stay inside the band; the last one costs 300 centipawns
    against the engine's own evaluation, so that ply is the one reported.
    """
    plies = line_plies(BOOK_LINE)
    player_plies = [ply for ply in plies if ply.is_my_move]
    assert len(player_plies) == 8, "the fixture should hold eight player moves"
    last = plies[-1]
    assert last.ply_index == 14 and last.move_san == "Nxe5"

    table = replies_for(plies, value=30, after={last.fen_after: -270})

    flag = first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert flag is not None, "the last move is 300 cp worse than the engine's line"
    assert flag.ply_index == 14
    assert flag.my_move == last.move_san == "Nxe5"
    assert flag.cp_gap == 300
    assert flag.game_id == "unit-game"
    assert flag.fen_before == last.fen_before


def test_first_deviation_reports_both_moves_in_san() -> None:
    """``my_move`` and ``best_move`` are SAN read from the position before the move.

    ``EvalResult.best_move`` is UCI, which nothing in the report should show, so
    the two move spaces stay distinct: the flag names the engine's move from the
    board in hand.
    """
    plies = line_plies(BOOK_LINE)
    last = plies[-1]

    table = replies_for(
        plies,
        value=30,
        after={last.fen_after: -270},
        before={last.fen_before: best_in(last.fen_before, "h3", cp=30)},
    )

    flag = first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert flag is not None
    assert flag.my_move == "Nxe5"
    assert flag.best_move == "h3"
    assert table[position_key(last.fen_before)].best_move != "h3", (
        "the flag must convert the engine's UCI move to SAN, not pass it through"
    )


def test_no_deviation_when_every_move_stays_in_book() -> None:
    """A line the engine agrees with throughout is not flagged at all."""
    plies = line_plies(BOOK_LINE)

    flag = first_deviation(plies, StubEngine(replies_for(plies, value=30)), band_cp=BAND)

    assert flag is None


def test_the_band_edge_is_inclusive() -> None:
    """A gap exactly equal to ``band_cp`` is still book; one centipawn more is not."""
    plies = line_plies(BOOK_LINE)
    last = plies[-1]

    def at(gap: int) -> DeviationFlag | None:
        table = replies_for(plies, value=30, after={last.fen_after: 30 - gap})
        return first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert at(BAND) is None
    just_over = at(BAND + 1)
    assert just_over is not None
    assert just_over.cp_gap == BAND + 1


def test_the_band_is_configurable_and_defaults_to_the_config_value() -> None:
    """A wider band forgives a gap the default one would flag."""
    plies = line_plies(BOOK_LINE)
    last = plies[-1]
    table = replies_for(plies, value=30, after={last.fen_after: -20})
    engine = StubEngine(table)

    assert DEFAULT_BOOK_BAND_CP == 30
    assert Config().book_band_cp == DEFAULT_BOOK_BAND_CP
    assert first_deviation(plies, engine) is not None, "a 50 cp leak leaves a 30 cp band"
    assert first_deviation(plies, engine, band_cp=80) is None


def test_only_the_players_moves_are_walked() -> None:
    """The opponent's moves are never flagged, however bad they are."""
    plies = line_plies(BOOK_LINE, my_color="black")
    black_plies = [ply for ply in plies if ply.is_my_move]
    assert len(black_plies) == 7
    assert plies[0].is_my_move is False, "the fixture's first ply is the opponent's"

    # Two moves leave the band, and only one of them is the player's. A ply's gap
    # is the fall between the position before it and the position after it, in
    # the *player's* currency, and the table answers in white's: for a black
    # player a leak is a rise in white's evaluation. So the opponent's 1.e4 (ply
    # 0) leaves 900 cp on the table, and the player's 2...Nc6 (ply 3) leaves 300.
    # The flag must be the player's ply and never the opponent's, which is
    # earlier in the window and much worse.
    table = replies_for(
        plies,
        value=0,
        after={plies[0].fen_after: 900, plies[3].fen_after: 300},
    )
    flag = first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert flag is not None
    assert flag.ply_index == 3
    assert flag.cp_gap == 300
    assert flag.my_move == plies[3].move_san == "Nc6"
    assert black_plies[0].ply_index == 1, "the player's first move is in book"


def test_records_are_walked_in_ply_order() -> None:
    """The earliest deviation is reported even when the records arrive shuffled.

    ``first_deviation`` is called once per game with that game's window, and a
    caller that hands the window over shuffled must still get the earliest ply
    rather than whichever one came first in the list.
    """
    plies = line_plies(BOOK_LINE)
    deviating = [ply.ply_index for ply in plies if ply.ply_index in (6, 14)]

    # A position's evaluation is also the position after the ply before it, so a
    # ply's gap is raised by raising the position it was played *from*: ply 6 is
    # 300 cp worse than the position before it, and ply 14 (the last, whose after
    # position belongs to no ply) by lowering the position after it.
    table = replies_for(
        plies,
        value=30,
        before={plies[6].fen_before: 330},
        after={plies[14].fen_after: -270},
    )
    assert {plies[6].ply_index, plies[14].ply_index} == set(deviating)

    flag = first_deviation(list(reversed(plies)), StubEngine(table), band_cp=BAND)

    assert flag is not None
    assert flag.ply_index == 6


# -- the sign rule -----------------------------------------------------------


def test_a_black_player_who_hangs_a_piece_is_flagged_with_a_positive_gap() -> None:
    """Black's evaluation is white's negated, so a loss reads as a positive gap.

    The stub answers in white's point of view for both colours, which is the only
    way the bug shows: with no conversion, Black's 200 centipawn loss would come
    out as a 200 centipawn *gain* and never be flagged at all.
    """
    plies = line_plies(BLACK_LINE, my_color="black")
    # The leaking ply is 5...gxf6; the line then continues with 6.Nf3, which is
    # white's move and must not be the ply the flag names.
    leak = plies[9]
    assert leak.is_my_move and leak.move_san == "gxf6"
    assert plies[-1].is_my_move is False

    table = replies_for(
        plies,
        value=0,
        after={leak.fen_after: 200},
        before={leak.fen_before: best_in(leak.fen_before, "exf6", cp=0)},
    )

    flag = first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert flag is not None
    assert flag.ply_index == leak.ply_index == 9
    assert flag.my_move == "gxf6"
    assert flag.best_move == "exf6"
    assert flag.cp_gap == 200


def test_a_black_player_who_improves_is_not_flagged() -> None:
    """The mirror image: Black improving reads as a gain, not as a deviation."""
    plies = line_plies(BLACK_LINE, my_color="black")
    leak = plies[9]
    assert leak.is_my_move and leak.move_san == "gxf6"

    table = replies_for(plies, value=0, after={leak.fen_after: -200})

    assert first_deviation(plies, StubEngine(table), band_cp=BAND) is None


# -- mates and finished positions -------------------------------------------


def test_giving_up_a_forced_mate_is_a_deviation() -> None:
    """Walking away from a mate score leaves the band by construction.

    A mate score has no centipawn value, so the gap needs a stand-in for one.
    Whatever the figure is, it has to dominate any band a caller can configure,
    which is why it is a named module constant rather than a literal here.
    """
    plies = line_plies("1. e4 e5 2. Bc4 Bc5 3. Qh5")
    last = plies[-1]
    assert last.is_my_move

    # The mate score is a stub, because the unit test pins the arithmetic and
    # test_real_mate_score_scores_as_a_whole_win measures it against a real
    # engine. The engine's move is 3.Bxf7+, which mates in two; the player played
    # 3.Qh5 and is level. Bxf7+ is the side to move's own move, which is the only
    # way the SAN can be named from the board.
    table = replies_for(
        plies,
        value=0,
        before={last.fen_before: best_in(last.fen_before, "Bxf7+", cp=None, mate=2)},
    )

    flag = first_deviation(plies, StubEngine(table), band_cp=BAND)

    assert flag is not None
    assert flag.cp_gap == MATE_CP
    assert flag.cp_gap > BAND
    assert flag.best_move == "Bxf7+"


def test_a_mate_the_player_delivers_is_not_a_deviation() -> None:
    """Delivering mate is the opposite of leaving the book.

    ``engine.py`` answers a mated position as ``mate = 0`` from either side, so
    the board is what says who is mated: the side to move after the player's
    move, which is the opponent.
    """
    plies = line_plies(MATE_LINE, my_color="black")
    last = plies[-1]
    assert last.is_my_move and last.move_san == "Qh4#"
    assert chess.Board(last.fen_after).is_checkmate()

    # The position after the player's move is the one ``engine.py`` answers from
    # the board: mate zero, no centipawn value, and no move to play. It is the
    # best outcome there is, and the flag has to read it that way.
    table = replies_for(
        plies,
        value=0,
        after={last.fen_after: EvalResult(cp=None, mate=0, best_move=None, depth=DEPTH)},
    )

    assert first_deviation(plies, StubEngine(table), band_cp=BAND) is None


def test_a_position_with_no_move_to_play_is_not_a_deviation() -> None:
    """A finished position has no engine move, so there is nothing to leave."""
    plies = line_plies(BOOK_LINE)
    last = plies[-1]

    table = replies_for(
        plies,
        value=0,
        before={last.fen_before: EvalResult(cp=0, mate=None, best_move=None, depth=DEPTH)},
    )

    assert first_deviation(plies, StubEngine(table), band_cp=BAND) is None


def test_an_engine_move_illegal_in_the_record_is_logged_not_trusted(caplog) -> None:
    """A corrupt or stale cached move is skipped, and says why it was skipped."""
    plies = line_plies(BOOK_LINE)
    last = plies[-1]

    # a1a8 is not a legal move from an Italian middlegame position.
    table = replies_for(
        plies,
        value=0,
        before={last.fen_before: EvalResult(cp=0, mate=None, best_move="a1a8", depth=DEPTH)},
    )

    with caplog.at_level(logging.WARNING, logger="src.chessleak.book"):
        assert first_deviation(plies, StubEngine(table), band_cp=BAND) is None

    assert "illegal" in caplog.text, (
        f"an illegal engine move must be logged, not swallowed: {caplog.text!r}"
    )


# -- the flag's shape --------------------------------------------------------


def test_the_flag_is_a_frozen_dataclass_with_the_frozen_fields() -> None:
    """``DeviationFlag`` carries what ``cluster.py`` keys and reports on."""
    flag = DeviationFlag(
        game_id="g1",
        ply_index=6,
        fen_before=chess.STARTING_FEN,
        my_move="e4",
        best_move="d5",
        cp_gap=40,
    )

    assert (flag.game_id, flag.ply_index) == ("g1", 6)
    assert flag.my_move == "e4" and flag.best_move == "d5"
    assert flag.cp_gap >= 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        flag.cp_gap = 50  # frozen: a flag a consumer could mutate would rank wrong


def test_no_records_means_no_deviation() -> None:
    """An empty window (a skipped or variant game) is not a deviation."""
    assert first_deviation([], StubEngine({})) is None
