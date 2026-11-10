import io
import json
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import card_id

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def setup(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("a :: 1\nb :: 2\n", encoding="utf-8")
    state = tmp_path / "state.json"
    run(["review", str(deck), "--state", str(state)])  # no input: nothing graded
    entry = {"state": "review", "ease": 2.5, "interval": 6, "due": "2026-11-16", "reps": 2, "lapses": 0}
    cards = {card_id(q): dict(entry) for q in ("a", "b", "gone")}
    log = [{"id": card_id(q), "at": "2026-11-10T09:00:00", "grade": "good", "from": "new", "interval": 6}
           for q in ("a", "gone")]
    state.write_text(json.dumps({"version": 1, "cards": cards, "log": log}), encoding="utf-8")
    return deck, state


def test_lists_orphans_without_changing_state(tmp_path):
    deck, state = setup(tmp_path)
    before = state.read_text(encoding="utf-8")
    code, out, _ = run(["orphans", str(deck), "--state", str(state)])
    assert code == 0
    assert card_id("gone") in out and card_id("a") not in out
    assert "1 orphaned card(s)" in out
    assert state.read_text(encoding="utf-8") == before


def test_prune_removes_card_and_its_log(tmp_path):
    deck, state = setup(tmp_path)
    code, out, _ = run(["orphans", str(deck), "--state", str(state), "--prune"])
    assert code == 0 and "Pruned 1 card(s) and 1 log entries." in out
    data = json.loads(state.read_text(encoding="utf-8"))
    assert sorted(data["cards"]) == sorted([card_id("a"), card_id("b")])
    assert [e["id"] for e in data["log"]] == [card_id("a")]


def test_no_orphans(tmp_path):
    deck, state = setup(tmp_path)
    run(["orphans", str(deck), "--state", str(state), "--prune"])
    code, out, _ = run(["orphans", str(deck), "--state", str(state), "--prune"])
    assert code == 0 and out == "No orphaned state entries.\n"


def test_missing_deck_is_an_error_not_a_wipe(tmp_path):
    deck, state = setup(tmp_path)
    before = state.read_text(encoding="utf-8")
    code, _, err = run(["orphans", str(tmp_path / "nope.md"), "--state", str(state), "--prune"])
    assert code == 2 and err
    assert state.read_text(encoding="utf-8") == before
