"""Review state, kept apart from the decks in one JSON file.

Layout::

    {
      "version": 1,
      "cards": {"<card id>": {"state": "review", "ease": 2.5, ...}},
      "log": [{"id": "...", "at": "2026-11-10T09:30:00", "grade": "good",
               "from": "review", "interval": 6}, ...]
    }

Cards are keyed by the hash of their question, so decks can be edited,
reordered, split or renamed freely. The file is written atomically.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from .scheduler import NEW, CardState

FORMAT_VERSION = 1


SUMMARY = "summary"


def entry_count(entry: Mapping) -> int:
    """How many answers a log entry stands for (more than 1 for a compacted summary)."""
    if entry.get("grade") == SUMMARY:
        return max(int(entry.get("count", 1)), 0)
    return 1


def entry_passed(entry: Mapping) -> int:
    """How many of those answers were not 'again'."""
    if entry.get("grade") == SUMMARY:
        return max(int(entry.get("passed", 0)), 0)
    return 0 if entry.get("grade") == "again" else 1


class StoreError(Exception):
    """The state file exists but cannot be used."""


def data_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    """Directory for flashdeck's state.

    ``FLASHDECK_HOME`` wins; otherwise ``%APPDATA%\\flashdeck`` on Windows,
    ``$XDG_DATA_HOME/flashdeck`` or ``~/.local/share/flashdeck`` elsewhere.
    """
    env = os.environ if environ is None else environ
    override = env.get("FLASHDECK_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "flashdeck"
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "flashdeck"
    return Path.home() / ".local" / "share" / "flashdeck"


def default_state_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    return data_dir(environ) / "state.json"


SQLITE_SUFFIXES = (".sqlite", ".sqlite3", ".db")


def is_sqlite_path(path) -> bool:
    return Path(path).suffix.lower() in SQLITE_SUFFIXES


class Store:
    """Cards and answer log, in a JSON file or (for ``.sqlite``/``.sqlite3``/``.db``
    paths) a SQLite database. The SQLite backend writes only what changed."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.cards: dict[str, CardState] = {}
        self.log: list[dict] = []
        self.sqlite = is_sqlite_path(self.path)
        self._saved_cards: dict[str, str] = {}
        self._saved_log: list[str] = []
        if self.sqlite:
            self._load_sqlite()
        else:
            self._load()

    def _connect(self) -> sqlite3.Connection:
        try:
            con = sqlite3.connect(str(self.path))
            con.execute(
                "CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS log (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)"
            )
            con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            return con
        except sqlite3.Error as exc:
            raise StoreError(f"cannot open state database {self.path}: {exc}") from None

    def _load_sqlite(self) -> None:
        if not self.path.exists():
            return
        con = self._connect()
        try:
            row = con.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            if row is not None and row[0] != str(FORMAT_VERSION):
                raise StoreError(
                    f"state database {self.path} has format version {row[0]}; "
                    f"this flashdeck understands version {FORMAT_VERSION}"
                )
            for cid, data in con.execute("SELECT id, data FROM cards"):
                self.cards[cid] = CardState.from_dict(json.loads(data))
                self._saved_cards[cid] = data
            for (data,) in con.execute("SELECT data FROM log ORDER BY seq"):
                entry = json.loads(data)
                if isinstance(entry, dict) and "id" in entry and "grade" in entry:
                    self.log.append(entry)
                    self._saved_log.append(data)
        except (sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
            raise StoreError(f"cannot read state database {self.path}: {exc}") from None
        finally:
            con.close()

    def _save_sqlite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        cards = {k: json.dumps(v.to_dict(), sort_keys=True) for k, v in self.cards.items()}
        log = [json.dumps(e, sort_keys=True, ensure_ascii=False) for e in self.log]
        con = self._connect()
        try:
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)",
                    (str(FORMAT_VERSION),),
                )
                for cid in self._saved_cards.keys() - cards.keys():
                    con.execute("DELETE FROM cards WHERE id=?", (cid,))
                for cid, data in cards.items():
                    if self._saved_cards.get(cid) != data:
                        con.execute("INSERT OR REPLACE INTO cards (id, data) VALUES (?, ?)", (cid, data))
                n = len(self._saved_log)
                if log[:n] != self._saved_log:
                    con.execute("DELETE FROM log")
                    n = 0
                con.executemany("INSERT INTO log (data) VALUES (?)", [(d,) for d in log[n:]])
        except sqlite3.Error as exc:
            raise StoreError(f"cannot write state database {self.path}: {exc}") from None
        finally:
            con.close()
        self._saved_cards = cards
        self._saved_log = log

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = self.path.read_bytes().decode("utf-8-sig")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreError(f"cannot read state file {self.path}: {exc}") from None
        if not isinstance(data, dict):
            raise StoreError(f"state file {self.path} is not a JSON object")
        version = data.get("version", FORMAT_VERSION)
        if version != FORMAT_VERSION:
            raise StoreError(
                f"state file {self.path} has format version {version}; "
                f"this flashdeck understands version {FORMAT_VERSION}"
            )
        try:
            self.cards = {str(k): CardState.from_dict(v) for k, v in data.get("cards", {}).items()}
        except (ValueError, TypeError, AttributeError) as exc:
            raise StoreError(f"state file {self.path} has a bad card entry: {exc}") from None
        log = data.get("log", [])
        self.log = [e for e in log if isinstance(e, dict) and "id" in e and "grade" in e]

    def get(self, card_id: str) -> CardState:
        return self.cards.get(card_id) or CardState()

    def state_of(self, card_id: str) -> str:
        st = self.cards.get(card_id)
        return st.state if st else NEW

    def record(self, card_id: str, before: CardState, after: CardState, grade: str, at: str) -> None:
        self.cards[card_id] = after
        self.log.append(
            {"id": card_id, "at": at, "grade": grade, "from": before.state, "interval": after.interval}
        )

    def unrecord(self, card_id: str, previous: Optional[CardState]) -> None:
        """Take back the most recent ``record`` for ``card_id``.

        ``previous`` is the card's stored state before that answer, or
        ``None`` if it had no entry (a new card), in which case the entry is
        removed again. The matching log entry (the last one for this card)
        is dropped.
        """
        if previous is None:
            self.cards.pop(card_id, None)
        else:
            self.cards[card_id] = previous
        for i in range(len(self.log) - 1, -1, -1):
            if self.log[i].get("id") == card_id:
                del self.log[i]
                break

    def orphans(self, live_ids) -> list[str]:
        """Sorted ids with a state entry that is not in ``live_ids``."""
        live = set(live_ids)
        return sorted(k for k in self.cards if k not in live)

    def prune(self, ids) -> int:
        """Remove state entries and their log entries for ``ids``; return how many cards went."""
        gone = {i for i in ids if i in self.cards}
        for i in gone:
            del self.cards[i]
        self.log = [e for e in self.log if e.get("id") not in gone]
        return len(gone)

    def rename(self, old_id: str, new_id: str) -> int:
        """Move a card's state and log entries from ``old_id`` to ``new_id``.

        Returns the number of log entries moved. Raises ``KeyError`` if
        ``old_id`` has no state and ``ValueError`` if ``new_id`` already has
        some (or is the same id), so no history is ever overwritten.
        """
        if old_id not in self.cards:
            raise KeyError(old_id)
        if new_id == old_id or new_id in self.cards:
            raise ValueError(new_id)
        self.cards[new_id] = self.cards.pop(old_id)
        moved = 0
        for entry in self.log:
            if entry.get("id") == old_id:
                entry["id"] = new_id
                moved += 1
        return moved

    def compact(self, cutoff: str) -> tuple[int, int]:
        """Fold log entries dated before ``cutoff`` (YYYY-MM-DD) into per-day summaries.

        Entries for the same card, day and previous state become one entry
        ``{"id", "at": "YYYY-MM-DD", "grade": "summary", "from", "count",
        "passed", "interval"}``, which statistics count correctly. Existing
        summaries are kept as they are. Returns ``(entries before, entries after)``
        for the folded part of the log.
        """
        groups: dict[tuple, dict] = {}
        kept: list[dict] = []
        before = 0
        for e in self.log:
            at = str(e.get("at", ""))[:10]
            if e.get("grade") == SUMMARY or len(at) != 10 or at >= cutoff:
                kept.append(e)
                continue
            before += 1
            key = (e["id"], at, e.get("from"))
            g = groups.get(key)
            if g is None:
                g = groups[key] = {
                    "id": e["id"], "at": at, "grade": SUMMARY, "from": e.get("from"),
                    "count": 0, "passed": 0, "interval": 0,
                }
            g["count"] += 1
            g["passed"] += entry_passed(e)
            g["interval"] = e.get("interval", g["interval"])
        self.log = sorted(groups.values(), key=lambda g: g["at"]) + kept
        return before, len(groups)

    def save(self) -> None:
        if self.sqlite:
            self._save_sqlite()
            return
        data = {
            "version": FORMAT_VERSION,
            "cards": {k: v.to_dict() for k, v in sorted(self.cards.items())},
            "log": self.log,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(data, fh, indent=1, ensure_ascii=False)
                fh.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
