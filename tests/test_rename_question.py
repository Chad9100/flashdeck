import io
import json
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import card_id

NOW = datetime(2026, 11, 10, 9, 0, 0)
ENTRY = {"state": "review", "ease": 2.5, "interval": 6, "due": "2026-11-16", "reps": 2, "lapses": 0}


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def make_state(tmp_path, questions=("old q",)):
    state = tmp_path / "state.json"
    cards = {card_id(q): dict(ENTRY) for q in questions}
    log = [{"id": card_id(q), "at": "2026-11-10T09:00:00", "grade": "good", "from": "new", "interval": 6}
           for q in questions]
    state.write_text(json.dumps({"version": 1, "cards": cards, "log": log}), encoding="utf-8")
    return state


def read(state):
    return json.loads(state.read_text(encoding="utf-8"))


def test_moves_state_and_log(tmp_path):
    state = make_state(tmp_path)
    code, out, _ = run(["rename-question", "old q", "new q", "--state", str(state)])
    assert code == 0 and "(1 log entries)" in out
    data = read(state)
    assert list(data["cards"]) == [card_id("new q")]
    assert data["cards"][card_id("new q")]["interval"] == 6
    assert [e["id"] for e in data["log"]] == [card_id("new q")]


def test_old_can_be_an_id(tmp_path):
    state = make_state(tmp_path)
    code, _, _ = run(["rename-question", card_id("old q"), "new q", "--state", str(state)])
    assert code == 0
    assert list(read(state)["cards"]) == [card_id("new q")]


def test_whitespace_differences_do_not_matter(tmp_path):
    state = make_state(tmp_path)
    code, _, _ = run(["rename-question", "  old   q ", "new  q", "--state", str(state)])
    assert code == 0
    assert list(read(state)["cards"]) == [card_id("new q")]


def test_unknown_old_question(tmp_path):
    state = make_state(tmp_path)
    before = state.read_text(encoding="utf-8")
    code, _, err = run(["rename-question", "nope", "new q", "--state", str(state)])
    assert code == 1 and "no review history" in err
    assert state.read_text(encoding="utf-8") == before


def test_refuses_to_overwrite_existing_history(tmp_path):
    state = make_state(tmp_path, ("old q", "new q"))
    before = state.read_text(encoding="utf-8")
    code, _, err = run(["rename-question", "old q", "new q", "--state", str(state)])
    assert code == 1 and "already has review history" in err
    assert state.read_text(encoding="utf-8") == before


def test_same_id_is_rejected(tmp_path):
    state = make_state(tmp_path)
    code, _, err = run(["rename-question", "old q", "old  q", "--state", str(state)])
    assert code == 1 and "same id" in err
