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
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from .scheduler import NEW, CardState

FORMAT_VERSION = 1


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


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.cards: dict[str, CardState] = {}
        self.log: list[dict] = []
        self._load()

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

    def save(self) -> None:
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
