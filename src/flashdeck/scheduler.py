"""SM-2 scheduling.

Each card carries an ease factor (EF, starts at 2.5, never below 1.3), an
interval in days, a count of successful repetitions in a row and a count of
lapses (times a review card was forgotten).

The four buttons map to SM-2 quality grades: again = 2, hard = 3, good = 4,
easy = 5. On a new or review card the ease factor is updated with the SM-2
formula ``EF += 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)``; so "good" keeps it,
"hard" lowers it by 0.14, "again" by 0.32 and "easy" raises it by 0.1.

Intervals follow SM-2 (1 day, then 6 days, then previous interval x EF), with
two small tweaks borrowed from Anki: "hard" grows the interval by 1.2x only,
and "easy" adds a 1.3x bonus. "again" restarts the card: it becomes due again
in the same session (learning / relearning) and, once answered, starts over at
1 day. Grades given while (re)learning do not change the ease factor again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from typing import Optional

NEW = "new"
LEARNING = "learning"
REVIEW = "review"
RELEARNING = "relearning"
STATES = (NEW, LEARNING, REVIEW, RELEARNING)

GRADES = ("again", "hard", "good", "easy")
QUALITY = {"again": 2, "hard": 3, "good": 4, "easy": 5}

INITIAL_EASE = 2.5
MIN_EASE = 1.3
HARD_FACTOR = 1.2
EASY_BONUS = 1.3
MAX_INTERVAL = 36500
MATURE_DAYS = 21


@dataclass
class CardState:
    state: str = NEW
    ease: float = INITIAL_EASE
    interval: int = 0
    reps: int = 0
    lapses: int = 0
    due: Optional[str] = None  # ISO date
    last_review: Optional[str] = None  # ISO datetime

    @property
    def due_date(self) -> Optional[date]:
        return date.fromisoformat(self.due) if self.due else None

    def is_due(self, today: date) -> bool:
        d = self.due_date
        return self.state != NEW and d is not None and d <= today

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CardState":
        if not isinstance(data, dict):
            raise ValueError("card state must be an object")
        state = data.get("state", NEW)
        if state not in STATES:
            raise ValueError(f"unknown card state {state!r}")
        due = data.get("due")
        if due is not None:
            date.fromisoformat(due)  # validate
        return cls(
            state=state,
            ease=max(MIN_EASE, float(data.get("ease", INITIAL_EASE))),
            interval=max(0, int(data.get("interval", 0))),
            reps=max(0, int(data.get("reps", 0))),
            lapses=max(0, int(data.get("lapses", 0))),
            due=due,
            last_review=data.get("last_review"),
        )


def parse_grade(text: str) -> Optional[str]:
    """Turn user input (``1``-``4``, ``a``/``h``/``g``/``e`` or a word) into a grade."""
    t = text.strip().lower()
    if t in GRADES:
        return t
    if t in ("1", "2", "3", "4"):
        return GRADES[int(t) - 1]
    for g in GRADES:
        if t == g[0]:
            return g
    return None


def next_ease(ease: float, grade: str) -> float:
    q = QUALITY[grade]
    ease = ease + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
    return round(max(MIN_EASE, ease), 4)


def schedule(st: CardState, grade: str, today: date, now_iso: Optional[str] = None) -> CardState:
    """Return the card's new state after answering it with ``grade`` on ``today``."""
    if grade not in QUALITY:
        raise ValueError(f"unknown grade {grade!r}")
    ease = st.ease
    if st.state in (NEW, REVIEW):
        ease = next_ease(st.ease, grade)

    if grade == "again":
        if st.state == REVIEW:
            state, lapses = RELEARNING, st.lapses + 1
        elif st.state == NEW:
            state, lapses = LEARNING, st.lapses
        else:
            state, lapses = st.state, st.lapses
        return replace(
            st, state=state, ease=ease, interval=0, reps=0, lapses=lapses,
            due=today.isoformat(), last_review=now_iso,
        )

    if st.state != REVIEW:
        # New, learning or relearning card answered correctly: first step.
        reps = 1
        interval = 4 if grade == "easy" else 1
    else:
        reps = st.reps + 1
        prev = max(1, st.interval)
        if reps <= 1:
            interval = 1
        elif reps == 2:
            interval = {"hard": 4, "good": 6, "easy": 8}[grade]
        elif grade == "hard":
            interval = round(prev * HARD_FACTOR)
        elif grade == "good":
            interval = round(prev * st.ease)
        else:
            interval = round(prev * st.ease * EASY_BONUS)
        interval = max(interval, prev + 1)
    interval = min(interval, MAX_INTERVAL)
    return replace(
        st, state=REVIEW, ease=ease, interval=interval, reps=reps,
        due=(today + timedelta(days=interval)).isoformat(), last_review=now_iso,
    )
