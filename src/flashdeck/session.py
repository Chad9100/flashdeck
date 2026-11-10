"""The interactive review session."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional, TextIO

from .deck import Card
from .scheduler import GRADES, LEARNING, NEW, RELEARNING, CardState, parse_grade, schedule
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
    undone: int = 0

    @property
    def answers(self) -> int:
        return sum(self.counts.values())


@dataclass
class _Answer:
    """One graded answer, kept so that ``u`` can take it back."""

    card: Card
    previous: Optional[CardState]
    grade: str
    requeued: bool


def _indent(text: str) -> str:
    return "\n".join("  " + ln if ln else "" for ln in text.split("\n"))


def _is(line: Optional[str], key: str) -> bool:
    return line is not None and line.strip().lower() == key


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
    later in the same session. ``u`` (at either prompt) undoes the last
    answer: the card's previous state is restored, its log entry dropped,
    and the card is asked again. Repeated ``u`` keeps going back.
    """
    result = SessionResult()
    pending = deque(queue)
    history: list[_Answer] = []

    def undo(current: Card) -> None:
        pending.appendleft(current)
        if not history:
            out.write("  Nothing to undo.\n")
            return
        last = history.pop()
        if last.requeued:
            # The "again" copy was appended at the end; later answers that
            # could have moved it have already been undone.
            for i in range(len(pending) - 1, -1, -1):
                if pending[i].id == last.card.id:
                    del pending[i]
                    break
        pending.appendleft(last.card)
        store.unrecord(last.card.id, last.previous)
        store.save()
        result.counts[last.grade] -= 1
        result.undone += 1
        if not any(a.card.id == last.card.id for a in history):
            result.cards.discard(last.card.id)
        out.write(f"  <- undid \"{last.grade}\" on: {last.card.front.splitlines()[0]}\n")

    while pending:
        card = pending.popleft()
        before = store.get(card.id)
        label = "new" if before.state == NEW else before.state
        tags = "  " + " ".join("#" + t for t in card.tags) if card.tags else ""
        hint = "u to undo, q to quit" if history else "q to quit"
        out.write(f"\n[{len(pending) + 1} left] {card.deck} ({label}){tags}\n")
        out.write(_indent(card.front) + "\n")
        out.write(f"  -- Enter to show the answer, {hint} -- ")
        out.flush()
        line = read()
        if line is None or _is(line, "q"):
            result.quit_early = True
            out.write("\n")
            break
        if _is(line, "u"):
            out.write("\n")
            undo(card)
            continue
        out.write("\n" + _indent(card.back) + "\n")
        grade = None
        undone = False
        while grade is None:
            extra = "u undo, q quit" if history else "q to quit"
            out.write(f"  1 again   2 hard   3 good   4 easy   ({extra}) > ")
            out.flush()
            line = read()
            if line is None or _is(line, "q"):
                result.quit_early = True
                out.write("\n")
                break
            if _is(line, "u"):
                if not history:
                    out.write("  Nothing to undo.\n")
                    continue
                out.write("\n")
                undo(card)
                undone = True
                break
            grade = parse_grade(line)
            if grade is None:
                out.write("  Please answer 1-4 (or again/hard/good/easy).\n")
        if undone:
            continue
        if grade is None:
            break
        now = clock()
        after = schedule(before, grade, now.date(), now.isoformat(timespec="seconds"))
        previous = store.cards.get(card.id)
        store.record(card.id, before, after, grade, now.isoformat(timespec="seconds"))
        store.save()
        result.counts[grade] += 1
        result.cards.add(card.id)
        requeued = after.state in (LEARNING, RELEARNING)
        history.append(_Answer(card, previous, grade, requeued))
        if requeued:
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
    if result.undone:
        text += f" Undid {result.undone}."
    if result.quit_early:
        text += " Stopped early; progress saved."
    return text
