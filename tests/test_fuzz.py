import io
import json
from datetime import date, datetime

import pytest

from flashdeck.cli import main
from flashdeck.scheduler import REVIEW, CardState, fuzz_interval, schedule

TODAY = date(2026, 11, 10)


def review_card(interval=20, reps=4):
    return CardState(state=REVIEW, interval=interval, reps=reps, due=TODAY.isoformat())


def test_fuzz_off_by_default():
    assert schedule(review_card(), "good", TODAY).interval == 50
    assert schedule(review_card(), "good", TODAY, fuzz=0, key="x").interval == 50


def test_fuzz_is_deterministic_and_within_bounds():
    base = 50
    seen = set()
    for i in range(200):
        st = schedule(review_card(), "good", TODAY, fuzz=5, key=f"card{i}")
        again = schedule(review_card(), "good", TODAY, fuzz=5, key=f"card{i}")
        assert st.interval == again.interval
        assert base * 0.95 - 1 <= st.interval <= base * 1.05 + 1
        seen.add(st.interval)
    assert len(seen) >= 5  # cards really are spread out


def test_short_intervals_are_not_fuzzed():
    assert fuzz_interval(6, 1, 50, "k") == 6
    # second correct review: "good" is the fixed 6 days
    st = schedule(CardState(state=REVIEW, interval=1, reps=1, due=TODAY.isoformat()), "good", TODAY, fuzz=50, key="k")
    assert st.interval == 6


def test_fuzz_never_shortens_below_previous_plus_one():
    for i in range(100):
        st = schedule(review_card(interval=10, reps=3), "hard", TODAY, fuzz=50, key=f"c{i}")
        assert st.interval >= 11


def test_learning_steps_unaffected():
    st = schedule(CardState(), "good", TODAY, fuzz=50, key="k")
    assert st.interval == 1


def test_fuzz_option_validation():
    for bad in ("-1", "51", "abc"):
        with pytest.raises(SystemExit):
            main(["review", "x.md", "--fuzz", bad], stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())


def test_cli_review_with_fuzz_spreads_cards(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("".join(f"q{i} :: a{i}\n" for i in range(12)), encoding="utf-8")
    state = tmp_path / "s.json"
    # Make every card a mature review card due today.
    from flashdeck.deck import parse_deck
    from flashdeck.store import Store

    cards, _ = parse_deck(deck.read_text(encoding="utf-8"), deck="d")
    store = Store(state)
    for c in cards:
        store.cards[c.id] = CardState(state=REVIEW, interval=30, reps=5, due="2026-11-10")
    store.save()
    out = io.StringIO()
    answers = io.StringIO("".join("\n3\n" for _ in cards))
    code = main(
        ["review", str(deck), "--state", str(state), "--fuzz", "10"],
        stdout=out, stderr=io.StringIO(), stdin=answers, clock=lambda: datetime(2026, 11, 10, 9, 0, 0),
    )
    assert code == 0
    data = json.loads(state.read_text(encoding="utf-8"))
    intervals = {v["interval"] for v in data["cards"].values()}
    assert len(intervals) > 3
    assert all(67 <= i <= 83 for i in intervals)  # 75 +/- 10%
