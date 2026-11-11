"""Export cards to CSV or Anki's plain-text import format."""

from __future__ import annotations

import csv
import io
from typing import Iterable

from .deck import Card

FORMATS = ("csv", "anki")


def export_cards(cards: Iterable[Card], fmt: str) -> str:
    """Return the cards as text: one row per card (front, back, tags).

    ``csv`` has a ``front,back,tags`` header and comma separators, so it
    round-trips through ``flashdeck import``. ``anki`` is tab separated with
    the ``#separator``, ``#html`` and ``#tags column`` header lines Anki reads.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format {fmt!r} (use csv or anki)")
    buf = io.StringIO()
    if fmt == "csv":
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["front", "back", "tags"])
    else:
        buf.write("#separator:tab\n#html:false\n#tags column:3\n")
        writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    for c in cards:
        writer.writerow([c.front, c.back, " ".join(c.tags)])
    return buf.getvalue()
