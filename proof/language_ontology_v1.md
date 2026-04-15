## Language Ontology V1

Language Ontology V1 sits above Browser Ontology V8.

Browser V8 already proved that Memla can:
- control a bounded browser world
- rank and compare search results
- carry a subject across GitHub, YouTube, and Reddit
- recover from weak branches
- synthesize bounded evidence

Language V1 adds:
- noisy-phrase normalization
- clause-level prompt splitting
- implied site inference from words like `video`, `repo`, and `post`
- light typo and slang handling
- paraphrase benchmarking against the same canonical browser transmutations

## Language V1 Goal

Language V1 is for prompts like:
- `yo memla go to youtube and look up nine vicious`
- `click he first vid you see`
- `grab a youtube vid on this repo and open the first one`
- `find the best repo for c plus plus cpu inference, grab a youtube vid on it, then tell me which source explains it best`

The point is:
- keep the browser ontology fixed
- widen the language surface above it
- compile noisy prompts into the same bounded transmutations
- benchmark paraphrase robustness instead of claiming free-form intelligence by vibe

## Language V1 Composition

Language V1 does not add new browser actions.

It translates noisy prompts into existing browser transmutations like:
- `open_url`
- `browser_new_tab`
- `open_search_result`
- `browser_rank_cards`
- `browser_search_subject`
- `browser_retry_subject_result`
- `browser_synthesize_evidence`

## Grounding Rules

1. Language V1 only widens phrasing, not ontology scope.
If a task is outside Browser V8, Language V1 cannot invent a new browser capability.

2. Implied site inference stays bounded.
- `video` / `vid` implies YouTube
- `repo` / `repository` implies GitHub
- `post` / `thread` implies Reddit

3. Paraphrases must lower to the same canonical plan.
The benchmark is not asking whether the wording sounds smart. It asks whether different phrasings produce the same accepted transmutation chain.

## Adjudication

A Language V1 case is only successful if:
- the noisy prompt lowers into an accepted browser action set
- the existing browser backtester still passes
- the same semantic outcome is reached under the fixed browser ontology

## What Counts As A Real Language V1 Win

A real Language Ontology V1 win looks like:
- the prompt wording changes
- the browser ontology does not
- Memla still produces the same bounded chain
- and the browser backtester still solves the task

That is the difference between:
- a one-phrase shortcut
and
- a translated language layer over C2A.
