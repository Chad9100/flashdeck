"""Due counts and statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .deck import Card
from .scheduler import LEARNING, MATURE_DAYS, NEW, RELEARNING, REVIEW, STATES
from .store import Store


@dataclass
class DueRow:
    deck: str
    new: int = 0
    learning: int = 0
    review: int = 0
    total: int = 0

    @property
    def due(self) -> int:
        return self.learning + self.review


def due_counts(cards: list[Card], store: Store, today: date) -> list[DueRow]:
    """Per deck: unseen cards, (re)learning cards due, review cards due, total."""
    rows: dict[str, DueRow] = {}
    for card in cards:
        row = rows.setdefault(card.deck, DueRow(card.deck))
        row.total += 1
        st = store.get(card.id)
        if st.state == NEW:
            row.new += 1
        elif st.is_due(today):
            if st.state == REVIEW:
                row.review += 1
            else:
                row.learning += 1
    return list(rows.values())


def format_due(rows: list[DueRow]) -> str:
    width = max([len("deck"), len("total")] + [len(r.deck) for r in rows])
    head = f"{'deck':<{width}}  {'due':>5}  {'learn':>5}  {'review':>6}  {'new':>5}  {'cards':>5}"
    lines = [head]
    tot = DueRow("total")
    for r in rows:
        lines.append(f"{r.deck:<{width}}  {r.due:>5}  {r.learning:>5}  {r.review:>6}  {r.new:>5}  {r.total:>5}")
        tot.new += r.new
        tot.learning += r.learning
        tot.review += r.review
        tot.total += r.total
    if len(rows) > 1:
        lines.append(
            f"{'total':<{width}}  {tot.due:>5}  {tot.learning:>5}  {tot.review:>6}  {tot.new:>5}  {tot.total:>5}"
        )
    return "\n".join(lines)


@dataclass
class Stats:
    total: int = 0
    by_state: dict[str, int] = field(default_factory=lambda: {s: 0 for s in STATES})
    mature: int = 0
    avg_ease: float | None = None
    lapses: int = 0
    reviews_total: int = 0
    reviews_today: int = 0
    retention_30: tuple[int, int] = (0, 0)  # (passed, total)
    retention_all: tuple[int, int] = (0, 0)
    forecast: list[tuple[date, int]] = field(default_factory=list)


def compute_stats(cards: list[Card], store: Store, today: date, days: int = 7) -> Stats:
    s = Stats(total=len(cards))
    ids = {c.id for c in cards}
    eases = []
    for card in cards:
        st = store.get(card.id)
        s.by_state[st.state] += 1
        s.lapses += st.lapses
        if st.state != NEW:
            eases.append(st.ease)
        if st.state == REVIEW and st.interval >= MATURE_DAYS:
            s.mature += 1
    if eases:
        s.avg_ease = sum(eases) / len(eases)

    since = (today - timedelta(days=29)).isoformat()
    today_s = today.isoformat()
    p30 = t30 = pall = tall = 0
    for e in store.log:
        if e.get("id") not in ids:
            continue
        at = str(e.get("at", ""))
        s.reviews_total += 1
        if at.startswith(today_s):
            s.reviews_today += 1
        # Retention: how often a card that had graduated to review was recalled.
        if e.get("from") == REVIEW:
            ok = e.get("grade") != "again"
            tall += 1
            pall += ok
            if at[:10] >= since:
                t30 += 1
                p30 += ok
    s.retention_30 = (p30, t30)
    s.retention_all = (pall, tall)

    buckets = [0] * days
    for card in cards:
        st = store.get(card.id)
        d = st.due_date
        if st.state == NEW or d is None:
            continue
        offset = max(0, (d - today).days)
        if offset < days:
            buckets[offset] += 1
    s.forecast = [(today + timedelta(days=i), n) for i, n in enumerate(buckets)]
    return s


def _pct(pair: tuple[int, int]) -> str:
    passed, total = pair
    if not total:
        return "n/a"
    return f"{100 * passed / total:.1f}% ({passed}/{total})"


def format_stats(s: Stats) -> str:
    b = s.by_state
    lines = [
        f"Cards:      {s.total} total",
        f"  new {b[NEW]}, learning {b[LEARNING]}, review {b[REVIEW]} "
        f"(mature {s.mature}), relearning {b[RELEARNING]}",
        f"Ease:       {s.avg_ease:.2f} average" if s.avg_ease is not None else "Ease:       n/a",
        f"Lapses:     {s.lapses}",
        f"Reviews:    {s.reviews_total} total, {s.reviews_today} today",
        f"Retention:  {_pct(s.retention_30)} last 30 days, {_pct(s.retention_all)} all time",
        "Forecast (cards due):",
    ]
    peak = max([n for _, n in s.forecast] + [1])
    for i, (day, n) in enumerate(s.forecast):
        label = "today" if i == 0 else "tomorrow" if i == 1 else day.strftime("%a %m-%d")
        bar = "#" * (round(20 * n / peak) if n else 0)
        lines.append(f"  {label:<9} {n:>4}  {bar}".rstrip())
    return "\n".join(lines)
