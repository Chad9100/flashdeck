from datetime import date

import pytest

from flashdeck.scheduler import (
    LEARNING,
    MIN_EASE,
    NEW,
    RELEARNING,
    REVIEW,
    CardState,
    next_ease,
    parse_grade,
    schedule,
)

TODAY = date(2026, 11, 10)


def review_card(interval=10, reps=3, ease=2.5, lapses=0):
    return CardState(state=REVIEW, ease=ease, interval=interval, reps=reps, lapses=lapses, due=TODAY.isoformat())


def test_new_card_good_then_six_days_then_times_ease():
    st = schedule(CardState(), "good", TODAY)
    assert (st.state, st.interval, st.reps, st.due) == (REVIEW, 1, 1, "2026-11-11")
    st = schedule(st, "good", date(2026, 11, 11))
    assert (st.interval, st.reps, st.due) == (6, 2, "2026-11-17")
    st = schedule(st, "good", date(2026, 11, 17))
    assert (st.interval, st.reps) == (15, 3)  # round(6 * 2.5)
    assert st.ease == 2.5


def test_new_card_easy_starts_at_four_days_and_raises_ease():
    st = schedule(CardState(), "easy", TODAY)
    assert st.interval == 4
    assert st.ease == pytest.approx(2.6)


def test_sm2_ease_formula():
    assert next_ease(2.5, "good") == pytest.approx(2.5)
    assert next_ease(2.5, "easy") == pytest.approx(2.6)
    assert next_ease(2.5, "hard") == pytest.approx(2.36)
    assert next_ease(2.5, "again") == pytest.approx(2.18)
    assert next_ease(1.35, "again") == MIN_EASE


def test_hard_and_easy_intervals_on_review_card():
    assert schedule(review_card(), "hard", TODAY).interval == 12  # 10 * 1.2
    assert schedule(review_card(), "good", TODAY).interval == 25  # 10 * 2.5
    assert schedule(review_card(), "easy", TODAY).interval == 32  # 10 * 2.5 * 1.3


def test_interval_always_grows_by_at_least_a_day():
    st = schedule(review_card(interval=2, ease=1.3), "hard", TODAY)
    assert st.interval == 3


def test_lapse_goes_to_relearning_due_today():
    st = schedule(review_card(lapses=1), "again", TODAY)
    assert st.state == RELEARNING
    assert st.lapses == 2
    assert (st.reps, st.interval, st.due) == (0, 0, TODAY.isoformat())
    assert st.ease == pytest.approx(2.18)


def test_relearning_does_not_change_ease_again_and_restarts_at_one_day():
    st = schedule(review_card(), "again", TODAY)
    st2 = schedule(st, "again", TODAY)
    assert st2.ease == st.ease and st2.lapses == st.lapses and st2.state == RELEARNING
    st3 = schedule(st2, "good", TODAY)
    assert (st3.state, st3.interval, st3.reps) == (REVIEW, 1, 1)


def test_new_card_again_is_learning_not_a_lapse():
    st = schedule(CardState(), "again", TODAY)
    assert st.state == LEARNING and st.lapses == 0 and st.due == TODAY.isoformat()


def test_schedule_records_review_time_and_rejects_bad_grade():
    st = schedule(CardState(), "good", TODAY, "2026-11-10T09:00:00")
    assert st.last_review == "2026-11-10T09:00:00"
    with pytest.raises(ValueError):
        schedule(CardState(), "meh", TODAY)


def test_interval_is_capped():
    st = schedule(review_card(interval=30000, ease=2.5), "easy", TODAY)
    assert st.interval == 36500


@pytest.mark.parametrize(
    "text,grade",
    [("1", "again"), ("2", "hard"), ("3", "good"), ("4", "easy"), (" G ", "good"),
     ("easy", "easy"), ("a", "again"), ("5", None), ("", None), ("x", None)],
)
def test_parse_grade(text, grade):
    assert parse_grade(text) == grade


def test_card_state_round_trip_and_validation():
    st = review_card()
    assert CardState.from_dict(st.to_dict()) == st
    assert CardState.from_dict({}).state == NEW
    with pytest.raises(ValueError):
        CardState.from_dict({"state": "zombie"})
    with pytest.raises(ValueError):
        CardState.from_dict({"state": "review", "due": "tomorrow"})
    assert CardState.from_dict({"ease": 0.5}).ease == MIN_EASE
