## Browser Ontology V5

Browser Ontology V5 extends Browser Ontology V4 from bounded research completion into bounded research explanation.

V4 covered:
- judge the best bounded subject
- hand that subject to a second-site search
- open the best follow-on result

V5 adds:
- reading the opened follow-on page and turning it into a structured answer

This is the first point where the browser ontology can complete a full bounded research loop:
- judge
- hand off
- search
- open
- read

## V5 Goal

V5 is meant for prompts like:
- `find the best repo for c++ llm inference on cpu then find a youtube video about it, open the first one, and tell me what it is`
- `find a youtube video about this repo, open the first result, and summarize it`
- `compare the first and second repo for cpu inference then open the first youtube video about the winner and explain it`

The point is not unrestricted browser chat.

The point is:
- complete a bounded research chain
- end on a readable page
- return a structured explanation grounded in a seeded snapshot

## V5 Composition

V5 is still compositional.

It uses:
- `browser_rank_cards` or `browser_compare_cards`
- `browser_search_subject`
- `open_search_result`
- `browser_read_page`

That matters because the ontology is still growing by reusable transmutations, not by one-off scripted workflows.

## V5 State

V5 keeps the V4 browser state:
- `current_url`
- `page_kind`
- `search_engine`
- `search_query`
- `result_urls`
- `result_cards`
- `subject_title`
- `subject_url`
- `subject_summary`

After the final `browser_read_page`, the state should still reflect the opened follow-on page and the carried subject, while the action details return the structured explanation.

## Grounding Rules

V5 keeps all V1-V4 rules and adds:

1. The final explanation must be page-grounded.
It comes from the seeded final-page snapshot, not from freeform world knowledge.

2. The final answer step is still bounded.
`browser_read_page` reads the opened page only. It does not resume browsing or infer over hidden context.

3. V5 remains backtestable.
The final page snapshot is seeded in the case pack so semantic success depends on the right chain and the right final read, not on live web variance.

## Adjudication

A V5 case is only semantically successful if:
- the right chain was chosen
- the right subject was carried forward
- the right second-site search happened
- the right follow-on result was opened
- the final read returned the expected structured fields from the opened page

## V5 Benchmark Shape

A Browser Ontology V5 benchmark case includes:
- seeded first-site browser state
- seeded first-site cards
- seeded second-site cards for the subject search
- a seeded final-page snapshot for the opened result
- accepted action chain
- expected final page state and structured detail fields

## Out Of Scope For V5

V5 still does not claim:
- arbitrary multi-hop browsing across unknown sites
- login flows
- full cloud browser-agent parity
- long-horizon planning over the open web
- unrestricted summarization over unseen DOM state

V5 is bounded research explanation, not universal browser autonomy.

## What Counts As A Real V5 Win

A real Browser Ontology V5 win looks like:
- the same seeded browser state
- the same seeded cross-site result sets
- the same seeded final-page snapshot
- the same base model
- raw planning fails to produce the full bounded chain
- Memla chooses the full chain and returns the structured final explanation

That is the point where browser C2A starts looking like a bounded browser research assistant rather than just a browser control/runtime layer.
