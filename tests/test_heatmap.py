import io
import json
from datetime import date, datetime

from flashdeck.cli import main
from flashdeck.deck import Card, card_id
from flashdeck.stats import format_heatmap, review_days, streaks
from flashdeck.store import Store

TODAY = date(2026, 11, 10)  # a Tuesday


def run(args, now=datetime(2026, 11, 10, 9, 0, 0)):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: now)
    return code, out.getvalue(), err.getvalue()


def days(*ds):
    return {date.fromisoformat(d): 1 for d in ds}


def test_streak_counts_back_from_today():
    assert streaks(days("2026-11-10", "2026-11-09", "2026-11-08", "2026-11-05"), TODAY) == (3, 3)


def test_streak_alive_if_only_yesterday():
    assert streaks(days("2026-11-09", "2026-11-08"), TODAY) == (2, 2)


def test_streak_broken_after_gap_and_longest_kept():
    cur, longest = streaks(days("2026-11-07", "2026-11-05", "2026-11-04", "2026-11-03"), TODAY)
    assert (cur, longest) == (0, 3)


def test_streak_empty():
    assert streaks({}, TODAY) == (0, 0)


def test_review_days_filters_by_cards_and_skips_bad_dates():
    c = Card(front="q", back="a", deck="d")
    store = Store.__new__(Store)
    store.log = [
        {"id": c.id, "at": "2026-11-10T08:00:00"},
        {"id": c.id, "at": "2026-11-10T09:00:00"},
        {"id": "other", "at": "2026-11-09T08:00:00"},
        {"id": c.id, "at": "garbage"},
    ]
    assert review_days([c], store) == {TODAY: 2}


def test_format_heatmap_shape():
    text = format_heatmap({TODAY: 5, date(2026, 11, 9): 1}, TODAY)
    lines = text.splitlines()
    assert len(lines) == 7 + 3
    assert lines[1].startswith("  Mon ")
    # Tuesday (today) is in the last column, heaviest shade; Wednesday onwards is blank.
    assert lines[2].rstrip().endswith("#")
    assert lines[3].count("-") == 11  # Wednesday: 11 past weeks, the future cell is blank
    assert "Current streak: 2 days. Longest streak: 2 days." in text


def test_cli_heatmap_json_and_text(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("un :: one\n", encoding="utf-8")
    state = tmp_path / "state.json"
    cid = card_id("un")
    state.write_text(json.dumps({"version": 1, "cards": {}, "log": [
        {"id": cid, "at": "2026-11-10T08:00:00", "grade": "good", "from": "new"},
        {"id": cid, "at": "2026-11-09T08:00:00", "grade": "good", "from": "new"},
    ]}), encoding="utf-8")
    code, out, _ = run(["stats", str(deck), "--state", str(state), "--heatmap", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["streak"] == 2 and data["reviews"] == 2
    assert data["days"] == {"2026-11-09": 1, "2026-11-10": 1}
    code, out, _ = run(["stats", str(deck), "--state", str(state), "--heatmap"])
    assert code == 0 and "Current streak: 2 days" in out


def test_heatmap_with_no_history(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("un :: one\n", encoding="utf-8")
    code, out, _ = run(["stats", str(deck), "--state", str(tmp_path / "s.json"), "--heatmap"])
    assert code == 0
    assert "Current streak: 0 days. Longest streak: 0 days." in out
