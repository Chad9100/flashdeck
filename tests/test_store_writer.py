import json

import pytest

from flashdeck.deck import load_decks, parse_deck
from flashdeck.scheduler import CardState, REVIEW
from flashdeck.store import Store, StoreError, data_dir
from flashdeck.writer import append_cards, clean_tags, format_card, import_rows, read_csv_rows


# --- store -------------------------------------------------------------------

def test_store_missing_file_is_empty_and_save_round_trips(tmp_path):
    path = tmp_path / "sub" / "state.json"
    store = Store(path)
    assert store.cards == {} and store.log == []
    before = CardState()
    after = CardState(state=REVIEW, interval=1, reps=1, due="2026-11-11")
    store.record("abc", before, after, "good", "2026-11-10T09:00:00")
    store.save()
    again = Store(path)
    assert again.cards["abc"] == after
    assert again.log == [{"id": "abc", "at": "2026-11-10T09:00:00", "grade": "good", "from": "new", "interval": 1}]
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]  # no temp files left


def test_store_rejects_corrupt_file_without_overwriting(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreError, match="cannot read"):
        Store(path)
    assert path.read_text(encoding="utf-8") == "{not json"
    path.write_text(json.dumps({"version": 99}), encoding="utf-8")
    with pytest.raises(StoreError, match="version 99"):
        Store(path)
    path.write_text(json.dumps({"cards": {"x": {"state": "zombie"}}}), encoding="utf-8")
    with pytest.raises(StoreError, match="bad card"):
        Store(path)


def test_store_accepts_bom_and_skips_bad_log_entries(tmp_path):
    path = tmp_path / "state.json"
    data = {"version": 1, "cards": {}, "log": [{"id": "a", "grade": "good"}, "junk", {"no": "id"}]}
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode())
    assert len(Store(path).log) == 1


def test_data_dir_precedence(tmp_path):
    assert data_dir({"FLASHDECK_HOME": str(tmp_path)}) == tmp_path
    assert data_dir({"XDG_DATA_HOME": "/x", "APPDATA": "C:/AppData"}).name == "flashdeck"


# --- writer ------------------------------------------------------------------

def roundtrip(front, back, tags=()):
    cards, warnings = parse_deck(format_card(front, back, tags) + "\n")
    assert warnings == []
    assert len(cards) == 1
    return cards[0]


@pytest.mark.parametrize(
    "front,back,tags",
    [
        ("hola", "hello", ["spanish"]),
        ("What is std::vector?", "a dynamic array", []),
        ("a :: b", "c", []),
        ("Q: tricky", "answer", []),
        ("line one\nline two", "back", ["x"]),
        ("front", "use #include and #pragma", []),
        ("C#?", "a language", []),
        ("code?", "```\nx = 1\n\ny = 2\n```", []),
    ],
)
def test_format_card_round_trips(front, back, tags):
    card = roundtrip(front, back, tags)
    assert card.front == front
    assert card.back == back.replace("\n\n", "\n")
    assert card.tags == tags


def test_format_card_validation():
    assert format_card("a", "b", ["#One", "two,three"]) == "a :: b #one #two #three"
    with pytest.raises(ValueError):
        format_card("", "b")
    with pytest.raises(ValueError):
        clean_tags(["bad!tag"])


def test_append_keeps_bom_crlf_and_separates_blocks(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_bytes(b"\xef\xbb\xbfQ: one\r\nA: 1")
    append_cards(deck, ["two :: 2", "three :: 3", "Q: four\nA: 4"])
    raw = deck.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    cards, warnings = load_decks([deck])
    assert [(c.front, c.back) for c in cards] == [("one", "1"), ("two", "2"), ("three", "3"), ("four", "4")]
    assert warnings == []
    text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    assert "two :: 2\nthree :: 3\n\nQ: four" in text


def test_append_creates_file_and_parent(tmp_path):
    deck = tmp_path / "new" / "deck.md"
    append_cards(deck, ["a :: b"])
    assert deck.read_text(encoding="utf-8") == "a :: b\n"


def test_import_rows_with_header_tags_and_duplicates(tmp_path):
    deck = tmp_path / "d.md"
    deck.write_text("hola :: hello\n", encoding="utf-8")
    rows = read_csv_rows("\ufeffQuestion;Answer;Tags\nhola;hi;x\ngato;cat;animals pets\nperro;;\n")
    res = import_rows(rows, deck, extra_tags=["es"])
    assert (res.added, res.duplicates, res.skipped) == (1, 1, 1)
    cards, _ = load_decks([deck])
    assert cards[-1].front == "gato" and cards[-1].tags == ["es", "animals", "pets"]


def test_import_rows_by_column_number_without_header(tmp_path):
    deck = tmp_path / "d.md"
    rows = read_csv_rows("1,uno,one\n2,dos,two\n")
    res = import_rows(rows, deck, header=False, front_col="2", back_col="3")
    assert res.added == 2
    cards, _ = load_decks([deck])
    assert [(c.front, c.back) for c in cards] == [("uno", "one"), ("dos", "two")]
    with pytest.raises(ValueError, match="no column named"):
        import_rows(read_csv_rows("front,back\na,b\n"), deck, front_col="nope")
