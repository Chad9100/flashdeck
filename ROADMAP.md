# Roadmap

Estimates are rough working hours for one person.

## v0.1 (done)

- [x] Deck parser: `question :: answer` lines and multi-line `Q:`/`A:` blocks,
      section and per-card `#tags`, fenced code, BOM and CRLF, warnings with line numbers
- [x] Stable card ids (hash of the question) and a separate JSON state file
- [x] SM-2 scheduling with ease factor, intervals, lapses and relearning
- [x] `flashdeck review` with `--new` daily allowance, `--limit`, `--tag`
- [x] `flashdeck due`, `stats` (states, retention, 7-day forecast), `add`, `import` (CSV/TSV)
- [x] Injectable clock and input; pytest suite; CI on Ubuntu and Windows

## v0.2: undo and editing during review (about 3 h)

- [x] `u` undoes the last answer in a session (restore the previous card state, drop the log entry)
- [x] `s` skips a card for this session without grading it
- [x] `e` opens the card's deck file in `$EDITOR` at the card's line, then reloads the deck

## v0.3: reverse and cloze cards (about 4 h)

- [x] `front ::: back` creates a card in both directions, each with its own id and history
- [x] `flashdeck add --reverse` writes two-way cards, with round-trip tests
- [x] Cloze deletions: `The capital of France is {{Paris}}.` yields one card per gap
- [x] `flashdeck add --cloze` with round-trip tests
- [x] Two-way `Q:`/`A::` blocks (multi-line cards in both directions)

## v0.4: state housekeeping (about 3 h)

- [x] `flashdeck orphans`: list (and with `--prune`, remove) state entries whose question no longer
      appears in any given deck
- [x] `flashdeck rename-question`: carry a card's history over when its question is reworded
- [x] Compact the answer log (keep per-day summaries for entries older than a year)

## v0.5: better scheduling options (about 4 h)

- [ ] Configurable learning steps in minutes (e.g. `1m 10m`) instead of "later in this session"
- [x] Interval fuzz (`review --fuzz PCT`) so cards added together do not stay bunched together
- [x] Credit for late reviews: a card answered correctly well past its due date gets a longer interval
- [ ] Optional FSRS scheduler behind `--scheduler fsrs`, with SM-2 remaining the default

## v0.6: richer statistics (about 3 h)

- [x] `stats --by-deck` and `--by-tag` breakdowns
- [x] Review heatmap for the last 12 weeks and current study streak
- [x] `--json` output for `due` and `stats`

## v0.7: import and export (about 3 h)

- [x] Import Anki's plain-text export (tab-separated, with `#separator`/`#html` headers)
- [x] `flashdeck export DECK --format csv|anki` for moving cards elsewhere
- [x] Optional SQLite state backend for very large collections (`--state x.sqlite`)

## Release (about 1 h)

- [ ] Publish to PyPI with a trusted-publishing workflow
- [ ] Animated terminal demo in the README
