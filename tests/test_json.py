import io
import json
from datetime import datetime

from flashdeck.cli import main

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args, inp=""):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(inp), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def make(tmp_path):
    deck = tmp_path / "fr.md"
    deck.write_text("un :: one\ndeux :: two\ntrois :: three\n", encoding="utf-8")
    other = tmp_path / "de.md"
    other.write_text("eins :: one\n", encoding="utf-8")
    return deck, other, tmp_path / "state.json"


def test_due_json_fresh(tmp_path):
    deck, other, state = make(tmp_path)
    code, out, _ = run(["due", str(deck), str(other), "--state", str(state), "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["decks"] == [
        {"deck": "fr", "due": 0, "learning": 0, "review": 0, "new": 3, "cards": 3},
        {"deck": "de", "due": 0, "learning": 0, "review": 0, "new": 1, "cards": 1},
    ]
    assert data["total"] == {"due": 0, "learning": 0, "review": 0, "new": 4, "cards": 4}


def test_due_json_no_cards(tmp_path):
    empty = tmp_path / "e.md"
    empty.write_text("just prose\n", encoding="utf-8")
    code, out, _ = run(["due", str(empty), "--state", str(tmp_path / "s.json"), "--json"])
    assert code == 0
    assert json.loads(out) == {"decks": [], "total": {
        "due": 0, "learning": 0, "review": 0, "new": 0, "cards": 0}}


def test_stats_json_fresh_has_nulls(tmp_path):
    deck, _, state = make(tmp_path)
    code, out, _ = run(["stats", str(deck), "--state", str(state), "--json", "--days", "3"])
    assert code == 0
    data = json.loads(out)
    assert data["cards"] == 3
    assert data["states"]["new"] == 3
    assert data["ease_average"] is None
    assert data["retention"]["all_time"] == {"passed": 0, "total": 0, "rate": None}
    assert [f["date"] for f in data["forecast"]] == ["2026-11-10", "2026-11-11", "2026-11-12"]


def test_stats_json_after_review(tmp_path):
    deck, _, state = make(tmp_path)
    run(["review", str(deck), "--state", str(state), "--new", "1"], "\n3\n")
    code, out, _ = run(["stats", str(deck), "--state", str(state), "--json"])
    data = json.loads(out)
    assert code == 0
    assert data["states"]["review"] == 1 and data["states"]["new"] == 2
    assert data["reviews"] == {"total": 1, "today": 1}
    assert data["ease_average"] == 2.5
    assert sum(f["due"] for f in data["forecast"]) == 1


def test_json_keeps_unicode_and_text_default_unchanged(tmp_path):
    deck = tmp_path / "é.md"
    deck.write_text("a :: b\n", encoding="utf-8")
    code, out, _ = run(["due", str(deck), "--state", str(tmp_path / "s.json"), "--json"])
    assert "é" in out
    code, out, _ = run(["due", str(deck), "--state", str(tmp_path / "s.json")])
    assert out.startswith("deck")
