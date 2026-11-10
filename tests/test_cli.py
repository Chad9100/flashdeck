import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from flashdeck.cli import main

NOW = datetime(2026, 11, 10, 9, 0, 0)

DECK = """\
# Spanish basics

#spanish

hola :: hello
adiós :: goodbye #greeting
gracias :: thank you

Q: How do you say
"I am tired"?
A: Estoy cansado.
"""


def run(args, stdin="", now=NOW):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(stdin), stdout=out, stderr=err, clock=lambda: now)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def deck(tmp_path):
    path = tmp_path / "spanish.md"
    path.write_text(DECK, encoding="utf-8")
    return path


@pytest.fixture
def state(tmp_path):
    return tmp_path / "state.json"


def test_due_on_fresh_deck(deck, state):
    code, out, err = run(["due", str(deck), "--state", str(state)])
    assert code == 0 and err == ""
    assert out.splitlines()[1].split() == ["spanish", "0", "0", "0", "4", "4"]


def test_review_session_end_to_end(deck, state):
    code, out, _ = run(["review", str(deck), "--state", str(state), "--new", "2"], stdin="\n3\n\n1\n\n4\n")
    assert code == 0
    assert "2 card(s): 0 due, 2 new." in out
    assert "Reviewed 2 cards (3 answers: again 1, hard 0, good 1, easy 1)." in out
    data = json.loads(state.read_text(encoding="utf-8"))
    assert len(data["cards"]) == 2 and len(data["log"]) == 3

    # Same day: the daily new-card allowance is used up.
    code, out, _ = run(["review", str(deck), "--state", str(state), "--new", "2"])
    assert out.startswith("Nothing to review right now. Next card is due 2026-11-11.")

    # Next day: both cards are due again, plus two new ones.
    code, out, _ = run(["due", str(deck), "--state", str(state)], now=NOW + timedelta(days=1))
    assert out.splitlines()[1].split() == ["spanish", "1", "0", "1", "2", "4"]


def test_review_piped_bom_on_first_answer(deck, state):
    code, out, _ = run(["review", str(deck), "--state", str(state), "--new", "1"], stdin="﻿\n3\n")
    assert "Reviewed 1 card " in out


def test_review_limit_and_tag_filter(deck, state):
    code, out, _ = run(
        ["review", str(deck), "--state", str(state), "--tag", "greeting", "--limit", "5"], stdin="\n4\n"
    )
    assert "1 card(s): 0 due, 1 new." in out
    assert "adiós" in out and "hola" not in out


def test_stats_command(deck, state):
    run(["review", str(deck), "--state", str(state)], stdin="\n3\n\n3\n\n3\n\n3\n")
    later = NOW + timedelta(days=1)
    run(["review", str(deck), "--state", str(state)], stdin="\n3\n\n1\n\n3\n\n3\n\n3\n", now=later)
    code, out, _ = run(["stats", str(deck), "--state", str(state)], now=later)
    assert code == 0
    assert "Cards:      4 total" in out
    assert "Retention:  75.0% (3/4) last 30 days" in out
    assert "Lapses:     1" in out
    assert out.count("\n") == 14


def test_add_and_duplicate(deck, state):
    code, out, _ = run(["add", str(deck), "buenos días", "good morning", "-t", "greeting"])
    assert code == 0 and out == f"Added to {deck}: buenos días :: good morning #greeting\n"
    assert deck.read_text(encoding="utf-8").endswith('A: Estoy cansado.\n\nbuenos días :: good morning #greeting\n')
    code, _, err = run(["add", str(deck), "buenos  días", "other"])
    assert code == 1 and "already has that question" in err
    code, _, err = run(["add", str(deck), "x", "  "])
    assert code == 2


def test_import_csv_file_and_stdin(tmp_path, deck):
    csv_path = tmp_path / "words.csv"
    csv_path.write_bytes("﻿front,back,tags\nperro,dog,animals\nhola,hi,\n".encode("utf-8"))
    code, out, _ = run(["import", str(csv_path), str(deck)])
    assert code == 0
    assert out == f"Imported 1 card(s) into {deck} (1 already in the deck).\n"
    code, out, _ = run(["import", "-", str(deck), "--no-header", "-t", "es"], stdin="﻿gato\tcat\n")
    assert out.startswith("Imported 1 card(s)")
    code, out, _ = run(["due", str(deck)])
    assert out.splitlines()[1].split()[-1] == "6"


def test_import_tsv_by_extension_and_bad_column(tmp_path):
    tsv = tmp_path / "w.tsv"
    tsv.write_text("a,b\tc\n", encoding="utf-8")
    deck = tmp_path / "out.md"
    assert run(["import", str(tsv), str(deck)])[0] == 0
    assert deck.read_text(encoding="utf-8") == "a,b :: c\n"
    code, _, err = run(["import", str(tsv), str(deck), "--front", "nope", "--header"])
    assert code == 2 and "no column named" in err


def test_errors_exit_2(tmp_path, deck):
    code, _, err = run(["due", str(tmp_path / "missing.md")])
    assert code == 2 and "no such deck" in err
    bad_state = tmp_path / "bad.json"
    bad_state.write_text("[1, 2", encoding="utf-8")
    code, _, err = run(["due", str(deck), "--state", str(bad_state)])
    assert code == 2 and "cannot read state file" in err
    code, _, err = run(["import", str(tmp_path / "none.csv"), str(deck)])
    assert code == 2


def test_default_state_lives_in_flashdeck_home(deck, isolated_home):
    run(["review", str(deck), "--new", "1"], stdin="\n3\n")
    assert (isolated_home / "state.json").exists()


def test_parse_deck_warnings_go_to_stderr(tmp_path):
    p = tmp_path / "w.md"
    p.write_text("ok :: fine\nbroken ::\n", encoding="utf-8")
    code, out, err = run(["due", str(p)])
    assert code == 0 and "w.md:2: card has no answer" in err


def test_bad_number_option_is_usage_error(deck):
    with pytest.raises(SystemExit) as exc:
        run(["review", str(deck), "--new", "-1"])
    assert exc.value.code == 2


def test_real_process_with_bom_piped_stdin(deck, tmp_path):
    """Piped stdin starting with a UTF-8 BOM (as PowerShell sends it) works."""
    env = dict(os.environ, FLASHDECK_HOME=str(tmp_path / "home"), PYTHONIOENCODING="")
    proc = subprocess.run(
        [sys.executable, "-m", "flashdeck", "review", str(deck), "--new", "1"],
        input="﻿\n3\n".encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout.decode("utf-8")
    assert "Reviewed 1 card " in text
    assert "hola" in text
