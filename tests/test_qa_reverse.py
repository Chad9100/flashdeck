"""Two-way Q:/A:: blocks make a card in each direction."""

from flashdeck.deck import card_id, parse_deck


def sides(cards):
    return [(c.front, c.back, c.reverse) for c in cards]


def test_block_with_double_colon_answer_is_two_way():
    text = "#t\n\nQ: first\nline two\nA:: the answer\nmore #x\n"
    cards, warnings = parse_deck(text)
    assert warnings == []
    assert sides(cards) == [
        ("first\nline two", "the answer\nmore", False),
        ("the answer\nmore", "first\nline two", True),
    ]
    assert cards[0].id == card_id("first line two")
    assert all(c.tags == ["t", "x"] and c.line == 3 for c in cards)


def test_plain_blocks_stay_one_way_and_flag_does_not_leak():
    text = "Q: a\nA:: b\n\nQ: c\nA: d\n\nQ: e\nA: ::f\n"
    cards, _ = parse_deck(text)
    assert sides(cards) == [
        ("a", "b", False), ("b", "a", True), ("c", "d", False), ("e", "::f", False),
    ]


def test_flag_resets_after_q_directly_following_a_block():
    cards, _ = parse_deck("Q: a\nA:: b\nQ: c\nA: d\n")
    assert sides(cards) == [("a", "b", False), ("b", "a", True), ("c", "d", False)]


def test_identical_sides_make_one_card_and_fence_is_respected():
    cards, _ = parse_deck("Q: x\nA:: x\n")
    assert sides(cards) == [("x", "x", False)]
    cards, _ = parse_deck("Q: code\nA: see\n```\nA:: no\n\nstill\n```\n")
    assert sides(cards) == [("code", "see\n```\nA:: no\n\nstill\n```", False)]
