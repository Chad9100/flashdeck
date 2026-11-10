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
    skipped: int = 0
    edited: int = 0

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


@dataclass
class EditResult:
    """What an edit callback found after the editor closed.

    ``cards`` is the freshly loaded deck (after tag filtering); ``card`` is
    the edited card as it now reads, or ``None`` if it is gone.
    """

    card: Optional[Card]
    cards: list[Card]


EditCallback = Callable[[Card], Optional[EditResult]]


def match_edited(card: Card, before_ids: set[str], after: list[Card]) -> Optional[Card]:
    """Find ``card`` again after its deck was edited.

    Same question: found by id. Reworded question: a card that now starts on
    the same line of the same file and whose id did not exist before the
    edit. Otherwise the card was deleted (or moved and reworded at once).
    """
    for c in after:
        if c.id == card.id:
            return c
    for c in after:
        if c.path == card.path and c.line == card.line and c.id not in before_ids:
            return c
    return None


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
    edit: Optional[EditCallback] = None,
) -> SessionResult:
    """Show each card, wait for Enter, reveal, ask for a grade, reschedule.

    The state file is saved after every answer, so quitting (``q``, end of
    input or Ctrl+C) never loses work. Cards answered "again" come back
    later in the same session. ``u`` (at either prompt) undoes the last
    answer: the card's previous state is restored, its log entry dropped,
    and the card is asked again. Repeated ``u`` keeps going back. ``s``
    (at either prompt) skips the card for the rest of the session without
    grading it; its state and the answer log are left untouched.

    With an ``edit`` callback, ``e`` (at either prompt) hands the card to
    it (normally: open the deck in an editor and reload it). The rest of
    the queue is refreshed from the reloaded deck, and the edited card is
    shown again from its question, ungraded. If the callback returns
    ``None`` (the editor failed) the card is shown again unchanged.
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

    def skip(current: Card) -> None:
        result.skipped += 1
        out.write(f"  -> skipped for this session: {current.front.splitlines()[0]}\n")

    def do_edit(current: Card) -> None:
        if edit is None:
            pending.appendleft(current)
            out.write("  Editing is not available here.\n")
            return
        found = edit(current)
        if found is None:
            pending.appendleft(current)
            return
        result.edited += 1
        by_id = {c.id: c for c in found.cards}
        refreshed = [by_id[c.id] for c in pending if c.id in by_id]
        pending.clear()
        pending.extend(refreshed)
        for answer in history:
            answer.card = by_id.get(answer.card.id, answer.card)
        new = found.card
        if new is None:
            out.write(f"  -> no longer in the deck, dropped: {current.front.splitlines()[0]}\n")
            return
        if new.id != current.id:
            out.write("  -> question reworded: asked as a new card\n")
        else:
            out.write("  -> reloaded after editing\n")
        if not any(c.id == new.id for c in pending):
            pending.appendleft(new)

    while pending:
        card = pending.popleft()
        before = store.get(card.id)
        label = "new" if before.state == NEW else before.state
        tags = "  " + " ".join("#" + t for t in card.tags) if card.tags else ""
        hint = "s to skip, " + ("e to edit, " if edit else "") + ("u to undo, " if history else "") + "q to quit"
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
        if _is(line, "s"):
            out.write("\n")
            skip(card)
            continue
        if _is(line, "e"):
            out.write("\n")
            do_edit(card)
            continue
        out.write("\n" + _indent(card.back) + "\n")
        grade = None
        handled = False
        while grade is None:
            extra = "s skip, " + ("e edit, " if edit else "") + ("u undo, " if history else "") + "q quit"
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
                handled = True
                break
            if _is(line, "s"):
                out.write("\n")
                skip(card)
                handled = True
                break
            if _is(line, "e"):
                out.write("\n")
                do_edit(card)
                handled = True
                break
            grade = parse_grade(line)
            if grade is None:
                out.write("  Please answer 1-4 (or again/hard/good/easy).\n")
        if handled:
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
        text = "No cards reviewed."
        if result.skipped:
            text += f" Skipped {result.skipped}."
        if result.edited:
            text += f" Edited {result.edited}."
        return text
    c = result.counts
    parts = ", ".join(f"{g} {c[g]}" for g in GRADES)
    n = len(result.cards)
    text = f"Reviewed {n} card{'s' if n != 1 else ''} ({result.answers} answers: {parts})."
    if result.undone:
        text += f" Undid {result.undone}."
    if result.skipped:
        text += f" Skipped {result.skipped}."
    if result.edited:
        text += f" Edited {result.edited}."
    if result.quit_early:
        text += " Stopped early; progress saved."
    return text
