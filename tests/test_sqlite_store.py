import io
import sqlite3
from datetime import datetime

import pytest

from flashdeck.cli import main
from flashdeck.scheduler import CardState
from flashdeck.store import Store, StoreError

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(stdin), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def answer(store, cid, grade="good", n=1):
    st = CardState(state="review", interval=n, due="2026-11-11", reps=n)
    store.record(cid, store.get(cid), st, grade, f"2026-11-10T09:0{n}:00")


def test_round_trip(tmp_path):
    path = tmp_path / "state.sqlite"
    s = Store(path)
    answer(s, "aaa")
    answer(s, "bbb", "again", 2)
    s.save()
    t = Store(path)
    assert t.sqlite
    assert t.cards == s.cards
    assert t.log == s.log


def test_json_path_stays_json(tmp_path):
    s = Store(tmp_path / "state.json")
    assert not s.sqlite
    answer(s, "aaa")
    s.save()
    assert (tmp_path / "state.json").read_text(encoding="utf-8").startswith("{")


def test_incremental_save_appends_log_and_deletes_cards(tmp_path):
    path = tmp_path / "s.db"
    s = Store(path)
    answer(s, "aaa")
    s.save()
    answer(s, "bbb", n=2)
    s.save()
    con = sqlite3.connect(str(path))
    seqs = [r[0] for r in con.execute("SELECT seq FROM log ORDER BY seq")]
    con.close()
    assert seqs == [1, 2]  # the first row was not rewritten
    s.prune(["aaa"])
    s.save()
    t = Store(path)
    assert list(t.cards) == ["bbb"]
    assert [e["id"] for e in t.log] == ["bbb"]


def test_unrecord_removes_log_row(tmp_path):
    path = tmp_path / "s.sqlite3"
    s = Store(path)
    answer(s, "aaa")
    s.save()
    s.unrecord("aaa", None)
    s.save()
    t = Store(path)
    assert t.cards == {} and t.log == []


def test_cli_uses_sqlite_state(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("a :: 1\n", encoding="utf-8")
    state = tmp_path / "state.sqlite"
    code, out, _ = run(["review", str(deck), "--state", str(state)], stdin="\n3\n")
    assert code == 0
    assert state.exists() and not (tmp_path / "state.json").exists()
    code, out, _ = run(["stats", str(deck), "--state", str(state)])
    assert code == 0
    assert "review" in out


def test_garbage_file_is_a_store_error(tmp_path):
    path = tmp_path / "bad.sqlite"
    path.write_text("this is not a database, just text " * 20, encoding="utf-8")
    with pytest.raises(StoreError):
        Store(path)


def test_cli_reports_bad_database(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("a :: 1\n", encoding="utf-8")
    path = tmp_path / "bad.sqlite"
    path.write_text("not a database " * 50, encoding="utf-8")
    code, _, err = run(["due", str(deck), "--state", str(path)])
    assert code != 0
    assert "bad.sqlite" in err
