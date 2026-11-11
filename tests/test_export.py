import csv
import io
from datetime import datetime

from flashdeck.cli import main

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def make_deck(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text(
        "#geo\nCapital of France? :: Paris\n"
        "Say \"hi\", please :: hola #greeting\n"
        "Q: Two lines\nA:\nfirst\nsecond\n\n"
        "pair ::: twin\n",
        encoding="utf-8",
    )
    return deck


def test_csv_export_has_header_and_quotes(tmp_path):
    code, out, _ = run(["export", str(make_deck(tmp_path))])
    assert code == 0
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["front", "back", "tags"]
    assert ["Capital of France?", "Paris", "geo"] in rows
    assert ['Say "hi", please', "hola", "geo greeting"] in rows
    assert ["Two lines", "first\nsecond", "geo"] in rows
    assert ["pair", "twin", "geo"] in rows and ["twin", "pair", "geo"] in rows


def test_anki_export_headers_and_tabs(tmp_path):
    code, out, _ = run(["export", str(make_deck(tmp_path)), "--format", "anki"])
    assert code == 0
    lines = out.splitlines()
    assert lines[:3] == ["#separator:tab", "#html:false", "#tags column:3"]
    assert "Capital of France?\tParis\tgeo" in lines


def test_tag_filter_and_output_file(tmp_path):
    target = tmp_path / "o.csv"
    code, out, err = run(["export", str(make_deck(tmp_path)), "-t", "greeting", "-o", str(target)])
    assert code == 0 and out == ""
    assert "Exported 1 card(s)" in err
    rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines(True)))
    assert len(rows) == 2


def test_csv_round_trips_through_import(tmp_path):
    exported = tmp_path / "x.csv"
    run(["export", str(make_deck(tmp_path)), "-o", str(exported)])
    new = tmp_path / "new.md"
    code, out, _ = run(["import", str(exported), str(new), "--header"])
    assert code == 0
    from flashdeck.deck import parse_deck
    a, _ = parse_deck((tmp_path / "d.md").read_text(encoding="utf-8"))
    b, _ = parse_deck(new.read_text(encoding="utf-8"))
    assert {(c.front, c.back) for c in a} == {(c.front, c.back) for c in b}


def test_unwritable_output(tmp_path):
    code, _, err = run(["export", str(make_deck(tmp_path)), "-o", str(tmp_path / "no" / "x.csv")])
    assert code == 2 and "cannot write" in err
