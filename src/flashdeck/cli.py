"""Command-line interface."""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence, TextIO

from . import __version__
from .deck import Card, DeckError, card_id, filter_tags, load_decks, parse_deck
from .export import FORMATS, export_cards
from .editor import EditorError, open_in_editor
from .session import EditResult, LineReader, build_queue, match_edited, run_session, summary
from .stats import (
    compute_grouped, compute_stats, due_counts, due_to_dict, format_due, format_grouped,
    format_heatmap, format_stats, grouped_to_dict, heatmap_to_dict, review_days, stats_to_dict,
)
from .store import Store, StoreError, default_state_path
from .writer import append_cards, clean_tags, existing_ids, format_card, format_cloze, import_rows, read_csv_rows


def _positive(text: str) -> int:
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}") from None
    if n < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return n


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--state",
        metavar="PATH",
        help="review state file (default: $FLASHDECK_HOME/state.json or the per-user data dir)",
    )
    tagged = argparse.ArgumentParser(add_help=False)
    tagged.add_argument(
        "-t", "--tag", action="append", default=[], metavar="TAG",
        help="only cards with this tag (repeatable: any of them)",
    )

    p = argparse.ArgumentParser(
        prog="flashdeck",
        description="Spaced-repetition flashcards from plain-text decks (SM-2).",
    )
    p.add_argument("--version", action="version", version=f"flashdeck {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    r = sub.add_parser("review", parents=[common, tagged], help="review due and new cards")
    r.add_argument("decks", nargs="+", metavar="DECK", help="deck files or directories")
    r.add_argument("--new", type=_positive, default=20, metavar="N",
                   help="new cards per day (default 20)")
    r.add_argument("--limit", type=_positive, default=200, metavar="N",
                   help="most cards in this session (default 200)")

    d = sub.add_parser("due", parents=[common, tagged], help="show what is due, per deck")
    d.add_argument("decks", nargs="+", metavar="DECK")
    d.add_argument("--json", action="store_true", help="print machine-readable JSON")

    s = sub.add_parser("stats", parents=[common, tagged], help="retention, card states, 7-day forecast")
    s.add_argument("decks", nargs="+", metavar="DECK")
    s.add_argument("--days", type=_positive, default=7, metavar="N", help="forecast length (default 7)")
    s.add_argument("--json", action="store_true", help="print machine-readable JSON")
    grp = s.add_mutually_exclusive_group()
    grp.add_argument("--by-deck", action="store_true", help="one row per deck instead of the summary")
    grp.add_argument("--by-tag", action="store_true",
                     help="one row per tag (a card counts under each of its tags)")
    grp.add_argument("--heatmap", action="store_true",
                     help="12-week review heatmap with current and longest study streak")

    o =sub.add_parser("orphans", parents=[common],
                       help="list (or --prune) state entries whose card is in no given deck")
    o.add_argument("decks", nargs="+", metavar="DECK", help="every deck you still use")
    o.add_argument("--prune", action="store_true",
                   help="remove the orphaned entries and their log history")

    rn = sub.add_parser("rename-question", parents=[common],
                        help="carry a card's review history over to a reworded question")
    rn.add_argument("old", metavar="OLD", help="the old question, or its id as shown by 'orphans'")
    rn.add_argument("new", metavar="NEW", help="the new question")

    x = sub.add_parser("export", parents=[tagged], help="write cards as CSV or Anki text")
    x.add_argument("decks", nargs="+", metavar="DECK", help="deck files or directories")
    x.add_argument("--format", choices=FORMATS, default="csv", help="output format (default csv)")
    x.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of standard output")

    a = sub.add_parser("add", help="append a card to a deck file")
    a.add_argument("deck", metavar="DECK", help="deck file (created if missing)")
    a.add_argument("front", metavar="QUESTION")
    a.add_argument("back", metavar="ANSWER", nargs="?",
                   help="the answer (omit with --cloze)")
    a.add_argument("-t", "--tag", action="append", default=[], metavar="TAG")
    a.add_argument("-c", "--cloze", action="store_true",
                   help="treat QUESTION as a cloze line with {{gaps}}; no ANSWER")
    a.add_argument("-r", "--reverse", action="store_true",
                   help="also quiz answer -> question (writes 'question ::: answer')")

    i = sub.add_parser("import", help="append cards from a CSV file to a deck")
    i.add_argument("csv", metavar="CSV", help="CSV/TSV file, or - for standard input")
    i.add_argument("deck", metavar="DECK", help="deck file (created if missing)")
    i.add_argument("--delimiter", metavar="CHAR", help="field separator (default: detect)")
    hdr = i.add_mutually_exclusive_group()
    hdr.add_argument("--header", dest="header", action="store_true", default=None,
                     help="first row is a header")
    hdr.add_argument("--no-header", dest="header", action="store_false",
                     help="first row is data")
    i.add_argument("--front", metavar="COL", help="question column: number (1-based) or header name")
    i.add_argument("--back", metavar="COL", help="answer column: number or header name")
    i.add_argument("--tags", metavar="COL", help="tags column (space/comma separated)")
    i.add_argument("-t", "--tag", action="append", default=[], metavar="TAG",
                   help="tag every imported card")
    return p


def _state_path(args) -> Path:
    return Path(args.state) if args.state else default_state_path()


EditFile = Callable[[str, int], None]


def _load_all(args, err: TextIO) -> list[Card]:
    cards, warnings = load_decks(args.decks)
    for w in warnings:
        err.write(f"flashdeck: warning: {w}\n")
    return cards


def _load(args, err: TextIO) -> list[Card]:
    return filter_tags(_load_all(args, err), args.tag)


def _edit_callback(args, err: TextIO, edit_file: EditFile, all_cards: list[Card]):
    """``e`` during review: open the card's deck at its line, then reload the decks."""
    known = {"ids": {c.id for c in all_cards}}

    def edit(card: Card) -> Optional[EditResult]:
        if not card.path:
            err.write("  This card has no deck file to edit.\n")
            return None
        try:
            edit_file(card.path, card.line)
        except EditorError as exc:
            err.write(f"  flashdeck: {exc}; card unchanged\n")
            return None
        try:
            reloaded = _load_all(args, err)
        except DeckError as exc:
            err.write(f"  flashdeck: {exc}; card unchanged\n")
            return None
        found = match_edited(card, known["ids"], reloaded)
        known["ids"] = {c.id for c in reloaded}
        return EditResult(found, filter_tags(reloaded, args.tag))

    return edit


def cmd_review(args, out, err, clock, read, edit_file: EditFile = open_in_editor) -> int:
    all_cards = _load_all(args, err)
    cards = filter_tags(all_cards, args.tag)
    store = Store(_state_path(args))
    today = clock().date()
    queue = build_queue(cards, store, today, args.new, args.limit)
    if not queue:
        out.write("Nothing to review right now.")
        upcoming = sorted(
            store.get(c.id).due for c in cards if store.get(c.id).due and store.state_of(c.id) != "new"
        )
        if upcoming:
            out.write(f" Next card is due {upcoming[0]}.")
        out.write("\n")
        return 0
    n_new = sum(1 for c in queue if store.state_of(c.id) == "new")
    out.write(f"{len(queue)} card(s): {len(queue) - n_new} due, {n_new} new.\n")
    edit = _edit_callback(args, err, edit_file, all_cards)
    result = run_session(queue, store, read, out, clock, edit=edit)
    out.write("\n" + summary(result) + "\n")
    return 0


def cmd_due(args, out, err, clock) -> int:
    cards = _load(args, err)
    store = Store(_state_path(args))
    rows = due_counts(cards, store, clock().date())
    if args.json:
        out.write(json.dumps(due_to_dict(rows), ensure_ascii=False, indent=2) + "\n")
    else:
        out.write(format_due(rows) + "\n")
    return 0


def cmd_stats(args, out, err, clock) -> int:
    cards = _load(args, err)
    store = Store(_state_path(args))
    if args.heatmap:
        days = review_days(cards, store)
        today = clock().date()
        if args.json:
            out.write(json.dumps(heatmap_to_dict(days, today), indent=2) + "\n")
        else:
            out.write(format_heatmap(days, today) + "\n")
        return 0
    by = "deck" if args.by_deck else "tag" if args.by_tag else None
    if by:
        groups = compute_grouped(cards, store, clock().date(), by)
        if args.json:
            out.write(json.dumps(grouped_to_dict(groups, by), ensure_ascii=False, indent=2) + "\n")
        else:
            out.write(format_grouped(groups, by) + "\n")
        return 0
    st = compute_stats(cards, store, clock().date(), days=args.days)
    if args.json:
        out.write(json.dumps(stats_to_dict(st), ensure_ascii=False, indent=2) + "\n")
    else:
        out.write(format_stats(st) + "\n")
    return 0


def cmd_orphans(args, out, err) -> int:
    cards = _load_all(args, err)
    store = Store(_state_path(args))
    orphans = store.orphans(c.id for c in cards)
    if not orphans:
        out.write("No orphaned state entries.\n")
        return 0
    for cid in orphans:
        st = store.cards[cid]
        out.write(f"{cid}  {st.state}, interval {st.interval}d, due {st.due or '-'}\n")
    if args.prune:
        logs = len(store.log)
        store.prune(orphans)
        store.save()
        out.write(f"Pruned {len(orphans)} card(s) and {logs - len(store.log)} log entries.\n")
    else:
        out.write(f"{len(orphans)} orphaned card(s); run again with --prune to remove them.\n")
    return 0


def cmd_rename_question(args, out, err) -> int:
    store = Store(_state_path(args))
    old_id = args.old.strip() if args.old.strip() in store.cards else card_id(args.old)
    new_id = card_id(args.new)
    if old_id not in store.cards:
        err.write("flashdeck: no review history for that question\n")
        return 1
    if new_id == old_id:
        err.write("flashdeck: the new question has the same id as the old one; nothing to do\n")
        return 1
    if new_id in store.cards:
        err.write("flashdeck: the new question already has review history; "
                  "refusing to overwrite it\n")
        return 1
    moved = store.rename(old_id, new_id)
    store.save()
    out.write(f"Moved {old_id} -> {new_id} ({moved} log entries).\n")
    return 0


def cmd_export(args, out, err) -> int:
    cards = _load(args, err)
    text = export_cards(cards, args.format)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError as exc:
            err.write(f"flashdeck: cannot write {args.output}: {exc.strerror or exc}\n")
            return 2
        err.write(f"Exported {len(cards)} card(s) to {args.output}.\n")
    else:
        out.write(text)
    return 0


def cmd_add(args, out, err) -> int:
    path = Path(args.deck)
    if args.cloze:
        if args.back is not None or args.reverse:
            err.write("flashdeck: --cloze takes one text with {{gaps}}, no answer, and not --reverse\n")
            return 2
    elif args.back is None:
        err.write("flashdeck: add needs a question and an answer\n")
        return 2
    try:
        if args.cloze:
            block = format_cloze(args.front, args.tag)
        else:
            block = format_card(args.front, args.back, args.tag, reverse=args.reverse)
    except ValueError as exc:
        err.write(f"flashdeck: {exc}\n")
        return 2
    have = existing_ids(path)
    if args.cloze:
        new_cards, _ = parse_deck(block)
        if any(c.id in have for c in new_cards):
            err.write(f"flashdeck: {path} already has a card for one of those gaps\n")
            return 1
        append_cards(path, [block])
        out.write(f"Added to {args.deck}: {block} ({len(new_cards)} card(s))\n")
        return 0
    if card_id(args.front) in have:
        err.write(f"flashdeck: {path} already has that question\n")
        return 1
    if args.reverse and card_id(args.back) in have:
        err.write(f"flashdeck: {path} already has the answer as a question (needed for the reverse card)\n")
        return 1
    append_cards(path, [block])
    out.write(f"Added to {args.deck}: {block.splitlines()[0]}\n")
    return 0


def cmd_import(args, out, err, stdin: TextIO) -> int:
    if args.csv == "-":
        text = stdin.read()
    else:
        try:
            text = Path(args.csv).read_bytes().decode("utf-8-sig")
        except OSError as exc:
            err.write(f"flashdeck: cannot read {args.csv}: {exc.strerror or exc}\n")
            return 2
        except UnicodeDecodeError:
            err.write(f"flashdeck: {args.csv} is not valid UTF-8\n")
            return 2
    delimiter = args.delimiter
    if delimiter in ("\\t", "tab"):
        delimiter = "\t"
    if delimiter is None and args.csv.lower().endswith(".tsv"):
        delimiter = "\t"
    try:
        clean_tags(args.tag)
        rows = read_csv_rows(text, delimiter)
        res = import_rows(
            rows, Path(args.deck), header=args.header,
            front_col=args.front, back_col=args.back, tags_col=args.tags, extra_tags=args.tag,
        )
    except ValueError as exc:
        err.write(f"flashdeck: {exc}\n")
        return 2
    msg = f"Imported {res.added} card(s) into {args.deck}"
    extras = []
    if res.duplicates:
        extras.append(f"{res.duplicates} already in the deck")
    if res.skipped:
        extras.append(f"{res.skipped} incomplete row(s) skipped")
    out.write(msg + (f" ({'; '.join(extras)})" if extras else "") + ".\n")
    return 0


def _real_stdin() -> TextIO:
    """Standard input; when piped, decoded as UTF-8 with any BOM dropped.

    Without this, Windows would decode piped bytes with the ANSI code page and
    a BOM written by PowerShell or Notepad would turn into junk characters.
    """
    stream = sys.stdin
    try:
        if stream is not None and not stream.isatty() and hasattr(stream, "buffer"):
            return io.TextIOWrapper(stream.buffer, encoding="utf-8-sig", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    return stream


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
    clock: Optional[Callable[[], datetime]] = None,
    edit_file: Optional[EditFile] = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    inp = stdin if stdin is not None else _real_stdin()
    clock = clock or datetime.now
    if stdout is None:
        # Cards are usually not ASCII. A console handles that itself; when
        # piped, write UTF-8 rather than the Windows ANSI code page.
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream.isatty():
                    stream.reconfigure(errors="replace")
                else:
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    try:
        if args.command == "review":
            return cmd_review(args, out, err, clock, LineReader(inp), edit_file or open_in_editor)
        if args.command == "due":
            return cmd_due(args, out, err, clock)
        if args.command == "stats":
            return cmd_stats(args, out, err, clock)
        if args.command == "orphans":
            return cmd_orphans(args, out, err)
        if args.command == "rename-question":
            return cmd_rename_question(args, out, err)
        if args.command == "export":
            return cmd_export(args, out, err)
        if args.command == "add":
            return cmd_add(args, out, err)
        if args.command == "import":
            return cmd_import(args, out, err, inp)
    except (DeckError, StoreError) as exc:
        err.write(f"flashdeck: {exc}\n")
        return 2
    except KeyboardInterrupt:
        err.write("\nflashdeck: interrupted\n")
        return 130
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
