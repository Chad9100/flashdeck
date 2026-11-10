import io
from datetime import date, datetime, timedelta

from flashdeck.deck import parse_deck
from flashdeck.scheduler import NEW, REVIEW, CardState
from flashdeck.session import LineReader, build_queue, new_introduced_on, run_session, summary
from flashdeck.stats import compute_stats, due_counts, format_due, format_stats
from flashdeck.store import Store

TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 9, 0, 0)


def make_cards(n=5, deck="d"):
    text = "".join(f"q{i} :: a{i}\n" for i in range(n))
    cards, _ = parse_deck(text, deck=deck)
    return cards


def reader(*answers):
    return LineReader(io.StringIO("".join(a + "\n" for a in answers)))


def test_line_reader_strips_bom_only_at_start_and_reports_eof():
    r = LineReader(io.StringIO("﻿3\r\n﻿x\n"))
    assert r() == "3"
    assert r() == "﻿x"
    assert r() is None


def test_build_queue_due_first_then_new_with_limits(tmp_path):
    cards = make_cards(5)
    store = Store(tmp_path / "s.json")
    store.cards[cards[3].id] = CardState(state=REVIEW, interval=3, reps=1, due="2026-11-09")
    store.cards[cards[4].id] = CardState(state=REVIEW, interval=3, reps=1, due="2026-11-08")
    store.cards[cards[2].id] = CardState(state=REVIEW, interval=3, reps=1, due="2026-11-12")
    q = build_queue(cards, store, TODAY, new_limit=1, limit=10)
    assert [c.front for c in q] == ["q4", "q3", "q0"]
    assert [c.front for c in build_queue(cards, store, TODAY, 5, 2)] == ["q4", "q3"]
    assert [c.front for c in build_queue(cards, store, TODAY, 0, 10)] == ["q4", "q3"]


def test_daily_new_allowance_counts_cards_started_today(tmp_path):
    cards = make_cards(4)
    store = Store(tmp_path / "s.json")
    for c in cards[:2]:
        after = CardState(state=REVIEW, interval=1, reps=1, due="2026-11-11")
        store.record(c.id, CardState(), after, "good", "2026-11-10T08:00:00")
    store.record("old", CardState(), CardState(), "good", "2026-11-09T08:00:00")
    assert new_introduced_on(store, TODAY) == 2
    q = build_queue(cards, store, TODAY, new_limit=3, limit=10)
    assert [c.front for c in q] == ["q2"]


def test_run_session_grades_and_saves_each_answer(tmp_path):
    cards = make_cards(2)
    path = tmp_path / "s.json"
    store = Store(path)
    out = io.StringIO()
    res = run_session(cards, store, reader("", "3", "", "4"), out, lambda: NOW)
    assert res.counts == {"again": 0, "hard": 0, "good": 1, "easy": 1}
    saved = Store(path)
    assert saved.cards[cards[0].id].due == "2026-11-11"
    assert saved.cards[cards[1].id].due == "2026-11-14"
    text = out.getvalue()
    assert "q0" in text and "a0" in text and "next in 1 day (2026-11-11)" in text
    assert summary(res) == "Reviewed 2 cards (2 answers: again 0, hard 0, good 1, easy 1)."


def test_again_requeues_card_in_same_session(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    res = run_session(cards, store, reader("", "1", "", "3"), out, lambda: NOW)
    assert res.counts["again"] == 1 and res.counts["good"] == 1
    assert len(res.cards) == 1
    st = store.cards[cards[0].id]
    assert st.state == REVIEW and st.interval == 1
    assert out.getvalue().count("q0") == 2
    assert len(store.log) == 2


def test_invalid_grade_reprompts(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    out = io.StringIO()
    run_session(cards, store, reader("", "9", "good"), out, lambda: NOW)
    assert "Please answer 1-4" in out.getvalue()
    assert store.cards[cards[0].id].state == REVIEW


def test_quit_and_eof_keep_earlier_answers(tmp_path):
    cards = make_cards(3)
    path = tmp_path / "s.json"
    store = Store(path)
    res = run_session(cards, store, reader("", "3", "q"), io.StringIO(), lambda: NOW)
    assert res.quit_early and res.answers == 1
    assert len(Store(path).cards) == 1
    res = run_session(cards, Store(path), reader("", ""), io.StringIO(), lambda: NOW)
    assert res.quit_early and res.answers == 0
    assert summary(res) == "No cards reviewed."


def test_session_uses_clock_at_answer_time(tmp_path):
    cards = make_cards(1)
    store = Store(tmp_path / "s.json")
    times = iter([datetime(2026, 11, 10, 23, 59), datetime(2026, 11, 11, 0, 1)])
    run_session(cards, store, reader("", "3"), io.StringIO(), lambda: next(times))
    assert store.cards[cards[0].id].due == "2026-11-11"
    assert store.log[0]["at"] == "2026-11-10T23:59:00"


def test_due_counts_per_deck(tmp_path):
    a = make_cards(3, deck="alpha")
    b, _ = parse_deck("x :: y\n", deck="beta")
    store = Store(tmp_path / "s.json")
    store.cards[a[0].id] = CardState(state=REVIEW, interval=2, reps=1, due="2026-11-10")
    store.cards[a[1].id] = CardState(state="learning", due="2026-11-10")
    store.cards[b[0].id] = CardState(state=REVIEW, interval=2, reps=1, due="2026-11-20")
    rows = due_counts(a + b, store, TODAY)
    assert [(r.deck, r.due, r.learning, r.review, r.new, r.total) for r in rows] == [
        ("alpha", 2, 1, 1, 1, 3),
        ("beta", 0, 0, 0, 0, 1),
    ]
    table = format_due(rows)
    assert table.splitlines()[0].split() == ["deck", "due", "learn", "review", "new", "cards"]
    assert table.splitlines()[-1].split() == ["total", "2", "1", "1", "1", "4"]


def test_stats_retention_states_and_forecast(tmp_path):
    cards = make_cards(5)
    store = Store(tmp_path / "s.json")
    store.cards[cards[0].id] = CardState(state=REVIEW, ease=2.5, interval=30, reps=4, due="2026-11-09")
    store.cards[cards[1].id] = CardState(state=REVIEW, ease=2.3, interval=3, reps=2, due="2026-11-12", lapses=1)
    store.cards[cards[2].id] = CardState(state="relearning", ease=2.0, due="2026-11-10", lapses=2)
    store.cards[cards[3].id] = CardState(state=REVIEW, ease=2.5, interval=9, reps=3, due="2026-11-30")
    log = [
        (cards[0].id, "2026-11-10T08:00:00", "good", REVIEW),
        (cards[1].id, "2026-11-01T08:00:00", "hard", REVIEW),
        (cards[2].id, "2026-11-10T08:05:00", "again", REVIEW),
        (cards[2].id, "2026-09-01T08:00:00", "again", REVIEW),
        (cards[3].id, "2026-09-01T08:00:00", "good", NEW),
        ("not-in-these-decks", "2026-11-10T08:00:00", "again", REVIEW),
    ]
    store.log = [{"id": i, "at": at, "grade": g, "from": f, "interval": 1} for i, at, g, f in log]
    s = compute_stats(cards, store, TODAY)
    assert s.by_state == {"new": 1, "learning": 0, "review": 3, "relearning": 1}
    assert s.mature == 1
    assert s.lapses == 3
    assert s.reviews_total == 5 and s.reviews_today == 2
    assert s.retention_30 == (2, 3)
    assert s.retention_all == (2, 4)
    assert [n for _, n in s.forecast] == [2, 0, 1, 0, 0, 0, 0]
    assert s.forecast[0][0] == TODAY and s.forecast[6][0] == TODAY + timedelta(days=6)
    text = format_stats(s)
    assert "66.7% (2/3) last 30 days" in text
    assert "today" in text and "tomorrow" in text and "Sat 11-14" in text


def test_stats_with_no_history(tmp_path):
    s = compute_stats(make_cards(2), Store(tmp_path / "s.json"), TODAY)
    text = format_stats(s)
    assert "Retention:  n/a last 30 days, n/a all time" in text
    assert "Ease:       n/a" in text
