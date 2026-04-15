# Browser Ontology V2

Browser Ontology V2 extends Browser Ontology V1 from control into judgment.

V1 covered:
- search
- click
- tab control
- page extraction
- lightweight browser actions

V2 adds:
- ranking extracted result cards against a goal
- comparing selected result cards against a goal

This means the browser runtime can now do more than navigate. It can judge which extracted candidate is the stronger fit for the active constraint.

## V2 Goal

V2 is meant for prompts like:
- `which repo best matches a beginner local llm workflow on a laptop`
- `rank these repos for local c++ inference on weak hardware`
- `compare the first and second repo for cpu inference`

The point is not open-ended analysis over the entire web.

The point is:
- extract bounded browser evidence
- compare that evidence to an explicit goal
- return a structured best-match judgment

## V2 State

V2 keeps the V1 browser state:
- `current_url`
- `page_kind`
- `search_engine`
- `search_query`
- `result_urls`
- `result_cards`

V2 judgment is grounded to `result_cards`.

That matters:
- `browser_rank_cards` does not inspect arbitrary DOM state
- `browser_compare_cards` does not improvise from browser history
- both operate over extracted cards that Memla already understands

## New Primitives

### `browser_rank_cards`

Meaning:
- rank the current cached result cards against a goal

Inputs:
- cached `result_cards`
- goal text from the prompt or action note

Outputs:
- `goal`
- `best_title`
- `best_url`
- `best_score`
- `ranking`

### `browser_compare_cards`

Meaning:
- compare selected cached cards against a goal and return the stronger match

Inputs:
- selected card indexes
- cached `result_cards`
- goal text from the prompt or action note

Outputs:
- `goal`
- `winner_title`
- `winner_url`
- `winner_score`
- `winner_matching_terms`
- `runner_up_title`
- `runner_up_score`
- `comparison`

## Grounding Rules

V2 keeps the V1 grounding rules and adds two more:

1. Ranking and comparison are card-grounded.
They only operate on extracted `result_cards`.

2. The goal is explicit.
The runtime compares extracted card text against a normalized goal, not against hidden world knowledge.

3. V2 judgment is still bounded.
If there are no cards, ranking/comparison should fail cleanly instead of hallucinating a winner.

## Adjudication

V2 success is not just “an action ran.”

For V2, a judgment step is only semantically successful if:
- the correct primitive was chosen
- the card-grounded comparison executed
- the expected winner or best match was returned

This is the key difference from V1 control.

V1 asks:
- did Memla perform the right browser move?

V2 asks:
- did Memla perform the right browser judgment over bounded evidence?

## V2 Benchmark Shape

A Browser Ontology V2 benchmark case includes:
- seeded browser search state
- seeded result cards
- a goal prompt
- accepted action set
- expected best title or comparison winner

This makes V2 backtestable without drifting back into vague browser chat.

## Out Of Scope For V2

V2 still does not claim:
- arbitrary web research
- multi-page reasoning over unknown sites
- DOM-agent parity
- universal browser analysis
- hidden model reasoning over the whole internet

V2 is still bounded.

It is just bounded judgment rather than bounded control.

## What Counts As A Real V2 Win

A real Browser Ontology V2 win looks like:
- the same browser state
- the same extracted cards
- the same goal
- the same base model
- raw planning fails or chooses the wrong primitive
- Memla chooses the correct ranking/comparison primitive and returns the correct winner

That is the first point where browser C2A starts looking like agent judgment rather than just browser control.
