## Language Ontology V2

Language Ontology V2 extends Language Ontology V1 from heuristic paraphrase handling into bounded language compilation with an LLM fallback.

V1 covered:
- noisy-phrase normalization
- clause splitting
- implied site inference
- paraphrase benchmarking where heuristics still solved the language

V2 adds:
- a narrow language-model compiler fallback
- validation of compiled plans before execution
- explicit separation between language compilation and browser execution

## V2 Goal

V2 is for prompts like:
- `yo spin up a fresh tab and toss nine vicious on youtube then smack the first vid`
- `peep a youtube vid on this repo and if it's bunk grab a better one`
- `stack rank the first two repos for cpu inference then snag a reddit thread on the winner`

The point is:
- heuristics handle covered language instantly
- if language falls outside the heuristic layer, the model only compiles it into canonical actions
- Memla still validates the compiled plan against the current ontology before execution

## V2 Composition

Language V2 keeps the Browser V8 ontology fixed.

It adds one extra stage above execution:
1. heuristic language compiler
2. language-model compiler fallback
3. Memla validation
4. browser execution and adjudication

## Grounding Rules

1. The model does not get to freestyle the task.
It only emits legal JSON actions from the bounded action set.

2. Validation happens before execution.
If the compiled plan does not fit the current browser state, Memla rejects it instead of executing it blindly.

3. Browser ontology still owns meaning.
The model helps with messy language, but the browser ontology still decides what actions exist and what success means.

## What Counts As A Real V2 Win

A real Language Ontology V2 win looks like:
- heuristics miss the wording
- the bounded language-model compiler recovers the intent
- the compiled plan validates cleanly
- the existing browser backtester still solves the task

That is not open-ended model improvisation.
It is model-assisted language compilation into C2A.
