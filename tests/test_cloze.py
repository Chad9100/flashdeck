"""Cloze deletions: ``{{gap}}`` in a line makes one card per gap."""

from flashdeck.deck import card_id, load_decks, parse_deck


def pairs(cards):
    return [(c.front, c.back) for c in cards]


def test_one_gap_one_card():
    cards, warnings = parse_deck("The capital of France is {{Paris}}.\n", deck="geo", path="geo.md")
    assert warnings == []
    assert pairs(cards) == [
        ("The capital of France is [...].", "The capital of France is Paris."),
    ]
    assert cards[0].line == 1 and cards[0].id == card_id(cards[0].front)


def test_each_gap_gets_its_own_card_with_other_gaps_revealed():
    cards, _ = parse_deck("{{Paris}} is the capital of {{France}}.\n")
    assert pairs(cards) == [
        ("[...] is the capital of France.", "Paris is the capital of France."),
        ("Paris is the capital of [...].", "Paris is the capital of France."),
    ]
    assert cards[0].id != cards[1].id


def test_tags_section_and_trailing():
    cards, _ = parse_deck("#geo\n\nRome is in {{Italy}} #europe\n")
    assert pairs(cards) == [("Rome is in [...]", "Rome is in Italy")]
    assert cards[0].tags == ["geo", "europe"]


def test_one_line_card_wins_and_prose_without_gaps_ignored():
    cards, _ = parse_deck("what is {{x}} :: a placeholder\nplain prose\n{{ not closed\n")
    assert pairs(cards) == [("what is {{x}}", "a placeholder")]


def test_cloze_inside_fence_and_qa_block_is_not_a_cloze_card():
    text = "```\n{{ignored}}\n```\n\nQ: fill {{a}}\nA: b\n"
    cards, _ = parse_deck(text)
    assert pairs(cards) == [("fill {{a}}", "b")]


def test_escaped_hash_and_duplicate_front_across_files(tmp_path):
    cards, _ = parse_deck(r"C\#  is {{managed}}" + "\n")
    assert pairs(cards) == [("C#  is [...]", "C#  is managed")]
    (tmp_path / "a.md").write_text("A is {{b}}\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("A is {{b}}\n", encoding="utf-8")
    loaded, warnings = load_decks([tmp_path])
    assert len(loaded) == 1 and "duplicate question" in warnings[0]
