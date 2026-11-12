"""Due counts and statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .deck import Card
from .scheduler import LEARNING, MATURE_DAYS, NEW, RELEARNING, REVIEW, STATES
from .store import Store, entry_count, entry_passed


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


def due_to_dict(rows: list[DueRow]) -> dict:
    """The ``due --json`` document: one object per deck plus totals."""
    decks = [
        {"deck": r.deck, "due": r.due, "learning": r.learning, "review": r.review,
         "new": r.new, "cards": r.total}
        for r in rows
    ]
    keys = ("due", "learning", "review", "new", "cards")
    return {"decks": decks, "total": {k: sum(d[k] for d in decks) for k in keys}}


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
        n = entry_count(e)
        s.reviews_total += n
        if at.startswith(today_s):
            s.reviews_today += n
        # Retention: how often a card that had graduated to review was recalled.
        if e.get("from") == REVIEW:
            ok = entry_passed(e)
            tall += n
            pall += ok
            if at[:10] >= since:
                t30 += n
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


def stats_to_dict(s: Stats) -> dict:
    """The ``stats --json`` document; retention rate is null when there is no data."""

    def retention(pair: tuple[int, int]) -> dict:
        passed, total = pair
        return {"passed": passed, "total": total,
                "rate": round(passed / total, 4) if total else None}

    return {
        "cards": s.total,
        "states": dict(s.by_state),
        "mature": s.mature,
        "ease_average": round(s.avg_ease, 2) if s.avg_ease is not None else None,
        "lapses": s.lapses,
        "reviews": {"total": s.reviews_total, "today": s.reviews_today},
        "retention": {"last_30_days": retention(s.retention_30),
                      "all_time": retention(s.retention_all)},
        "forecast": [{"date": d.isoformat(), "due": n} for d, n in s.forecast],
    }


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


HEATMAP_WEEKS = 12
_SHADES = " .:+#"  # none, then four levels of activity


def review_days(cards: list[Card], store: Store) -> dict[date, int]:
    """Number of answers logged per calendar day for the given cards."""
    ids = {c.id for c in cards}
    days: dict[date, int] = {}
    for e in store.log:
        if e.get("id") not in ids:
            continue
        try:
            d = date.fromisoformat(str(e.get("at", ""))[:10])
        except ValueError:
            continue
        days[d] = days.get(d, 0) + entry_count(e)
    return days


def streaks(days: dict[date, int], today: date) -> tuple[int, int]:
    """(current, longest) run of consecutive study days.

    The current streak is still alive if you have not studied yet today but did yesterday.
    """
    longest = run = 0
    prev = None
    for d in sorted(x for x in days if x <= today):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    current = 0
    d = today if today in days else today - timedelta(days=1)
    while d in days:
        current += 1
        d -= timedelta(days=1)
    return current, longest


def heatmap_to_dict(days: dict[date, int], today: date, weeks: int = HEATMAP_WEEKS) -> dict:
    current, longest = streaks(days, today)
    start = _heatmap_start(today, weeks)
    shown = {d.isoformat(): n for d, n in sorted(days.items()) if start <= d <= today}
    return {"streak": current, "longest_streak": longest, "weeks": weeks,
            "days_studied": len(shown), "reviews": sum(shown.values()), "days": shown}


def _heatmap_start(today: date, weeks: int) -> date:
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(weeks=weeks - 1)


def format_heatmap(days: dict[date, int], today: date, weeks: int = HEATMAP_WEEKS) -> str:
    """Weeks as columns, Monday to Sunday as rows; darker means more reviews that day."""
    start = _heatmap_start(today, weeks)
    peak = max([n for d, n in days.items() if start <= d <= today] + [1])
    lines = [f"Reviews, last {weeks} weeks (each column is a week, '.' to '#' is light to heavy):"]
    for row, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        cells = []
        for w in range(weeks):
            d = start + timedelta(weeks=w, days=row)
            if d > today:
                cells.append(" ")
                continue
            n = days.get(d, 0)
            level = 0 if n == 0 else 1 + min(3, (n - 1) * 4 // peak)
            cells.append(_SHADES[level] if level else "-")
        lines.append(f"  {name} " + " ".join(cells))
    current, longest = streaks(days, today)
    shown = [n for d, n in days.items() if start <= d <= today]
    lines.append(f"Studied {len(shown)} of the last {(today - start).days + 1} days, "
                 f"{sum(shown)} reviews.")
    unit = lambda n: f"{n} day" + ("" if n == 1 else "s")
    lines.append(f"Current streak: {unit(current)}. Longest streak: {unit(longest)}.")
    return "\n".join(lines)


UNTAGGED = "(untagged)"


def group_cards(cards: list[Card], by: str) -> dict[str, list[Card]]:
    """Group cards by ``"deck"`` or ``"tag"``. A card with several tags is in each group."""
    groups: dict[str, list[Card]] = {}
    for card in cards:
        keys = [card.deck] if by == "deck" else (card.tags or [UNTAGGED])
        for key in keys:
            groups.setdefault(key, []).append(card)
    if by == "tag":
        return dict(sorted(groups.items(), key=lambda kv: (kv[0] == UNTAGGED, kv[0])))
    return groups


def compute_grouped(cards: list[Card], store: Store, today: date, by: str) -> dict[str, Stats]:
    return {k: compute_stats(g, store, today, days=1) for k, g in group_cards(cards, by).items()}


def format_grouped(groups: dict[str, Stats], by: str) -> str:
    label = "deck" if by == "deck" else "tag"
    width = max([len(label)] + [len(k) for k in groups])
    head = (f"{label:<{width}}  {'cards':>5}  {'new':>4}  {'learn':>5}  {'review':>6}  "
            f"{'mature':>6}  {'ease':>5}  {'retention':>9}")
    lines = [head]
    for key, s in groups.items():
        b = s.by_state
        ease = f"{s.avg_ease:.2f}" if s.avg_ease is not None else "n/a"
        passed, total = s.retention_all
        ret = f"{100 * passed / total:.0f}%" if total else "n/a"
        lines.append(
            f"{key:<{width}}  {s.total:>5}  {b[NEW]:>4}  {b[LEARNING] + b[RELEARNING]:>5}  "
            f"{b[REVIEW]:>6}  {s.mature:>6}  {ease:>5}  {ret:>9}"
        )
    return "\n".join(lines)


def grouped_to_dict(groups: dict[str, Stats], by: str) -> dict:
    """The ``stats --by-deck/--by-tag --json`` document."""
    return {"by": by, "groups": [{"name": k, **{x: v for x, v in stats_to_dict(s).items()
                                               if x != "forecast"}} for k, s in groups.items()]}
