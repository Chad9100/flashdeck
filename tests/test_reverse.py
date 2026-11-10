"""Two-way cards: ``front ::: back`` makes a card in each direction."""

import io
import json
from datetime import datetime

import pytest

from flashdeck.cli import main
from flashdeck.deck import card_id, load_decks, parse_deck
from flashdeck.session import match_edited
from flashdeck.writer import format_card

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args, stdin="", now=NOW):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(stdin), stdout=out, stderr=err, clock=lambda: now)
    return code, out.getvalue(), err.getvalue()


def sides(cards):
    return [(c.front, c.back, c.reverse) for c in cards]


def test_reverse_line_yields_two_cards_with_own_ids():
    cards, warnings = parse_deck("#spanish\n\nhola ::: hello #greeting\n", deck="es", path="es.md")
    assert warnings == []
    assert sides(cards) == [("hola", "hello", False), ("hello", "hola", True)]
    assert cards[0].id == card_id("hola") and cards[1].id == card_id("hello")
    for c in cards:
        assert c.tags == ["spanish", "greeting"] and c.line == 3 and c.path == "es.md"
    cards[0].tags.append("x")
    assert cards[1].tags == ["spanish", "greeting"]  # not a shared list


def test_forward_half_keeps_history_of_a_former_one_way_card():
    one_way, _ = parse_deck("hola :: hello\n")
    two_way, _ = parse_deck("hola ::: hello\n")
    assert two_way[0].id == one_way[0].id


def test_double_colon_inside_and_escapes():
    cards, _ = parse_deck(r"std::vector ::: C++ growable array, see \#include" + "\n")
    assert sides(cards) == [
        ("std::vector", "C++ growable array, see #include", False),
        ("C++ growable array, see #include", "std::vector", True),
    ]
    cards, _ = parse_deck("a :: b ::: c\n")
    assert sides(cards) == [("a :: b", "c", False), ("c", "a :: b", True)]


def test_reverse_without_answer_warns_and_same_sides_make_one_card():
    cards, warnings = parse_deck("lonely :::\nsame ::: same\n", path="d.md")
    assert warnings == ["d.md:1: card has no answer after ':::'; skipped"]
    assert sides(cards) == [("same", "same", False)]


def test_reverse_clashing_with_existing_question_is_reported(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("hello :: a greeting\nhola ::: hello\n", encoding="utf-8")
    cards, warnings = load_decks([deck])
    assert sides(cards) == [("hello", "a greeting", False), ("hola", "hello", False)]
    assert len(warnings) == 1 and "d.md:2: duplicate question (first at" in warnings[0]


def test_match_edited_keeps_direction_when_question_reworded():
    before, _ = parse_deck("hola ::: hello\n", path="d.md")
    after, _ = parse_deck("hola ::: hi there\n", path="d.md")
    ids = {c.id for c in before}
    assert match_edited(before[1], ids, after) is after[1]
    assert match_edited(before[0], ids, after) is after[0]


def test_format_card_reverse_round_trips():
    for front, back, tags in [
        ("hola", "hello", ["spanish"]),
        ("std::vector", "C++ #include <vector>", []),
        ("C#", "a language", ["lang"]),
    ]:
        text = format_card(front, back, tags, reverse=True)
        assert ":::" in text and "\n" not in text
        cards, warnings = parse_deck(text)
        assert warnings == []
        assert sides(cards) == [(front, back, False), (back, front, True)]
        assert all(c.tags == tags for c in cards)


def test_format_card_reverse_refuses_what_cannot_be_one_line():
    with pytest.raises(ValueError, match="one line"):
        format_card("multi\nline", "x", reverse=True)
    with pytest.raises(ValueError, match="two-way"):
        format_card("a ::: b", "c", reverse=True)
    with pytest.raises(ValueError, match="two-way"):
        format_card("Q: odd", "c", reverse=True)


def test_add_reverse_round_trip_and_duplicates(tmp_path):
    deck = tmp_path / "es.md"
    deck.write_text("adiós :: goodbye\n", encoding="utf-8")
    code, out, err = run(["add", str(deck), "hola", "hello", "--reverse", "-t", "greeting"])
    assert (code, err) == (0, "")
    assert out == f"Added to {deck}: hola ::: hello #greeting\n"
    assert deck.read_text(encoding="utf-8") == "adiós :: goodbye\nhola ::: hello #greeting\n"
    cards, _ = load_decks([deck])
    assert sides(cards)[1:] == [("hola", "hello", False), ("hello", "hola", True)]

    code, _, err = run(["add", str(deck), "bye", "adiós", "-r"])
    assert code == 1 and "already has the answer as a question" in err
    code, _, err = run(["add", str(deck), "hello", "x"])
    assert code == 1 and "already has that question" in err
    code, _, err = run(["add", str(deck), "same", "same", "-r"])
    assert code == 2 and "differ" in err
    code, _, err = run(["add", str(deck), "two\nlines", "x", "-r"])
    assert code == 2 and "one line" in err
    assert deck.read_text(encoding="utf-8") == "adiós :: goodbye\nhola ::: hello #greeting\n"


def test_review_asks_both_directions_with_separate_history(tmp_path):
    deck = tmp_path / "es.md"
    deck.write_text("hola ::: hello\n", encoding="utf-8")
    state = tmp_path / "state.json"
    code, out, _ = run(["review", str(deck), "--state", str(state)], stdin="\n3\n\n4\n")
    assert code == 0
    assert "(new)\n  hola\n" in out and "(new, reverse)\n  hello\n" in out
    assert "Reviewed 2 cards" in out
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["cards"][card_id("hola")]["interval"] == 1
    assert data["cards"][card_id("hello")]["interval"] == 4

    code, out, _ = run(["due", str(deck), "--state", str(state)])
    assert out.splitlines()[1].split() == ["es", "0", "0", "0", "0", "2"]
