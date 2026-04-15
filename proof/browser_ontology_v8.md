## Browser Ontology V8

Browser Ontology V8 extends Browser Ontology V7 from bounded recovery into bounded cross-source synthesis.

V7 covered:
- carrying a research subject across GitHub -> YouTube -> Reddit
- recovering from a weak first follow-on result

V8 adds:
- accumulating evidence from the sources Memla reads
- choosing which source best answers the active goal
- returning a grounded synthesis instead of just the last page read

## V8 Goal

V8 is meant for prompts like:
- `find the best repo, find a youtube video about it, find a reddit post about it, then tell me which source best explains weak-hardware setup`
- `find a repo, compare follow-on sources, then tell me which one best explains what the project is for`
- `carry the same subject across multiple sites, then choose the best current source and answer from it`

The point is:
- keep the browser chain bounded
- preserve what each source contributed
- choose the strongest source explicitly
- answer from evidence rather than from raw model improvisation

## V8 Composition

V8 adds one bounded transmutation:
- `browser_synthesize_evidence`

It composes with:
- `browser_rank_cards` / `browser_compare_cards`
- `browser_search_subject`
- `open_search_result`
- `browser_read_page`
- `browser_retry_subject_result`

Typical V8 chain:
1. choose the best repo subject
2. search YouTube about it
3. open and read the first result
4. recover to a better result if needed
5. search Reddit about the same carried subject
6. open and read the post
7. synthesize the accumulated evidence and choose the best source

## V8 State

V8 keeps all V7 state and adds:
- `evidence_items`

Each evidence item is bounded and structured:
- `source_kind`
- `title`
- `url`
- `summary`
- `meta`

Evidence is appended when:
- Memla reads a page
- Memla chooses a winning repo/card
- Memla carries a repo page into a subject search

## Grounding Rules

V8 keeps all earlier grounding rules and adds:

1. Synthesis only sees bounded evidence.
`browser_synthesize_evidence` cannot invent new browsing. It ranks the evidence already collected inside the ontology.

2. Source choice is explicit.
The output must name the best source title and source kind, not just emit a vague summary.

3. The research subject still anchors the answer.
Synthesis is about the carried subject, not a generic web topic drift.

## Adjudication

A V8 case is only semantically successful if:
- the subject chain still works
- the recovery step still chooses the stronger follow-on result when required
- enough evidence sources were accumulated
- the expected best source title matches
- the expected best source kind matches
- the final synthesis contains the expected key idea

## V8 Benchmark Shape

A Browser Ontology V8 case includes:
- everything V7 needs
- explicit expected best source fields
- an expected evidence count floor
- expected synthesis substrings

## Out Of Scope For V8

V8 still does not claim:
- unrestricted open-web research
- arbitrary browsing with no ontology
- full agent memory beyond the bounded evidence list
- universal source trust modeling

V8 is bounded cross-source synthesis, not open-world autonomy.

## What Counts As A Real V8 Win

A real Browser Ontology V8 win looks like:
- Memla carries the same subject through multiple sites
- it recovers from a weak first branch
- it accumulates structured evidence from what it actually read
- it chooses the strongest source for the active goal
- it answers from that evidence without needing the model in the hot path
