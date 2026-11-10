import io
import json
from datetime import datetime

import pytest

from flashdeck.cli import main
from flashdeck.deck import parse_deck
from flashdeck.editor import EditorError, build_command, editor_command_line, open_in_editor
from flashdeck.session import EditResult, LineReader, SessionResult, match_edited, run_session, summary
from flashdeck.store import Store

NOW = datetime(2026, 11, 10, 9, 0, 0)


def reader(*answers):
    return LineReader(io.StringIO("".join(a + "\n" for a in answers)))


def run_review(deck, state, answers, edit_file):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["review", str(deck), "--state", str(state)],
        stdin=io.StringIO("".join(a + "\n" for a in answers)),
        stdout=out,
        stderr=err,
        clock=lambda: NOW,
        edit_file=edit_file,
    )
    return code, out.getvalue(), err.getvalue()


class FakeEditor:
    """Stands in for $EDITOR: records the call and rewrites the file."""

    def __init__(self, change=None, fail=False):
        self.calls = []
        self.change = change
        self.fail = fail

    def __call__(self, path, line):
        self.calls.append((path, line))
        if self.fail:
            raise EditorError("editor 'vi' exited with status 1")
        if self.change:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.change(text))


def test_edit_answer_keeps_card_and_shows_new_text(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("# Spanish\n\nhola :: helo\nadiós :: goodbye\n", encoding="utf-8")
    state = tmp_path / "state.json"
    editor = FakeEditor(lambda t: t.replace("helo", "hello"))
    # Reveal, spot the typo, edit at the grade prompt, then answer both cards.
    code, out, err = run_review(deck, state, ["", "e", "", "3", "", "3"], editor)
    assert code == 0, err
    assert editor.calls == [(str(deck), 3)]
    assert "-> reloaded after editing" in out
    after_edit = out.split("reloaded after editing", 1)[1]
    assert "  hello\n" in after_edit and "helo" not in after_edit
    data = json.loads(state.read_text(encoding="utf-8"))
    assert [e["grade"] for e in data["log"]] == ["good", "good"]
    assert "Edited 1." in out


def test_edit_at_question_prompt_refreshes_rest_of_queue(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("uno :: one\ndos :: too\n", encoding="utf-8")
    editor = FakeEditor(lambda t: "#numbers\n" + t.replace("too", "two"))
    code, out, err = run_review(deck, tmp_path / "s.json", ["e", "", "3", "", "3"], editor)
    assert code == 0, err
    assert editor.calls == [(str(deck), 1)]
    # The second card picked up both the fixed answer and the new tag.
    assert "#numbers" in out and "  two\n" in out and "too" not in out


def test_reworded_question_is_asked_as_new_card(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\ngato :: cat\n", encoding="utf-8")
    state = tmp_path / "s.json"
    editor = FakeEditor(lambda t: t.replace("hola ::", "¡hola! ::"))
    code, out, err = run_review(deck, state, ["e", "", "4", "", "3"], editor)
    assert code == 0, err
    assert "question reworded" in out
    assert "  ¡hola!\n" in out
    cards, _ = parse_deck(deck.read_text(encoding="utf-8"))
    data = json.loads(state.read_text(encoding="utf-8"))
    assert set(data["cards"]) == {c.id for c in cards}


def test_deleted_card_is_dropped(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\ngato :: cat\n", encoding="utf-8")
    editor = FakeEditor(lambda t: t.replace("hola :: hello\n", ""))
    code, out, err = run_review(deck, tmp_path / "s.json", ["e", "", "3"], editor)
    assert code == 0, err
    assert "no longer in the deck, dropped: hola" in out
    # "gato" now sits on line 1 but kept its id, so it is not mistaken for the edited card.
    assert out.count("  gato\n") == 1
    assert "Reviewed 1 card" in out


def test_editor_failure_shows_card_again_unchanged(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\n", encoding="utf-8")
    editor = FakeEditor(fail=True)
    code, out, err = run_review(deck, tmp_path / "s.json", ["e", "", "3"], editor)
    assert code == 0
    assert "exited with status 1; card unchanged" in err
    assert out.count("  hola\n") == 2
    assert "Edited" not in out


def test_broken_deck_after_edit_keeps_session_going(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text("hola :: hello\n", encoding="utf-8")

    def remove_deck(path, line):
        deck.unlink()

    code, out, err = run_review(deck, tmp_path / "s.json", ["e", "", "3"], remove_deck)
    assert code == 0
    assert "no such deck" in err
    assert "Reviewed 1 card" in out


def test_edit_hint_only_when_editing_available(tmp_path):
    cards, _ = parse_deck("q0 :: a0\n", deck="d")
    out = io.StringIO()
    run_session(cards, Store(tmp_path / "a.json"), reader("", "3"), out, lambda: NOW)
    assert "e to edit" not in out.getvalue()
    out = io.StringIO()
    run_session(cards, Store(tmp_path / "b.json"), reader("", "3"), out, lambda: NOW,
                edit=lambda c: None)
    assert "Enter to show the answer, s to skip, e to edit, q to quit" in out.getvalue()
    assert "(s skip, e edit, q quit)" in out.getvalue()


def test_e_without_callback_reasks(tmp_path):
    cards, _ = parse_deck("q0 :: a0\n", deck="d")
    out = io.StringIO()
    res = run_session(cards, Store(tmp_path / "s.json"), reader("e", "", "3"), out, lambda: NOW)
    assert "Editing is not available" in out.getvalue()
    assert res.answers == 1 and res.edited == 0


def test_undo_after_edit_asks_the_edited_version(tmp_path):
    cards, _ = parse_deck("q0 :: a0\nq1 :: a1\n", deck="d", path="d.md")
    fixed, _ = parse_deck("q0 :: A0\nq1 :: a1\n", deck="d", path="d.md")
    out = io.StringIO()
    res = run_session(
        cards, Store(tmp_path / "s.json"), reader("", "3", "e", "u", "", "3", "", "3"), out,
        lambda: NOW, edit=lambda c: EditResult(fixed[1], fixed),
    )
    assert out.getvalue().rsplit("undid", 1)[1].count("A0") == 1
    assert res.undone == 1 and res.edited == 1


def test_match_edited():
    before, _ = parse_deck("a :: 1\nb :: 2\n", path="x.md")
    ids = {c.id for c in before}
    reworded, _ = parse_deck("a2 :: 1\nb :: 2\n", path="x.md")
    assert match_edited(before[0], ids, reworded).front == "a2"
    shifted, _ = parse_deck("b :: 2\n", path="x.md")
    assert match_edited(before[0], ids, shifted) is None
    assert match_edited(before[1], ids, shifted).line == 1


def test_summary_mentions_edits():
    res = SessionResult(edited=2)
    assert summary(res) == "No cards reviewed. Edited 2."


@pytest.mark.parametrize(
    "editor, expected",
    [
        (["vim"], ["vim", "+7", "d.md"]),
        (["C:\\Tools\\nvim.exe"], ["C:\\Tools\\nvim.exe", "+7", "d.md"]),
        (["code"], ["code", "--wait", "--goto", "d.md:7"]),
        (["code", "-w"], ["code", "-w", "--goto", "d.md:7"]),
        (["subl", "-w"], ["subl", "-w", "d.md:7"]),
        (["subl"], ["subl", "--wait", "d.md:7"]),
        (["hx"], ["hx", "d.md:7"]),
        (["notepad"], ["notepad", "d.md"]),
    ],
)
def test_build_command(editor, expected):
    assert build_command(editor, "d.md", 7) == expected


def test_editor_command_line_prefers_visual():
    assert editor_command_line({"VISUAL": "nano", "EDITOR": "vim"}) == ["nano"]
    assert editor_command_line({"EDITOR": "code -w"}) == ["code", "-w"]
    assert editor_command_line({})[0] in ("vi", "notepad")


def test_open_in_editor_runs_command_and_reports_failures():
    calls = []
    open_in_editor("d.md", 3, env={"EDITOR": "vim"}, run=lambda cmd: calls.append(cmd) or 0)
    assert calls == [["vim", "+3", "d.md"]]
    with pytest.raises(EditorError, match="status 2"):
        open_in_editor("d.md", 3, env={"EDITOR": "vim"}, run=lambda cmd: 2)

    def missing(cmd):
        raise FileNotFoundError(2, "No such file or directory")

    with pytest.raises(EditorError, match="cannot start editor 'vim'"):
        open_in_editor("d.md", 3, env={"EDITOR": "vim"}, run=missing)
