# flashdeck

Spaced-repetition flashcards in the terminal. Your decks are ordinary
plain-text or Markdown files that you write and edit in any editor (and keep in
git); flashdeck picks the cards out of them, quizzes you, and schedules each
card with the SM-2 algorithm. Review history lives in a separate JSON file,
keyed by a hash of each card's question, so you can edit, reorder, split or
rename your decks without losing progress.

**Who it is for:** people who would rather keep their study notes as text files
than in a flashcard app's database.

**Built with:** Python 3.10+ and the standard library only (no runtime
dependencies). Tests use pytest.

## Install

```sh
git clone https://github.com/Chad9100/flashdeck.git
cd flashdeck
python -m pip install .
```

That puts a `flashdeck` command on your PATH. `python -m flashdeck` works too.

## Deck format

A deck is any `.md`, `.markdown` or `.txt` file (UTF-8, with or without a
BOM, LF or CRLF). The kinds of cards below can be mixed freely:

```markdown
# Spanish basics

Plain Markdown: headings and prose are ignored, cards are picked out.

#spanish

hola :: hello
adiós :: goodbye #greeting

Q: How do you say
"I am tired"?
A: Estoy cansado.
(cansada if you are female)
```

- **One-line cards:** `question :: answer`. The `::` needs a space on both
  sides, so `std::vector` is safe inside a question.
- **Two-way cards:** `question ::: answer` (three colons) makes two cards, one
  asked each way round: `hola ::: hello` quizzes `hola` and `hello`. Each
  direction has its own id (the hash of the side it asks) and its own
  history, and tags apply to both. The reverse card is labelled `reverse`
  during review. Turning an existing `hola :: hello` into `hola ::: hello`
  keeps the forward card's history and adds a new reverse card. If the answer
  is already a question elsewhere, the reverse card is reported as a
  duplicate and skipped. For multi-line two-way cards, start the answer of a
  `Q:` block with `A::` (two colons) instead of `A:`; the block then makes a
  card in each direction, with the same rules as `:::`. `flashdeck add
  --reverse` still writes one-line cards only.
- **Cloze deletions:** a line with `{{gap}}` makes one card per gap. The card
  hides that gap as `[...]` and shows the other gaps; the answer is the whole
  sentence. A deck line `{{Paris}} is the capital of {{France}}.` quizzes:

  ```text
  [2 left] geo (new)  #geo
    [...] is the capital of France.
    -- Enter to show the answer, s to skip, e to edit, q to quit --
    Paris is the capital of France.
  ```

  Tags work as on one-line cards. A line that is already a `::` card, or sits
  in a fence or `Q:`/`A:` block, is not read as a cloze. Careful: prose with
  `{{...}}` in it (such as a template) becomes cards too.
- **Q/A blocks:** a line starting with `Q:` begins the question, `A:` begins
  the answer; both may run over several lines. The card ends at a blank line
  or the next `Q:`. Blank lines inside a fenced code block (```` ``` ````) do
  not end it, so answers can contain code.
- **Tags:** a line made only of tags (`#spanish #verbs`) tags every card after
  it, until the next tag line. Tags at the end of a card's answer apply to that
  card only. `C#` and `#42` are not tags; write `\#` for a literal `#` that
  would otherwise be read as one.
- Everything else (headings, prose, lists, code outside cards) is ignored.
  Broken cards (`question ::` with no answer, a `Q:` without `A:`) are reported
  as warnings on stderr with file and line, and skipped.

Each card's id is a short SHA-1 of its question with whitespace collapsed.
Changing the answer, tags, position or file keeps the card's history; changing
the question makes it a new card. If two decks contain the same question, the
first one wins and the second is reported as a duplicate.

## Usage

Every command that reads decks accepts files and directories (searched
recursively for deck files, skipping hidden folders), and `-t/--tag TAG` to
keep only cards with that tag.

### What is due

```text
$ flashdeck due examples
deck       due  learn  review    new  cards
python       0      0       0      3      3
spanish      0      0       0      5      5
total        0      0       0      8      8
```

`learn` counts cards you got wrong recently and have not yet answered
correctly; `review` counts graduated cards whose interval has run out.

### Review

```sh
flashdeck review DECK... [--new N] [--limit N] [--fuzz PCT] [-t TAG] [--state PATH]
```

Due cards come first (most overdue first), then new cards in deck order. `--new`
is a daily allowance (default 20): new cards already started today count
against it. `--limit` caps the whole session (default 200).

For each card the question is shown; press Enter to see the answer, then grade
yourself: `1` again, `2` hard, `3` good, `4` easy (or the words, or their first
letters). Cards you get wrong come back later in the same session. `q`, Ctrl+C
or end of input stops; the state file is saved after every answer, so nothing
is lost.

Pressed the wrong key? Type `u` at either prompt to undo the last answer: the
card's previous schedule is restored, its entry is dropped from the answer log,
and the card is asked again (a card sent back by "again" is not asked twice).
Press `u` repeatedly to go further back, as far as the start of the session.
The summary line notes how many answers were undone.

Not the moment for a card? Type `s` at either prompt to skip it for the rest of
the session. Nothing is graded and nothing is written: the card keeps its
schedule (a due card stays due, a new card stays new) and shows up again next
session. Skips are not answers, so `u` after a skip goes back to the last card
you actually graded. The summary line notes how many cards were skipped.

Spotted a typo? Type `e` at either prompt to open the card's deck file in your
editor at the card's line (`$VISUAL`, then `$EDITOR`, else Notepad on Windows
and `vi` elsewhere). When the editor exits the decks are reloaded and the card
is shown again from its question, ungraded. Fixing the answer or tags keeps the
card's history; rewording the question makes it a new card (it is still asked
in this session), and a card you deleted is dropped. The rest of the session
picks up your changes too. The line is passed as `+LINE` to vi, Vim, Neovim,
nano, Emacs, micro, gedit and similar editors, and as `FILE:LINE` to VS Code,
Sublime Text, Helix and Zed; the GUI ones among these are also given `--wait`
so that flashdeck waits until you close the file. Other editors just open the
file. If the editor fails to
start or exits with an error, the card is shown again unchanged.

Answers can be piped in, which is how this real session was captured, on
2026-11-10 against a fresh state file, so your dates will differ (the typed
answers are not echoed when piped, so prompts and results share a line):

```text
$ printf '\n3\n\n1\n\n4\n\n3\n' | flashdeck review examples/spanish.md --new 3
3 card(s): 0 due, 3 new.

[3 left] spanish (new)  #spanish
  hola
  -- Enter to show the answer, s to skip, e to edit, q to quit -- 
  hello
  1 again   2 hard   3 good   4 easy   (s skip, e edit, q quit) >   -> next in 1 day (2026-11-11)

[2 left] spanish (new)  #spanish #greeting
  adiós
  -- Enter to show the answer, s to skip, e to edit, u to undo, q to quit -- 
  goodbye
  1 again   2 hard   3 good   4 easy   (s skip, e edit, u undo, q quit) >   -> again later in this session

[2 left] spanish (new)  #spanish
  gracias
  -- Enter to show the answer, s to skip, e to edit, u to undo, q to quit -- 
  thank you
  1 again   2 hard   3 good   4 easy   (s skip, e edit, u undo, q quit) >   -> next in 4 days (2026-11-14)

[1 left] spanish (learning)  #spanish #greeting
  adiós
  -- Enter to show the answer, s to skip, e to edit, u to undo, q to quit -- 
  goodbye
  1 again   2 hard   3 good   4 easy   (s skip, e edit, u undo, q quit) >   -> next in 1 day (2026-11-11)

Reviewed 3 cards (4 answers: again 1, hard 0, good 2, easy 1).
```

Piped input may start with a UTF-8 byte order mark (PowerShell adds one); it is
ignored, and piped input is always read as UTF-8.

### Statistics

```text
$ flashdeck stats examples
Cards:      8 total
  new 5, learning 0, review 3 (mature 0), relearning 0
Ease:       2.43 average
Lapses:     0
Reviews:    4 total, 4 today
Retention:  n/a last 30 days, n/a all time
Forecast (cards due):
  today        0
  tomorrow     2  ####################
  Thu 11-12    0
  Fri 11-13    0
  Sat 11-14    1  ##########
  Sun 11-15    0
  Mon 11-16    0
```

Retention is the share of reviews of graduated cards that were not answered
"again" (it is `n/a` until a card comes back for its first real review).
Mature cards have an interval of 21 days or more. `today` in the forecast
includes overdue cards. `--days N` changes the forecast length.

`--by-deck` and `--by-tag` print one row per deck or tag instead (a card with
several tags counts under each; untagged cards go in `(untagged)`). Captured
after answering one card; add `--json` for the same data as JSON:

```text
$ flashdeck stats examples --by-deck
deck     cards   new  learn  review  mature   ease  retention
python       3     3      0       0       0    n/a        n/a
spanish      5     4      0       1       0   2.50        n/a
$ flashdeck stats examples --by-tag
tag       cards   new  learn  review  mature   ease  retention
greeting      1     1      0       0       0    n/a        n/a
python        3     3      0       0       0    n/a        n/a
spanish       5     4      0       1       0   2.50        n/a
```

`--heatmap` shows the last 12 weeks of reviews (one column per week, Monday to
Sunday, `-` for a day without reviews, `.` to `#` from light to heavy) and your
study streak. The current streak stays alive if you have not studied yet today
but did yesterday. Captured on 2026-11-11 from a hand-made review history for
`examples/python.md` (`--json` gives the same numbers plus per-day counts):

```text
$ flashdeck stats examples/python.md --heatmap
Reviews, last 12 weeks (each column is a week, '.' to '#' is light to heavy):
  Mon - - - - - - - - - - - -
  Tue - - - - . - - - . . - .
  Wed - - - - : - - . - - - -
  Thu - - - - - . - - - - .  
  Fri - - - - - + - - - - .  
  Sat - - - - - . - - - - :  
  Sun - - - - - - - - - - .  
Studied 13 of the last 80 days, 17 reviews.
Current streak: 1 day. Longest streak: 4 days.
```

### JSON output

`due --json` and `stats --json` print the same numbers as one JSON document,
for scripts, status bars and dashboards. Captured on 2026-11-11 after one
answered card in a fresh state (your dates will differ):

```text
$ flashdeck due examples --json
{
  "decks": [
    {
      "deck": "python",
      "due": 0,
      "learning": 0,
      "review": 0,
      "new": 3,
      "cards": 3
    },
    {
      "deck": "spanish",
      "due": 0,
      "learning": 0,
      "review": 0,
      "new": 5,
      "cards": 5
    }
  ],
  "total": {
    "due": 0,
    "learning": 0,
    "review": 0,
    "new": 8,
    "cards": 8
  }
}
$ flashdeck stats examples/spanish.md --days 3 --json
{
  "cards": 5,
  "states": {
    "new": 4,
    "learning": 0,
    "review": 1,
    "relearning": 0
  },
  "mature": 0,
  "ease_average": 2.5,
  "lapses": 0,
  "reviews": {
    "total": 1,
    "today": 1
  },
  "retention": {
    "last_30_days": {
      "passed": 0,
      "total": 0,
      "rate": null
    },
    "all_time": {
      "passed": 0,
      "total": 0,
      "rate": null
    }
  },
  "forecast": [
    {
      "date": "2026-11-11",
      "due": 0
    },
    {
      "date": "2026-11-12",
      "due": 1
    },
    {
      "date": "2026-11-13",
      "due": 0
    }
  ]
}
```

`rate` is a fraction (0 to 1) and `null` while there is nothing to measure.

### Adding cards

```text
$ flashdeck add examples/spanish.md "buenos días" "good morning" -t greeting
Added to examples/spanish.md: buenos días :: good morning #greeting
```

The deck is created if it does not exist. Multi-line cards, or questions that
would be ambiguous as one line, are written as `Q:`/`A:` blocks; `#` that would
be read as a tag is escaped. A question the deck already has is refused (exit
status 1). The file's BOM and line endings are kept.

`-r/--reverse` writes a two-way card instead:

```text
$ flashdeck add examples/spanish.md "la casa" "the house" --reverse
Added to examples/spanish.md: la casa ::: the house
```

It is refused if either side spans several lines, if the deck already has the
answer as a question (exit status 1), or if the card could not be read back the
same way (for example a question containing ` ::: `).

`-c/--cloze` writes a cloze line instead; give the text with `{{gaps}}` and no
answer:

```text
$ flashdeck add geo.md "{{Paris}} is the capital of {{France}}." --cloze -t geo
Added to geo.md: {{Paris}} is the capital of {{France}}. #geo (2 card(s))
```

It needs at least one gap and a single line, cannot be combined with
`--reverse`, and is refused (exit status 1) if the deck already has a card for
any of the gaps.

### Importing from CSV

```text
$ cat words.csv
front,back,tags
perro,dog,animals
gato,cat,animals
hola,hi,
$ flashdeck import words.csv examples/spanish.md
Imported 2 card(s) into examples/spanish.md (1 already in the deck).
```

The delimiter is detected (`,` `;` tab `|`; `.tsv` files use tab), or set with
`--delimiter`. A first row whose cells look like `front`/`back`/`question`/
`answer`/`tags` is treated as a header; force it with `--header` or
`--no-header`. Pick columns with `--front`, `--back` and `--tags` by 1-based
number or header name; by default the first two columns are question and
answer. `-t TAG` tags every imported card. `-` reads the CSV from standard
input. Questions already in the deck and rows missing a side are skipped and
counted.

### Importing an Anki text export

`import` also reads Anki's "Notes in Plain Text" export. When the file starts
with `#key:value` header lines, `#separator` (tab, comma, semicolon, pipe,
space or a literal character) and `#tags column` are honoured, the first row
is treated as a card (Anki writes no column header), and with `#html:true`
the fields are converted to plain text (`<br>` and block ends become line
breaks, other tags are dropped, entities decoded). Other header lines such as
`#guid column` are ignored; if your question and answer are not in columns 1
and 2, pick them with `--front` and `--back`.

```text
$ cat anki.txt
#separator:tab
#html:true
#tags column:3
perro	dog	animals
Good <b>morning</b><br>friend	Buenos d&iacute;as	greeting
$ flashdeck import anki.txt deck.md
Imported 2 card(s) into deck.md.
$ cat deck.md
perro :: dog #animals

Q: Good morning
friend
A: Buenos días #greeting
```

### Orphaned state

Review history is keyed by the hash of a card's question, so deleting or
rewording a card leaves its state entry behind. List such entries with
`orphans`, and remove them (and their log history) with `--prune`:

```text
$ flashdeck orphans examples/spanish.md
99800b85d338  review, interval 1d, due 2026-11-11
1 orphaned card(s); run again with --prune to remove them.
$ flashdeck orphans examples/spanish.md --prune
99800b85d338  review, interval 1d, due 2026-11-11
Pruned 1 card(s) and 1 log entries.
```

Pass every deck you still use: a card from a deck you leave out counts as
orphaned. A deck that cannot be read is an error and nothing is pruned.

### Exporting

`flashdeck export DECK...` writes every card (two-way and cloze cards as one
row each) to standard output, or to a file with `-o FILE`. `--format csv` (the
default) has a `front,back,tags` header and can be read back by
`flashdeck import --header`; `--format anki` writes tab-separated text with
the `#separator`, `#html` and `#tags column` header lines that Anki's import
dialog understands. `-t TAG` exports only matching cards.

```text
$ flashdeck export examples/spanish.md
front,back,tags
hola,hello,spanish
adiós,goodbye,spanish greeting
gracias,thank you,spanish
por favor,please,spanish
"How do you say
""I am tired""?","Estoy cansado.
(cansada if you are female)",spanish
$ flashdeck export examples/spanish.md --format anki -t greeting
#separator:tab
#html:false
#tags column:3
adiós	goodbye	spanish greeting
```

### Rewording a question

To keep a card's history when you reword its question, move it before
pruning. `rename-question` takes the old question (or its id, as printed by
`orphans`) and the new one, and moves the card's state and log entries:

```text
$ flashdeck orphans deck.md
a67d3f273c88  review, interval 1d, due 2026-11-11
1 orphaned card(s); run again with --prune to remove them.
$ flashdeck rename-question "Capital of France?" "Which city is the capital of France?"
Moved a67d3f273c88 -> ae086c734d4e (1 log entries).
$ flashdeck orphans deck.md
No orphaned state entries.
```

It refuses to run if the old question has no history, or if the new one
already has some (nothing is overwritten).

### Compacting the answer log

Every answer adds a line to the log in the state file. `compact` folds
entries older than a year (change it with `--older-than DAYS`) into one
summary per card, day and previous state. Statistics, retention and the
heatmap count the summaries correctly. Here is a log with 16 old answers
(from a made-up demo state), before and after, with the stats unchanged:

```text
$ flashdeck stats deck.md
  new 0, learning 0, review 2 (mature 2), relearning 0
Ease:       2.50 average
Lapses:     2
Reviews:    17 total, 1 today
Retention:  100.0% (1/1) last 30 days, 76.5% (13/17) all time
$ flashdeck compact
Compacted 16 log entries before 2025-11-11 into 8 daily summaries.
$ flashdeck compact
Nothing to compact: no log entries before 2025-11-11 would shrink.
$ flashdeck stats deck.md
  new 0, learning 0, review 2 (mature 2), relearning 0
Ease:       2.50 average
Lapses:     2
Reviews:    17 total, 1 today
Retention:  100.0% (1/1) last 30 days, 76.5% (13/17) all time
```

Individual grades and times of compacted answers are gone for good, so
copy `state.json` first if you want them.

## Scheduling (SM-2)

Each card has an ease factor (starts at 2.5, never below 1.3), an interval in
days, a streak of correct answers and a lapse count. The buttons map to SM-2
quality grades: again = 2, hard = 3, good = 4, easy = 5, and the ease factor is
updated with the SM-2 formula `EF += 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)`
(good keeps it, hard -0.14, again -0.32, easy +0.10).

| Situation | Next interval |
| --- | --- |
| New or relearning card, hard/good | 1 day |
| New or relearning card, easy | 4 days |
| Second correct review | hard 4, good 6, easy 8 days |
| Later reviews | hard x1.2, good x EF, easy x EF x 1.3 (always at least +1 day) |
| Again | back into the session today; lapse counted for graduated cards |

A card answered late gets credit for the extra days it survived: for the
multiplicative reviews the interval is computed from `interval + credit x days
overdue`, with credit 0.25 for hard, 0.5 for good and 1.0 for easy. Early or
on-time answers are unchanged.

Output of `schedule()` for a review card with a 10-day interval, 3 reps and
ease 2.5, answered 5 days early, on time and 10 days late:

```
early (-5 days): {'hard': 12, 'good': 25, 'easy': 32}
on time:         {'hard': 12, 'good': 25, 'easy': 32}
10 days late:    {'hard': 15, 'good': 38, 'easy': 65}
```

### Interval fuzz

Cards added together tend to come back together. `flashdeck review --fuzz PCT`
(0 to 50, default 0 = off) spreads review intervals of 8 days or more by up to
+/-PCT percent. The offset is derived from a hash of the card id and its
repetition count rather than a random number, so the same answer always gives
the same interval (undo and redo agree) while different cards land on
different days. The result is never shorter than the previous interval plus one
day, and learning steps and short intervals are left exact. Eight different
cards, each answered "good" from a 20-day interval:

```
fuzz 0%: [50, 50, 50, 50, 50, 50, 50, 50]
fuzz 5%: [48, 49, 50, 49, 50, 52, 52, 52]
```

The hard and easy multipliers are small tweaks borrowed from Anki; plain SM-2
has no separate hard/easy intervals. Grades given while a card is being
relearned do not change its ease again.

## Where state is kept

`$FLASHDECK_HOME/state.json` if that variable is set; otherwise
`%APPDATA%\flashdeck\state.json` on Windows and
`$XDG_DATA_HOME/flashdeck/state.json` (or `~/.local/share/flashdeck/state.json`)
elsewhere. `--state PATH` picks a different file, for example one kept next to
a deck. The file holds each card's schedule and a log of every answer; it is
written atomically, and a corrupt file is reported rather than overwritten.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # .venv\Scripts\pip on Windows
pytest -q
```

The clock and the input stream are injectable (`main(argv, stdin=..., stdout=...,
clock=...)`), so the tests run whole review sessions without a terminal or
real time passing. CI runs on Ubuntu and Windows with Python 3.10, 3.12 and
3.13.

## License

MIT. See [LICENSE](LICENSE).
