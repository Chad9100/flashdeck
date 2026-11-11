import io
import json
from datetime import datetime

from flashdeck.cli import main

NOW = datetime(2026, 11, 10, 9, 0, 0)


def run(args, inp=""):
    out, err = io.StringIO(), io.StringIO()
    code = main(args, stdin=io.StringIO(inp), stdout=out, stderr=err, clock=lambda: NOW)
    return code, out.getvalue(), err.getvalue()


def make(tmp_path):
    a = tmp_path / "fr.md"
    a.write_text("#verbs\nun :: one\ndeux :: two #hard\n\n#nouns\ntrois :: three\n", encoding="utf-8")
    b = tmp_path / "de.md"
    b.write_text("eins :: one\n", encoding="utf-8")
    return a, b, tmp_path / "state.json"


def test_by_deck_table(tmp_path):
    a, b, state = make(tmp_path)
    code, out, _ = run(["stats", str(a), str(b), "--state", str(state), "--by-deck"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["deck", "cards", "new", "learn", "review", "mature", "ease", "retention"]
    assert lines[1].split() == ["fr", "3", "3", "0", "0", "0", "n/a", "n/a"]
    assert lines[2].split()[:3] == ["de", "1", "1"]


def test_by_tag_counts_card_under_each_tag_and_untagged_last(tmp_path):
    a, b, state = make(tmp_path)
    code, out, _ = run(["stats", str(a), str(b), "--state", str(state), "--by-tag", "--json"])
    assert code == 0
    data = json.loads(out)
    assert data["by"] == "tag"
    counts = {g["name"]: g["cards"] for g in data["groups"]}
    assert counts == {"hard": 1, "nouns": 1, "verbs": 2, "(untagged)": 1}
    assert data["groups"][-1]["name"] == "(untagged)"
    assert "forecast" not in data["groups"][0]


def test_by_deck_reflects_reviews(tmp_path):
    a, _, state = make(tmp_path)
    run(["review", str(a), "--state", str(state), "--new", "1"], inp="\n3\n")
    code, out, _ = run(["stats", str(a), "--state", str(state), "--by-deck", "--json"])
    group = json.loads(out)["groups"][0]
    assert group["name"] == "fr"
    assert group["reviews"]["total"] == 1
    assert group["states"]["new"] == 2


def test_by_deck_and_by_tag_are_exclusive(tmp_path):
    a, _, state = make(tmp_path)
    try:
        run(["stats", str(a), "--state", str(state), "--by-deck", "--by-tag"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("expected argparse error")
