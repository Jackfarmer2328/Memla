## Browser Ontology V4

Browser Ontology V4 extends Browser Ontology V3 from bounded research handoff into bounded research completion.

V3 covered:
- choosing the best bounded subject
- carrying that subject forward in browser state
- searching a second site about that subject

V4 adds:
- opening the best follow-on result from that second-site search

This is the first point where the browser ontology can complete a full bounded research chain:
- judge
- hand off
- search
- open the follow-on result

## V4 Goal

V4 is meant for prompts like:
- `find the best repo for c++ llm inference on cpu then find a youtube video about it and open the first one`
- `find a youtube video about this repo and open the first result`
- `compare the first and second repo for cpu inference then open the first youtube video about the winner`

The point is still not open-ended browsing.

The point is:
- keep the chain explicit
- keep each state transition bounded
- make the final opened page backtestable

## V4 Composition

V4 does not need a magic new universal primitive.

It composes:
- `browser_rank_cards` or `browser_compare_cards`
- `browser_search_subject`
- `open_search_result`

That matters because V4 is evidence that the ontology is starting to compose usefully rather than requiring a new primitive for every larger ask.

## V4 State

V4 keeps the V3 browser state:
- `current_url`
- `page_kind`
- `search_engine`
- `search_query`
- `result_urls`
- `result_cards`
- `subject_title`
- `subject_url`
- `subject_summary`

After the final `open_search_result`, the browser state should now reflect:
- the opened follow-on page
- the carried search context
- the selected result as the new active subject

## Grounding Rules

V4 keeps all V1-V3 rules and adds:

1. The final open step must still be grounded to extracted result cards.
It does not click arbitrary invisible DOM targets.

2. The second-site search result set must be seeded in the benchmark.
That keeps V4 deterministic and backtestable.

3. V4 is still a bounded chain.
It is not a claim of unrestricted browsing.

## Adjudication

A V4 case is only semantically successful if:
- the correct chain was chosen
- the correct subject was carried forward
- the correct second-site search happened
- the correct follow-on result was opened
- the final page state matches the expected page kind / URL / search context

## V4 Benchmark Shape

A Browser Ontology V4 benchmark case includes:
- seeded initial browser state
- seeded first-site cards
- seeded second-site cards for the subject search
- accepted action chain
- expected final page and carried search context

## Out Of Scope For V4

V4 still does not claim:
- arbitrary multi-hop web research
- page understanding across unknown application UIs
- login flows
- long-horizon autonomous browsing
- cloud-agent parity across the open web

V4 is bounded research completion, not universal browser autonomy.

## What Counts As A Real V4 Win

A real Browser Ontology V4 win looks like:
- the same seeded browser state
- the same seeded cross-site result sets
- the same base model
- raw planning fails to produce the correct chain
- Memla chooses the correct chain and opens the correct follow-on result

That is the point where browser C2A starts looking like a bounded research workflow rather than just isolated browser operations.
