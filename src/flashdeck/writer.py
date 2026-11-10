"""Append cards to deck files (``flashdeck add`` and ``flashdeck import``)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .deck import card_id, load_decks, normalize_tag, parse_deck, read_text

_LOOKS_LIKE_TAG = re.compile(r"(?<![\\\w])#(?=[^\W\d])")
_TAG_OK = re.compile(r"^[^\W\d][\w/-]*$")


def _escape(text: str) -> str:
    """Escape ``#`` that the parser would otherwise read as a tag."""
    return _LOOKS_LIKE_TAG.sub(r"\\#", text)


def clean_tags(tags: Iterable[str]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        for piece in re.split(r"[\s,]+", raw):
            tag = normalize_tag(piece)
            if not tag:
                continue
            if not _TAG_OK.match(tag):
                raise ValueError(f"invalid tag {piece!r} (use letters, digits, '-', '_' or '/')")
            if tag not in out:
                out.append(tag)
    return out


def format_card(front: str, back: str, tags: Iterable[str] = (), reverse: bool = False) -> str:
    """Render a card as deck text (without a trailing newline).

    Short single-line cards use ``front :: back``; anything else becomes a
    ``Q:``/``A:`` block. With ``reverse`` the card is written as
    ``front ::: back`` (a card in each direction), which only exists as a
    one-line card. The result parses back to the same front, back and tags.
    """
    front = front.strip()
    back = back.strip()
    if not front or not back:
        raise ValueError("a card needs both a question and an answer")
    tag_text = "".join(f" #{t}" for t in clean_tags(tags))
    if reverse:
        return _format_reverse(front, back, tag_text, clean_tags(tags))
    multi = "\n" in front or "\n" in back
    awkward = (
        re.search(r"\s::(\s|$)", front)
        or front.startswith(("Q:", "A:"))
        or "\n\n" in back
        or "\n\n" in front
    )
    if not multi and not awkward:
        return f"{_escape(front)} :: {_escape(back)}{tag_text}"
    if "\n\n" in front or "\n\n" in back:
        # Blank lines would end the block; collapse them.
        front = re.sub(r"\n\s*\n", "\n", front)
        back = re.sub(r"\n\s*\n", "\n", back)
    front_lines = _escape(front).split("\n")
    back_lines = _escape(back).split("\n")
    # A continuation line starting with "A:" would end the question early.
    front_lines = front_lines[:1] + [
        (" " + ln if ln.startswith(("A:", "Q:")) else ln) for ln in front_lines[1:]
    ]
    back_lines = back_lines[:1] + [
        (" " + ln if ln.startswith("Q:") else ln) for ln in back_lines[1:]
    ]
    lines = [f"Q: {front_lines[0]}", *front_lines[1:], f"A: {back_lines[0]}", *back_lines[1:]]
    lines[-1] += tag_text
    return "\n".join(lines)


def _format_reverse(front: str, back: str, tag_text: str, tags: list[str]) -> str:
    if "\n" in front or "\n" in back:
        raise ValueError("a two-way card must fit on one line (no line breaks)")
    if card_id(front) == card_id(back):
        raise ValueError("a two-way card needs a question and answer that differ")
    text = f"{_escape(front)} ::: {_escape(back)}{tag_text}"
    cards, _ = parse_deck(text)
    expected = [(front, back, False), (back, front, True)]
    if [(c.front, c.back, c.reverse) for c in cards] != expected or any(c.tags != tags for c in cards):
        raise ValueError("this question cannot be written as a two-way card (it contains ':::' or 'Q:'/'A:')")
    return text


def append_cards(path: Path, blocks: list[str]) -> None:
    """Append rendered cards to a deck file, creating it if needed.

    Keeps the file's existing newline style and any BOM. Cards are separated
    by a blank line unless both neighbours are one-line cards, so that a
    ``Q:``/``A:`` block never swallows the card after it.
    """
    if not blocks:
        return
    existing = read_text(path) if path.exists() else ""
    newline = "\r\n" if "\r\n" in existing else "\n"
    body = existing.replace("\r\n", "\n")
    out = ""
    if body and not body.endswith("\n"):
        out = "\n"
    has_content = bool(body.strip())
    at_blank = not has_content or body.endswith("\n\n")
    prev_simple = False
    if has_content and not at_blank:
        last_lineno = len(body.rstrip("\n").split("\n"))
        cards, _ = parse_deck(body)
        prev_simple = bool(cards) and cards[-1].line == last_lineno
    for block in blocks:
        simple = "\n" not in block
        if has_content and not at_blank and not (simple and prev_simple):
            out += "\n"
        out += block + "\n"
        has_content, at_blank, prev_simple = True, False, simple
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(out.replace("\n", newline))


def existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    cards, _ = load_decks([path])
    return {c.id for c in cards}


@dataclass
class ImportResult:
    added: int = 0
    duplicates: int = 0
    skipped: int = 0


_FRONT_NAMES = {"front", "question", "q", "term", "prompt"}
_BACK_NAMES = {"back", "answer", "a", "definition", "response"}
_TAG_NAMES = {"tags", "tag"}


def _pick(header: list[str], wanted: str | None, names: set[str], default: int | None) -> int | None:
    lowered = [h.strip().lower() for h in header]
    if wanted is not None:
        if wanted.isdigit():
            return int(wanted) - 1
        if wanted.lower() in lowered:
            return lowered.index(wanted.lower())
        raise ValueError(f"no column named {wanted!r} (columns: {', '.join(header)})")
    for i, h in enumerate(lowered):
        if h in names:
            return i
    return default


def read_csv_rows(text: str, delimiter: str | None = None) -> list[list[str]]:
    if text.startswith("﻿"):
        text = text[1:]
    if delimiter is None:
        sample = text[:4096]
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]


def import_rows(
    rows: list[list[str]],
    deck_path: Path,
    *,
    header: bool | None = None,
    front_col: str | None = None,
    back_col: str | None = None,
    tags_col: str | None = None,
    extra_tags: Iterable[str] = (),
) -> ImportResult:
    """Append CSV rows to a deck, skipping questions the deck already has."""
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    result = ImportResult()
    if not rows:
        return result
    first = rows[0]
    if header is None:
        lowered = {c.strip().lower() for c in first}
        header = bool(lowered & (_FRONT_NAMES | _BACK_NAMES | _TAG_NAMES)) and len(first) >= 2
    names = first if header else [str(i + 1) for i in range(len(first))]
    data = rows[1:] if header else rows
    fi = _pick(names, front_col, _FRONT_NAMES if header else set(), 0)
    bi = _pick(names, back_col, _BACK_NAMES if header else set(), 1)
    ti = _pick(names, tags_col, _TAG_NAMES if header else set(), None)
    fixed_tags = clean_tags(extra_tags)

    seen = existing_ids(deck_path)
    blocks = []
    for row in data:
        try:
            front = row[fi].strip()
            back = row[bi].strip()
        except IndexError:
            result.skipped += 1
            continue
        if not front or not back:
            result.skipped += 1
            continue
        tags = list(fixed_tags)
        if ti is not None and ti < len(row):
            tags += clean_tags([row[ti]])
        cid = card_id(front)
        if cid in seen:
            result.duplicates += 1
            continue
        seen.add(cid)
        blocks.append(format_card(front, back, tags))
        result.added += 1
    append_cards(deck_path, blocks)
    return result
