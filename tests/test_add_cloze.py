"""``flashdeck add --cloze`` writes a cloze line that parses back to one card per gap."""

import io
from datetime import datetime

import pytest

from flashdeck.cli import main
from flashdeck.deck import load_decks, parse_deck
from flashdeck.writer import format_cloze

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def test_format_cloze_round_trips():
    for text, tags, n in [
        ("The capital of France is {{Paris}}.", [], 1),
        ("{{Paris}} is the capital of {{France}}.", ["geo", "europe"], 2),
        ("C# is {{typed}}", ["lang"], 1),
    ]:
        line = format_cloze(text, tags)
        assert "\n" not in line
        cards, warnings = parse_deck(line)
        assert warnings == [] and len(cards) == n
        assert all(c.tags == tags for c in cards)
        assert all("#" not in c.back or "C#" in c.back for c in cards)


def test_format_cloze_refuses_bad_input():
    with pytest.raises(ValueError, match="gap"):
        format_cloze("no gaps here")
    with pytest.raises(ValueError, match="one line"):
        format_cloze("a {{b}}\nc")
    with pytest.raises(ValueError, match="cloze"):
        format_cloze("a :: {{b}}")


def test_add_cloze_round_trip_and_duplicates(tmp_path):
    deck = tmp_path / "geo.md"
    deck.write_text("Rome :: Italy\n", encoding="utf-8")
    code, out, err = run(["add", str(deck), "{{Paris}} is in {{France}}.", "--cloze", "-t", "geo"])
    assert (code, err) == (0, "")
    assert out == f"Added to {deck}: {{{{Paris}}}} is in {{{{France}}}}. #geo (2 card(s))\n"
    cards, _ = load_decks([deck])
    assert [c.front for c in cards[1:]] == ["[...] is in France.", "Paris is in [...]."]
    assert all(c.back == "Paris is in France." for c in cards[1:])

    before = deck.read_text(encoding="utf-8")
    code, _, err = run(["add", str(deck), "{{Paris}} is in {{France}}.", "-c"])
    assert code == 1 and "already has" in err
    assert deck.read_text(encoding="utf-8") == before


def test_add_cloze_argument_errors(tmp_path):
    deck = tmp_path / "d.md"
    code, _, err = run(["add", str(deck), "a {{b}}", "answer", "--cloze"])
    assert code == 2 and "no answer" in err
    code, _, err = run(["add", str(deck), "a {{b}}", "--cloze", "--reverse"])
    assert code == 2
    code, _, err = run(["add", str(deck), "just a question"])
    assert code == 2 and "question and an answer" in err
    code, _, err = run(["add", str(deck), "no gaps", "--cloze"])
    assert code == 2 and "gap" in err
    assert not deck.exists()
