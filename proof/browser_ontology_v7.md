## Browser Ontology V7

Browser Ontology V7 extends Browser Ontology V6 from bounded multi-hop subject persistence into bounded result recovery.

V6 covered:
- keeping the same carried subject across GitHub -> YouTube -> Reddit
- opening and reading follow-on pages without losing what the chain was about

V7 adds:
- recovering from a weak follow-on result
- reopening a stronger cached result for the same carried subject

## V7 Goal

V7 is meant for prompts like:
- `find a youtube video about this repo, and if the first one seems weak open a better one`
- `find the best repo, search YouTube about it, recover to a stronger video, then continue to Reddit`
- `compare two repos, search about the winner, and retry if the first follow-on result is off-topic`

The point is not open-ended browsing.

The point is:
- use bounded cached search results
- inspect the first follow-on page
- recover to a better alternative when the first branch is weak
- keep the same carried subject through the recovery

## V7 Composition

V7 adds one bounded transmutation:
- `browser_retry_subject_result`

It composes with:
- `browser_rank_cards` or `browser_compare_cards`
- `browser_search_subject`
- `open_search_result`
- `browser_read_page`

Typical V7 chain:
1. choose the best repo subject
2. search YouTube about it
3. open the first result
4. read it
5. recover to a stronger cached result
6. read that recovered result
7. continue the chain to Reddit using the same carried subject

## V7 State

V7 keeps all V6 state:
- `subject_*`
- `research_subject_*`
- cached `result_urls`
- cached `result_cards`

The crucial idea is:
- `subject_*` can move from weak video -> stronger video
- `research_subject_*` remains the repo-level thing the chain is still about

## Grounding Rules

V7 keeps all V1-V6 grounding rules and adds:

1. Recovery is bounded to cached results.
`browser_retry_subject_result` is not a fresh web search. It chooses a stronger alternative from the current cached result set.

2. Recovery must exclude the current weak page.
The retry transmutation should not reopen the same page it just judged weak.

3. Recovery still serves the carried research subject.
The stronger alternative is chosen because it better matches the carried subject and active goal, not because it is generically popular.

## Adjudication

A V7 case is only semantically successful if:
- the right initial subject was chosen
- the right follow-on search happened
- the first result was opened and read
- the recovery transmutation opened a stronger alternative
- the expected retry-selected title matches the intended stronger result
- the later cross-site handoff still uses the carried research subject
- the final page read returns the expected structured fields

## V7 Benchmark Shape

A Browser Ontology V7 case includes:
- seeded first-site state
- seeded follow-on result cards where result #1 is intentionally weak and result #2 is strong
- seeded snapshots for both the weak and recovered pages
- seeded later-site cards and final page snapshots
- accepted full action chain including `browser_retry_subject_result`
- expected final carried subject and expected retry-selected title

## Out Of Scope For V7

V7 still does not claim:
- unrestricted backtracking across arbitrary sites
- dynamic DOM judgment beyond the bounded snapshots
- live open-web reranking
- universal browsing autonomy

V7 is bounded recovery, not open-world search.

## What Counts As A Real V7 Win

A real Browser Ontology V7 win looks like:
- the first opened video/post is weak
- raw planning does not recover
- Memla uses the recovery transmutation to reopen a stronger cached result
- the original research subject survives the recovery
- the chain still completes to the final bounded answer

That is the point where browser C2A starts looking like a bounded local agent that can self-correct within its ontology, not just follow the first branch it took.
