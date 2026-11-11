import io
from datetime import datetime

from flashdeck.cli import main
from flashdeck.deck import load_decks
from flashdeck.writer import html_to_text, split_anki_header

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(""), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def write(tmp_path, text):
    src = tmp_path / "anki.txt"
    src.write_bytes(text.encode("utf-8"))
    return src


def test_split_header_reads_keys():
    body, info = split_anki_header("#separator:semicolon\n#html:true\n#tags column:3\n#guid column:1\na;b;c\n")
    assert body == "a;b;c\n"
    assert info.delimiter == ";" and info.html is True and info.tags_col == "3"


def test_no_header_returns_none():
    body, info = split_anki_header("front,back\nx,y\n")
    assert info is None and body == "front,back\nx,y\n"


def test_html_to_text():
    assert html_to_text("one<br>two<div>three</div>&amp; &lt;b&gt;") == "one\ntwothree\n& <b>"
    assert html_to_text("<b>bold</b>&nbsp;text") == "bold text"


def test_import_tab_export_with_tags(tmp_path):
    src = write(
        tmp_path,
        "#separator:tab\n#html:false\n#tags column:3\n"
        "perro\tdog\tanimals\ngato\tcat\tanimals pets\n",
    )
    deck = tmp_path / "d.md"
    code, out, _ = run(["import", str(src), str(deck)])
    assert code == 0
    assert out.startswith("Imported 2 card(s)")
    cards, _w = load_decks([deck])
    by_front = {c.front: c for c in cards}
    assert by_front["perro"].back == "dog" and by_front["perro"].tags == ["animals"]
    assert by_front["gato"].tags == ["animals", "pets"]


def test_import_html_fields_and_first_row_is_data(tmp_path):
    src = write(
        tmp_path,
        "#separator:tab\n#html:true\n"
        "front\tback\n"
        "Say <b>hi</b><br>twice\tHola&nbsp;hola\n",
    )
    deck = tmp_path / "d.md"
    code, out, _ = run(["import", str(src), str(deck)])
    assert code == 0 and out.startswith("Imported 2 card(s)")
    cards, _w = load_decks([deck])
    by_front = {c.front: c for c in cards}
    assert by_front["Say hi\ntwice"].back == "Hola hola"
    assert "front" in by_front


def test_import_literal_separator_and_crlf_bom(tmp_path):
    src = write(tmp_path, "﻿#separator:pipe\r\n#tags column:3\r\na|b|t1\r\nc|d|\r\n")
    deck = tmp_path / "d.md"
    code, out, _ = run(["import", str(src), str(deck)])
    assert code == 0 and out.startswith("Imported 2 card(s)")
    cards, _w = load_decks([deck])
    assert {c.front: c.tags for c in cards} == {"a": ["t1"], "c": []}


def test_explicit_columns_override_header(tmp_path):
    src = write(tmp_path, "#separator:tab\n#guid column:1\nG1\tq1\ta1\nG2\tq2\ta2\n")
    deck = tmp_path / "d.md"
    code, out, _ = run(["import", str(src), str(deck), "--front", "2", "--back", "3"])
    assert code == 0 and out.startswith("Imported 2 card(s)")
    cards, _w = load_decks([deck])
    assert {c.front for c in cards} == {"q1", "q2"}


def test_plain_csv_unaffected(tmp_path):
    src = write(tmp_path, "front,back\nx,y\n")
    deck = tmp_path / "d.md"
    code, out, _ = run(["import", str(src), str(deck)])
    assert code == 0 and out.startswith("Imported 1 card(s)")
