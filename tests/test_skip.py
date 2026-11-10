import io
import json
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import parse_deck
from flashdeck.session import LineReader, SessionResult, run_session, summary
from flashdeck.store import Store

NOW = datetime(2026, 11, 10, 9, 0, 0)


def make_cards(n):
    cards, _ = parse_deck("".join(f"q{i} :: a{i}\n" for i in range(n)), deck="d")
    return cards


def reader(*answers):
    return LineReader(io.StringIO("".join(a + "\n" for a in answers)))


def fronts_asked(text):
    return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("q")]


def test_skip_at_question_prompt_leaves_state_untouched(tmp_path):
    cards = make_cards(2)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    res = run_session(cards, store, reader("s", "", "3"), out, lambda: NOW)
    text = out.getvalue()
    assert fronts_asked(text) == ["q0", "q1"]
    assert "-> skipped for this session: q0" in text
    assert cards[0].id not in store.cards
    assert [e["id"] for e in store.log] == [cards[1].id]
    assert res.skipped == 1 and res.cards == {cards[1].id}
    assert not res.quit_early


def test_skip_at_grade_prompt_after_seeing_the_answer(tmp_path):
    cards = make_cards(2)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    res = run_session(cards, store, reader("", "S", "", "4"), out, lambda: NOW)
    text = out.getvalue()
    assert "a0" in text  # answer was revealed before skipping
    assert "Please answer" not in text
    assert cards[0].id not in store.cards
    assert res.skipped == 1 and res.counts["easy"] == 1


def test_skipping_a_requeued_card_drops_it_for_the_session(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    # "again" requeues q0; skipping the requeued copy ends the session.
    res = run_session(cards, store, reader("", "1", "s"), out, lambda: NOW)
    assert fronts_asked(out.getvalue()) == ["q0", "q0"]
    assert [e["grade"] for e in store.log] == ["again"]
    assert res.skipped == 1 and not res.quit_early


def test_undo_after_skip_goes_back_to_the_last_answer(tmp_path):
    cards = make_cards(3)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    # Grade q0, skip q1, then undo at q2: q0 is asked again; q1 stays skipped.
    res = run_session(cards, store, reader("", "3", "s", "u", "", "2", "", "3"), out, lambda: NOW)
    assert fronts_asked(out.getvalue()) == ["q0", "q1", "q2", "q0", "q2"]
    assert [(e["id"], e["grade"]) for e in store.log] == [(cards[0].id, "hard"), (cards[2].id, "good")]
    assert cards[1].id not in store.cards
    assert res.skipped == 1 and res.undone == 1


def test_skip_hint_shown_at_both_prompts(tmp_path):
    out = io.StringIO()
    run_session(make_cards(1), Store(tmp_path / "s.json"), reader("", "3"), out, lambda: NOW)
    text = out.getvalue()
    assert "Enter to show the answer, s to skip, q to quit" in text
    assert "(s skip, q quit)" in text


def test_summary_mentions_skips():
    res = SessionResult()
    assert summary(res) == "No cards reviewed."
    res.skipped = 2
    assert summary(res) == "No cards reviewed. Skipped 2."
    res.counts["good"] = 1
    res.cards.add("x")
    assert summary(res) == "Reviewed 1 card (1 answers: again 0, hard 0, good 1, easy 0). Skipped 2."


def test_cli_review_with_skip(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\nadiós :: goodbye\n", encoding="utf-8")
    state = tmp_path / "state.json"
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["review", str(deck), "--state", str(state)],
        stdin=io.StringIO("s\n\n3\n"),
        stdout=out,
        stderr=err,
        clock=lambda: NOW,
    )
    assert code == 0, err.getvalue()
    data = json.loads(state.read_text(encoding="utf-8"))
    assert [e["grade"] for e in data["log"]] == ["good"]
    assert len(data["cards"]) == 1
    assert "Skipped 1." in out.getvalue()
