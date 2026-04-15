## Browser Ontology V3

Browser Ontology V3 extends Browser Ontology V2 from bounded judgment into bounded research handoffs.

V1 covered:
- browser control
- search
- click
- extraction

V2 added:
- ranking extracted cards against a goal
- comparing bounded candidates against a goal

V3 adds:
- carrying the winning subject forward in browser state
- searching a second site about that active subject

This is the first point where the browser ontology supports a real multi-step research chain.

## V3 Goal

V3 is meant for prompts like:
- `find the best repo for c++ llm inference on cpu then find a youtube video about it`
- `find a youtube video about this repo`
- `compare the first and second repo for cpu inference then find a youtube video about the winner`

The point is not arbitrary agentic web wandering.

The point is:
- judge a bounded candidate set
- promote the winner into browser state as the active subject
- hand that subject off into a second bounded search

## V3 State

V3 keeps all V2 fields and adds:
- `subject_title`
- `subject_url`
- `subject_summary`

These fields are the active browser subject.

That matters because V3 does not allow the runtime to make up what `it` means.
`it` has to resolve to a bounded subject already present in browser state.

## New Primitive

### `browser_search_subject`

Meaning:
- search another site about the active subject in browser state

Inputs:
- active subject fields from browser state
- target search engine from the action or action note

Outputs:
- `subject_title`
- `subject_url`
- `search_engine`
- `search_query`
- `search_url`

## Grounding Rules

V3 keeps the V1 and V2 rules and adds:

1. Subject handoff must be explicit.
The next-site search can only use:
- the V2 winner
- a clicked/extracted card promoted into subject state
- or the current repo page resolved into a subject

2. Cross-site research is still bounded.
`browser_search_subject` does not inspect arbitrary hidden browser history.
It lowers one explicit subject into one explicit target search engine.

3. V3 is not free-roaming autonomy.
It is a bounded research chain over:
- current browser evidence
- bounded judgment
- bounded search handoff

## Adjudication

A V3 case is only semantically successful if:
- the right chain primitive sequence was chosen
- the right subject was carried forward
- the target search engine was correct
- the final search query was grounded to the chosen subject

## V3 Benchmark Shape

A Browser Ontology V3 benchmark case includes:
- seeded browser state
- seeded result cards or a seeded repo page
- accepted action chain
- expected carried subject
- expected target search engine/query

This keeps V3 measurable without drifting into vague browser-agent claims.

## Out Of Scope For V3

V3 still does not claim:
- arbitrary multi-page research over unknown sites
- login flows
- open-world DOM planning
- arbitrary cloud-agent parity
- long autonomous browser sessions without bounded state

V3 is still bounded research, not universal browsing.

## What Counts As A Real V3 Win

A real Browser Ontology V3 win looks like:
- the same seeded search state
- the same seeded cards
- the same base model
- raw planning fails to carry the right subject into the next search
- Memla chooses the correct judgment step, persists the winning subject, and searches the next site about it

That is the first point where browser C2A stops looking like isolated browser moves and starts looking like bounded browser research.
