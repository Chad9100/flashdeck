import pytest

from flashdeck.deck import Card, DeckError, card_id, deck_files, filter_tags, load_decks, parse_deck


def fronts(cards):
    return [c.front for c in cards]


def test_one_line_cards():
    cards, warnings = parse_deck("hola :: hello\nadiós :: goodbye\n")
    assert [(c.front, c.back) for c in cards] == [("hola", "hello"), ("adiós", "goodbye")]
    assert warnings == []
    assert cards[1].line == 2


def test_double_colon_without_spaces_is_not_a_separator():
    cards, _ = parse_deck("What is std::vector? :: a dynamic array\n")
    assert cards[0].front == "What is std::vector?"
    assert cards[0].back == "a dynamic array"


def test_back_may_contain_separator():
    cards, _ = parse_deck("a :: b :: c\n")
    assert (cards[0].front, cards[0].back) == ("a", "b :: c")


def test_qa_block_multiline():
    text = "Q: How do you say\n\"I am tired\"?\nA: Estoy cansado.\n(cansada if female)\n\nnext :: card\n"
    cards, warnings = parse_deck(text)
    assert cards[0].front == 'How do you say\n"I am tired"?'
    assert cards[0].back == "Estoy cansado.\n(cansada if female)"
    assert cards[0].line == 1
    assert cards[1].front == "next"
    assert warnings == []


def test_qa_block_ended_by_next_question():
    cards, _ = parse_deck("Q: one\nA: 1\nQ: two\nA: 2\n")
    assert [(c.front, c.back) for c in cards] == [("one", "1"), ("two", "2")]


def test_qa_block_with_fenced_code_keeps_blank_lines():
    text = "Q: Print hello in Python?\nA:\n```python\nx = 1\n\nprint('hello')\n```\n\nafter :: x\n"
    cards, _ = parse_deck(text)
    assert cards[0].back == "```python\nx = 1\n\nprint('hello')\n```"
    assert cards[1].front == "after"


def test_fenced_code_outside_cards_is_ignored():
    cards, _ = parse_deck("```\nnot :: a card\n```\nreal :: card\n")
    assert fronts(cards) == ["real"]


def test_section_tags_and_inline_tags():
    text = "#spanish #verbs\n\nser :: to be #irregular\n\n#french\nêtre :: to be\n"
    cards, _ = parse_deck(text)
    assert cards[0].tags == ["spanish", "verbs", "irregular"]
    assert cards[0].back == "to be"
    assert cards[1].tags == ["french"]


def test_markdown_heading_is_not_a_tag_line():
    cards, _ = parse_deck("# Chapter 1\n\na :: b\n")
    assert cards[0].tags == []


def test_tag_on_last_line_of_qa_block():
    cards, _ = parse_deck("Q: q\nA: answer\n#geo #capitals\n")
    assert cards[0].back == "answer"
    assert cards[0].tags == ["geo", "capitals"]


def test_escaped_hash_and_csharp_are_not_tags():
    text = r"Best language? :: C# \#1" + "\n" + r"header? :: use \#include" + "\n"
    cards, _ = parse_deck(text)
    assert cards[0].back == "C# #1"
    assert cards[1].back == "use #include"
    assert cards[0].tags == [] and cards[1].tags == []


def test_numeric_hash_is_not_a_tag():
    cards, _ = parse_deck("Who? :: issue #42\n")
    assert cards[0].back == "issue #42"
    assert cards[0].tags == []


def test_warnings_for_incomplete_cards():
    cards, warnings = parse_deck("lonely ::\nQ: no answer here\n\nQ: x\nA:\n\n", path="d.md")
    assert cards == []
    assert len(warnings) == 3
    assert warnings[0].startswith("d.md:1:")
    assert "no 'A:' answer" in warnings[1]
    assert "empty answer" in warnings[2]


def test_prose_is_ignored():
    text = "Some notes about verbs.\n- a list item\n> quote\n\nok :: yes\n"
    cards, warnings = parse_deck(text)
    assert fronts(cards) == ["ok"] and warnings == []


def test_bom_and_crlf():
    cards, _ = parse_deck("\ufeffhola :: hello\r\nQ: a\r\nA: b\r\n")
    assert [(c.front, c.back) for c in cards] == [("hola", "hello"), ("a", "b")]


def test_card_id_is_stable_and_ignores_whitespace_and_answer():
    assert card_id("What  is\nthis?") == card_id("What is this?")
    assert len(card_id("x")) == 12
    assert Card("hola", "hello").id == Card(" hola ", "something else").id
    assert card_id("Hola") != card_id("hola")


def test_load_decks_from_files_and_directory_with_bom(tmp_path):
    d = tmp_path / "decks"
    (d / "sub").mkdir(parents=True)
    (d / "a.md").write_bytes("\ufeffuno :: one\n".encode("utf-8"))
    (d / "sub" / "b.txt").write_text("dos :: two\n", encoding="utf-8")
    (d / "notes.pdf").write_text("tres :: three\n", encoding="utf-8")
    (d / ".hidden").mkdir()
    (d / ".hidden" / "c.md").write_text("cuatro :: four\n", encoding="utf-8")
    cards, _ = load_decks([d])
    assert fronts(cards) == ["uno", "dos"]
    assert cards[0].deck == "a"
    assert cards[1].deck == "b"


def test_duplicates_across_decks_kept_once(tmp_path):
    (tmp_path / "a.md").write_text("hola :: hello\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("hola :: hi\n", encoding="utf-8")
    cards, warnings = load_decks([tmp_path / "a.md", tmp_path / "b.md", tmp_path / "a.md"])
    assert len(cards) == 1 and cards[0].back == "hello"
    assert len(warnings) == 1 and "duplicate" in warnings[0]


def test_missing_deck_and_bad_utf8(tmp_path):
    with pytest.raises(DeckError, match="no such deck"):
        deck_files([tmp_path / "nope.md"])
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"caf\xe9 :: coffee\n")
    with pytest.raises(DeckError, match="not valid UTF-8"):
        load_decks([bad])
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DeckError, match="no deck files"):
        deck_files([empty])


def test_filter_tags():
    cards = [Card("a", "1", ["x"]), Card("b", "2", ["y"]), Card("c", "3", [])]
    assert fronts(filter_tags(cards, ["#X"])) == ["a"]
    assert fronts(filter_tags(cards, ["x", "y"])) == ["a", "b"]
    assert fronts(filter_tags(cards, [])) == ["a", "b", "c"]
