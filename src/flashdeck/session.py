"""The interactive review session."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional, TextIO

from .deck import Card
from .scheduler import GRADES, LEARNING, NEW, RELEARNING, parse_grade, schedule
from .store import Store

Clock = Callable[[], datetime]


class LineReader:
    """Read answers line by line from a stream.

    Returns ``None`` at end of input. A UTF-8 BOM at the very start (which
    some Windows tools put in front of piped text) is dropped.
    """

    def __init__(self, stream: TextIO):
        self.stream = stream
        self._first = True

    def __call__(self) -> Optional[str]:
        try:
            line = self.stream.readline()
        except KeyboardInterrupt:
            return None
        if line == "":
            return None
        if self._first:
            self._first = False
            line = line.lstrip("﻿")
        return line.rstrip("\r\n")


def new_introduced_on(store: Store, day: date) -> int:
    """How many new cards were first answered on ``day``."""
    prefix = day.isoformat()
    return len({e["id"] for e in store.log if e.get("from") == NEW and str(e.get("at", "")).startswith(prefix)})


def build_queue(cards: list[Card], store: Store, today: date, new_limit: int, limit: int) -> list[Card]:
    """Due cards first (most overdue first), then new cards in deck order.

    ``new_limit`` is a daily allowance: new cards already started today count
    against it. ``limit`` caps the whole session.
    """
    order = {c.id: i for i, c in enumerate(cards)}
    due = [c for c in cards if store.get(c.id).is_due(today)]
    due.sort(key=lambda c: (store.get(c.id).due, order[c.id]))
    allowance = max(0, new_limit - new_introduced_on(store, today))
    fresh = [c for c in cards if store.state_of(c.id) == NEW][:allowance]
    return (due + fresh)[: max(0, limit)]


@dataclass
class SessionResult:
    counts: dict[str, int] = field(default_factory=lambda: {g: 0 for g in GRADES})
    cards: set[str] = field(default_factory=set)
    quit_early: bool = False

    @property
    def answers(self) -> int:
        return sum(self.counts.values())


def _indent(text: str) -> str:
    return "\n".join("  " + ln if ln else "" for ln in text.split("\n"))


def run_session(
    queue: list[Card],
    store: Store,
    read: Callable[[], Optional[str]],
    out: TextIO,
    clock: Clock,
) -> SessionResult:
    """Show each card, wait for Enter, reveal, ask for a grade, reschedule.

    The state file is saved after every answer, so quitting (``q``, end of
    input or Ctrl+C) never loses work. Cards answered "again" come back
    later in the same session.
    """
    result = SessionResult()
    pending = deque(queue)
    while pending:
        card = pending.popleft()
        before = store.get(card.id)
        label = "new" if before.state == NEW else before.state
        tags = "  " + " ".join("#" + t for t in card.tags) if card.tags else ""
        out.write(f"\n[{len(pending) + 1} left] {card.deck} ({label}){tags}\n")
        out.write(_indent(card.front) + "\n")
        out.write("  -- Enter to show the answer, q to quit -- ")
        out.flush()
        line = read()
        if line is None or line.strip().lower() == "q":
            result.quit_early = True
            out.write("\n")
            break
        out.write("\n" + _indent(card.back) + "\n")
        grade = None
        while grade is None:
            out.write("  1 again   2 hard   3 good   4 easy   (q to quit) > ")
            out.flush()
            line = read()
            if line is None or line.strip().lower() == "q":
                result.quit_early = True
                out.write("\n")
                break
            grade = parse_grade(line)
            if grade is None:
                out.write("  Please answer 1-4 (or again/hard/good/easy).\n")
        if grade is None:
            break
        now = clock()
        after = schedule(before, grade, now.date(), now.isoformat(timespec="seconds"))
        store.record(card.id, before, after, grade, now.isoformat(timespec="seconds"))
        store.save()
        result.counts[grade] += 1
        result.cards.add(card.id)
        if after.state in (LEARNING, RELEARNING):
            out.write("  -> again later in this session\n")
            pending.append(card)
        else:
            days = after.interval
            out.write(f"  -> next in {days} day{'s' if days != 1 else ''} ({after.due})\n")
    return result


def summary(result: SessionResult) -> str:
    if result.answers == 0:
        return "No cards reviewed."
    c = result.counts
    parts = ", ".join(f"{g} {c[g]}" for g in GRADES)
    n = len(result.cards)
    text = f"Reviewed {n} card{'s' if n != 1 else ''} ({result.answers} answers: {parts})."
    if result.quit_early:
        text += " Stopped early; progress saved."
    return text
