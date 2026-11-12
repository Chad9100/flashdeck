import io
import json
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import card_id

NOW = datetime(2026, 11, 10, 9, 0, 0)
A, B = card_id("a"), card_id("b")


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def e(cid, at, grade, frm="review", interval=10):
    return {"id": cid, "at": at, "grade": grade, "from": frm, "interval": interval}


def setup(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("a :: 1\nb :: 2\n", encoding="utf-8")
    state = tmp_path / "state.json"
    card = {"state": "review", "ease": 2.5, "interval": 10, "due": "2026-11-20", "reps": 2, "lapses": 0}
    log = [
        e(A, "2025-01-03T08:00:00", "good"),
        e(A, "2025-01-03T08:05:00", "again"),
        e(A, "2025-01-03T08:09:00", "good", interval=12),
        e(B, "2025-01-03T09:00:00", "good", frm="new"),
        e(A, "2025-12-01T09:00:00", "good"),  # not old enough
        e(A, "2026-11-10T09:00:00", "good"),
    ]
    state.write_text(
        json.dumps({"version": 1, "cards": {A: card, B: dict(card)}, "log": log}), encoding="utf-8"
    )
    return deck, state


def test_compacts_old_entries_into_daily_summaries(tmp_path):
    deck, state = setup(tmp_path)
    code, out, _ = run(["compact", "--state", str(state)])
    assert code == 0
    assert out == "Compacted 4 log entries before 2025-11-10 into 2 daily summaries.\n"
    log = json.loads(state.read_text(encoding="utf-8"))["log"]
    assert len(log) == 4
    first = next(x for x in log if x["id"] == A and x["grade"] == "summary")
    assert first == {"id": A, "at": "2025-01-03", "grade": "summary", "from": "review",
                     "count": 3, "passed": 2, "interval": 12}
    assert [x["at"] for x in log[-2:]] == ["2025-12-01T09:00:00", "2026-11-10T09:00:00"]


def test_stats_are_unchanged_by_compaction(tmp_path):
    deck, state = setup(tmp_path)
    args = ["stats", str(deck), "--state", str(state), "--json"]
    before = run(args)[1]
    heat = run(["stats", str(deck), "--state", str(state), "--heatmap", "--json"])[1]
    run(["compact", "--state", str(state)])
    assert run(args)[1] == before
    assert run(["stats", str(deck), "--state", str(state), "--heatmap", "--json"])[1] == heat


def test_second_run_is_a_noop(tmp_path):
    deck, state = setup(tmp_path)
    run(["compact", "--state", str(state)])
    text = state.read_text(encoding="utf-8")
    code, out, _ = run(["compact", "--state", str(state)])
    assert code == 0 and out.startswith("Nothing to compact")
    assert state.read_text(encoding="utf-8") == text


def test_older_than_option(tmp_path):
    deck, state = setup(tmp_path)
    code, out, _ = run(["compact", "--older-than", "0", "--state", str(state)])
    assert code == 0
    assert out == "Compacted 5 log entries before 2026-11-10 into 3 daily summaries.\n"
