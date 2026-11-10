"""Parse plain-text / Markdown deck files into cards.

These card syntaxes are recognised, and can be mixed in one file:

* one-line cards::

      hola :: hello #spanish

* two-way cards, which make one card in each direction (each with its own
  id and history)::

      hola ::: hello

* cloze lines, which make one card per ``{{gap}}``; the card hides that gap
  as ``[...]`` and its answer is the whole sentence::

      The capital of France is {{Paris}}.

* question/answer blocks, which may span several lines and end at a blank
  line (blank lines inside a fenced code block do not end them)::

      Q: What does SM-2 stand for?
      A: SuperMemo algorithm, version 2.

A line made only of tags (``#spanish #verbs``) sets the tags for the cards
that follow it, until the next such line. Tags at the end of a card's answer
apply to that card only. Write ``\\#`` for a literal ``#`` that would
otherwise be read as a tag. Everything else (headings, prose, lists) is
ignored, so a deck can double as ordinary notes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DECK_SUFFIXES = (".md", ".markdown", ".txt")

_TAG = r"(?<!\\)#[^\W\d][\w/-]*"
TAG_RE = re.compile(_TAG)
TAG_LINE_RE = re.compile(rf"^\s*{_TAG}(?:\s+{_TAG})*\s*$")
TRAILING_TAGS_RE = re.compile(rf"(?:\s+{_TAG})+\s*$")
ONE_LINE_RE = re.compile(r"^(?P<front>.*?\S)\s+::(?:\s+(?P<back>.*\S))?\s*$")
REVERSE_RE = re.compile(r"^(?P<front>.*?\S)\s+:::(?:\s+(?P<back>.*\S))?\s*$")
CLOZE_RE = re.compile(r"\{\{(.+?)\}\}")
CLOZE_BLANK = "[...]"
Q_RE = re.compile(r"^Q:\s?(.*)$")
A_RE = re.compile(r"^A:\s?(.*)$")
A_BOTH_RE = re.compile(r"^A::(?:\s(.*))?$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


class DeckError(Exception):
    """A deck path that cannot be read."""


@dataclass
class Card:
    front: str
    back: str
    tags: list[str] = field(default_factory=list)
    deck: str = ""
    path: str = ""
    line: int = 0
    reverse: bool = False  # the back-to-front card of a ``front ::: back`` line

    @property
    def id(self) -> str:
        return card_id(self.front)


def normalize_front(front: str) -> str:
    return " ".join(front.split())


def card_id(front: str) -> str:
    """Stable id for a card: a short hash of its whitespace-normalised front.

    Editing the answer, tags, position or file of a card keeps its id (and so
    its review history); changing the question makes it a new card.
    """
    digest = hashlib.sha1(normalize_front(front).encode("utf-8")).hexdigest()
    return digest[:12]


def normalize_tag(tag: str) -> str:
    return tag.lstrip("#").lower()


def _split_trailing_tags(text: str) -> tuple[str, list[str]]:
    m = TRAILING_TAGS_RE.search(text)
    if not m or m.start() == 0:
        return text, []
    tags = [normalize_tag(t) for t in TAG_RE.findall(m.group(0))]
    return text[: m.start()], tags


def _unescape(text: str) -> str:
    return text.replace("\\#", "#")


def _merge_tags(*groups: Iterable[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for tag in group:
            if tag not in out:
                out.append(tag)
    return out


def parse_deck(text: str, deck: str = "", path: str = "") -> tuple[list[Card], list[str]]:
    """Parse deck text. Returns ``(cards, warnings)``."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cards: list[Card] = []
    warnings: list[str] = []
    where = path or deck or "<deck>"
    section_tags: list[str] = []

    mode: str | None = None  # None, "q" or "a"
    in_fence = False
    front: list[str] = []
    back: list[str] = []
    start = 0
    both = False  # the current Q:/A:: block is two-way

    def finish() -> None:
        nonlocal mode, both
        front_text = "\n".join(front).strip()
        back_text = "\n".join(back).strip()
        if mode == "q":
            warnings.append(f"{where}:{start}: question has no 'A:' answer; skipped")
        elif not front_text:
            warnings.append(f"{where}:{start}: empty question; skipped")
        else:
            back_text, own_tags = _split_trailing_tags(back_text)
            back_text = back_text.strip()
            if not back_text:
                warnings.append(f"{where}:{start}: empty answer; skipped")
            else:
                f, b = _unescape(front_text), _unescape(back_text)
                sides = [(f, b, False)]
                if both and card_id(f) != card_id(b):
                    sides.append((b, f, True))
                for sf, sb, rev in sides:
                    cards.append(
                        Card(
                            front=sf,
                            back=sb,
                            tags=_merge_tags(section_tags, own_tags),
                            deck=deck,
                            path=path,
                            line=start,
                            reverse=rev,
                        )
                    )
        mode = None
        both = False

    for lineno, raw in enumerate(lines, 1):
        line = raw.rstrip()
        is_fence = bool(FENCE_RE.match(line))

        if mode is None:
            if is_fence:
                in_fence = not in_fence
                continue
            if in_fence or not line.strip():
                continue
            q = Q_RE.match(line)
            if q:
                mode, start, front, back = "q", lineno, [q.group(1)], []
                continue
            if TAG_LINE_RE.match(line):
                section_tags = [normalize_tag(t) for t in TAG_RE.findall(line)]
                continue
            if CLOZE_RE.search(line) and not ONE_LINE_RE.match(line):
                text, own_tags = _split_trailing_tags(line)
                gaps = list(CLOZE_RE.finditer(text))
                full = _unescape(CLOZE_RE.sub(lambda g: g.group(1).strip(), text).strip())
                tags = _merge_tags(section_tags, own_tags)
                for target in gaps:
                    pieces, pos = [], 0
                    for g in gaps:
                        pieces.append(text[pos:g.start()])
                        pieces.append(CLOZE_BLANK if g is target else g.group(1).strip())
                        pos = g.end()
                    pieces.append(text[pos:])
                    cards.append(
                        Card(front=_unescape("".join(pieces).strip()), back=full,
                             tags=list(tags), deck=deck, path=path, line=lineno)
                    )
                continue
            m = REVERSE_RE.match(line)
            both = m is not None
            if not both:
                m = ONE_LINE_RE.match(line)
            if m:
                if m.group("back") is None:
                    sep = ":::" if both else "::"
                    warnings.append(f"{where}:{lineno}: card has no answer after '{sep}'; skipped")
                    continue
                back_text, own_tags = _split_trailing_tags(m.group("back"))
                front_text = _unescape(m.group("front").strip())
                back_text = _unescape(back_text.strip())
                tags = _merge_tags(section_tags, own_tags)
                sides = [(front_text, back_text, False)]
                if both and card_id(back_text) != card_id(front_text):
                    sides.append((back_text, front_text, True))
                for f, b, rev in sides:
                    cards.append(
                        Card(front=f, back=b, tags=list(tags), deck=deck, path=path,
                             line=lineno, reverse=rev)
                    )
            continue

        if is_fence:
            in_fence = not in_fence
        if mode == "q":
            ab = A_BOTH_RE.match(line) if not in_fence else None
            a = A_RE.match(line) if not in_fence else None
            if ab:
                mode, back, both = "a", [ab.group(1) or ""], True
            elif a:
                mode, back = "a", [a.group(1)]
            elif not line.strip() and not in_fence:
                finish()
            else:
                front.append(line)
            continue

        # mode == "a"
        if not in_fence and not line.strip():
            finish()
            continue
        q = Q_RE.match(line) if not in_fence else None
        if q:
            finish()
            mode, start, front, back = "q", lineno, [q.group(1)], []
            continue
        back.append(line)

    if mode is not None:
        in_fence = False
        finish()
    return cards, warnings


def read_text(path: Path) -> str:
    """Read a UTF-8 text file, dropping a leading BOM."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DeckError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DeckError(f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start})") from None


def deck_files(paths: Iterable[str | Path]) -> list[Path]:
    """Expand deck arguments: files as given, directories to their deck files."""
    out: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            found = sorted(
                f
                for f in p.rglob("*")
                if f.is_file()
                and f.suffix.lower() in DECK_SUFFIXES
                and not any(part.startswith(".") for part in f.relative_to(p).parts)
            )
            if not found:
                raise DeckError(f"no deck files (*.md, *.txt) in {p}")
            out.extend(found)
        elif p.is_file():
            out.append(p)
        else:
            raise DeckError(f"no such deck: {p}")
    # Keep order, drop repeats.
    seen: set[Path] = set()
    unique = []
    for f in out:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def load_decks(paths: Iterable[str | Path]) -> tuple[list[Card], list[str]]:
    """Load every card from the given deck files/directories.

    Cards with the same front (same id) are kept once, at their first place.
    """
    cards: list[Card] = []
    warnings: list[str] = []
    first_seen: dict[str, Card] = {}
    for f in deck_files(paths):
        found, warns = parse_deck(read_text(f), deck=f.stem, path=str(f))
        warnings.extend(warns)
        for card in found:
            other = first_seen.get(card.id)
            if other is not None:
                warnings.append(
                    f"{card.path}:{card.line}: duplicate question "
                    f"(first at {other.path}:{other.line}); skipped"
                )
                continue
            first_seen[card.id] = card
            cards.append(card)
    return cards, warnings


def filter_tags(cards: list[Card], tags: Iterable[str] | None) -> list[Card]:
    wanted = {normalize_tag(t) for t in (tags or [])}
    if not wanted:
        return cards
    return [c for c in cards if wanted.intersection(c.tags)]
