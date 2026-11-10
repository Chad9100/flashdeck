import io
import json
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import parse_deck
from flashdeck.scheduler import REVIEW, CardState
from flashdeck.session import LineReader, run_session, summary
from flashdeck.store import Store

NOW = datetime(2026, 11, 10, 9, 0, 0)


def make_cards(n):
    cards, _ = parse_deck("".join(f"q{i} :: a{i}\n" for i in range(n)), deck="d")
    return cards


def reader(*answers):
    return LineReader(io.StringIO("".join(a + "\n" for a in answers)))


def fronts_asked(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("q")]


def test_undo_at_grade_prompt_reasks_previous_card(tmp_path):
    cards = make_cards(2)
    path = tmp_path / "s.json"
    store = Store(path)
    out = io.StringIO()
    answers = reader("", "3", "", "u", "", "4", "", "3")
    res = run_session(cards, store, answers, out, lambda: NOW)
    saved = Store(path)
    assert saved.cards[cards[0].id].due == "2026-11-14"  # easy, not good
    assert saved.cards[cards[1].id].due == "2026-11-11"
    assert [e["grade"] for e in saved.log] == ["easy", "good"]
    assert res.counts == {"again": 0, "hard": 0, "good": 1, "easy": 1}
    assert res.undone == 1 and len(res.cards) == 2
    text = out.getvalue()
    assert '<- undid "good" on: q0' in text
    assert fronts_asked(text) == ["q0", "q1", "q0", "q1"]
    assert summary(res) == "Reviewed 2 cards (2 answers: again 0, hard 0, good 1, easy 1). Undid 1."


def test_undo_at_question_prompt_and_repeatedly(tmp_path):
    cards = make_cards(3)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    answers = reader("", "3", "", "2", "u", "u", "", "1", "", "3")
    res = run_session(cards, store, answers, out, lambda: NOW)
    # q2's prompt undoes q1, q1's prompt undoes q0; q0 then goes "again".
    assert fronts_asked(out.getvalue()) == ["q0", "q1", "q2", "q1", "q0", "q1", "q2"]
    assert [(e["id"], e["grade"]) for e in store.log] == [(cards[0].id, "again"), (cards[1].id, "good")]
    assert cards[2].id not in store.cards
    assert res.undone == 2 and res.cards == {cards[0].id, cards[1].id}
    assert res.quit_early  # input ran out at q2


def test_undoing_again_drops_the_requeued_copy(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    res = run_session(cards, store, reader("", "1", "u", "", "3"), out, lambda: NOW)
    assert fronts_asked(out.getvalue()) == ["q0", "q0", "q0"]
    assert not res.quit_early
    st = store.cards[cards[0].id]
    assert st.state == REVIEW and st.interval == 1 and st.lapses == 0
    assert [e["grade"] for e in store.log] == ["good"]


def test_undo_restores_existing_review_state_exactly(tmp_path):
    cards = make_cards(1)
    path = tmp_path / "s.json"
    store = Store(path)
    old = CardState(state=REVIEW, ease=2.36, interval=12, reps=3, due="2026-11-09", lapses=1)
    store.cards[cards[0].id] = old
    store.record("other", CardState(), CardState(), "good", "2026-11-01T08:00:00")
    store.save()
    run_session(cards, Store(path), reader("", "1", "u", "q"), io.StringIO(), lambda: NOW)
    saved = Store(path)
    assert saved.cards[cards[0].id] == old
    assert [e["id"] for e in saved.log] == ["other"]


def test_nothing_to_undo_keeps_the_card(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    res = run_session(cards, store, reader("u", "", "u", "3"), out, lambda: NOW)
    text = out.getvalue()
    assert text.count("Nothing to undo.") == 2
    assert "Please answer" not in text
    assert res.counts["good"] == 1 and res.undone == 0


def test_undo_hint_only_after_an_answer(tmp_path):
    cards = make_cards(2)
    out = io.StringIO()
    run_session(cards, Store(tmp_path / "s.json"), reader("", "3", "", "3"), out, lambda: NOW)
    text = out.getvalue()
    assert text.count("Enter to show the answer, s to skip, q to quit") == 1
    assert text.count("Enter to show the answer, s to skip, u to undo, q to quit") == 1
    assert text.count("(s skip, u undo, q quit)") == 1


def test_store_unrecord_removes_last_entry_for_that_card(tmp_path):
    store = Store(tmp_path / "s.json")
    a1 = CardState(state=REVIEW, interval=1, reps=1, due="2026-11-11")
    store.record("a", CardState(), a1, "good", "t1")
    store.record("b", CardState(), a1, "good", "t2")
    store.record("a", a1, CardState(state=REVIEW, interval=6, reps=2), "good", "t3")
    store.unrecord("a", a1)
    assert store.cards["a"] == a1
    assert [(e["id"], e["at"]) for e in store.log] == [("a", "t1"), ("b", "t2")]
    store.unrecord("a", None)
    assert "a" not in store.cards and [e["id"] for e in store.log] == ["b"]


def test_cli_review_with_undo(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\nadiós :: goodbye\n", encoding="utf-8")
    state = tmp_path / "state.json"
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["review", str(deck), "--state", str(state)],
        stdin=io.StringIO("\n1\nu\n\n3\n\n3\n"),
        stdout=out,
        stderr=err,
        clock=lambda: NOW,
    )
    assert code == 0, err.getvalue()
    data = json.loads(state.read_text(encoding="utf-8"))
    assert [e["grade"] for e in data["log"]] == ["good", "good"]
    assert all(c["state"] == REVIEW for c in data["cards"].values())
    assert "Undid 1." in out.getvalue()
