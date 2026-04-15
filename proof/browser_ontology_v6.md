## Browser Ontology V6

Browser Ontology V6 extends Browser Ontology V5 from bounded two-site research explanation into bounded cross-site subject persistence.

V5 covered:
- choose the best bounded subject
- search a second site about it
- open the best follow-on result
- read the opened page

V6 adds:
- keeping the original research subject alive across another site hop
- so the ontology can move from:
  - GitHub -> YouTube
- to:
  - GitHub -> YouTube -> Reddit

## V6 Goal

V6 is meant for prompts like:
- `find the best repo for c++ llm inference on cpu then find a youtube video about it then find a reddit post about it`
- `find a youtube video about this repo, open it, then find a reddit post about the same repo`
- `compare the first and second repo, pick the winner, search YouTube about it, then search Reddit about it`

The point is not unrestricted browsing.

The point is:
- carry the same bounded subject across multiple site searches
- avoid losing that subject when the currently opened page becomes a video or post
- remain replayable and backtestable

## V6 Composition

V6 still uses bounded transmutations:
- `browser_rank_cards` or `browser_compare_cards`
- `browser_search_subject`
- `open_search_result`
- `browser_read_page`

The difference is that V6 now distinguishes:
- the currently opened page subject
- the carried research subject

That means opening a YouTube video does not destroy the repo-level subject that should drive the Reddit hop.

## V6 State

V6 keeps all V5 browser state and adds a persistent carried subject:
- `research_subject_title`
- `research_subject_url`
- `research_subject_summary`

This is the anchor that survives cross-site handoffs.

Typical V6 flow:
1. rank GitHub repo cards
2. store the winner as both `subject_*` and `research_subject_*`
3. search YouTube about the research subject
4. open a video, which updates `subject_*` to the video
5. search Reddit about the research subject again
6. open and read the Reddit post

## Grounding Rules

V6 keeps all V1-V5 grounding rules and adds:

1. Cross-site follow-ups must use the carried research subject.
They must not drift to the title of the currently opened video or post unless the ontology explicitly says to switch subjects.

2. Multi-hop search is seeded.
Every subject-search hop is backed by seeded result cards in the benchmark case pack.

3. Final explanation remains page-grounded.
The last `browser_read_page` reads the opened page snapshot only.

## Adjudication

A V6 case is only semantically successful if:
- the right initial subject was chosen
- the first cross-site search used that subject
- the second cross-site search also used that same subject
- the correct final follow-on result was opened
- the final page read returned the expected structured fields
- the final `research_subject_title` still matches the intended carried subject

## V6 Benchmark Shape

A Browser Ontology V6 case includes:
- seeded first-site state and cards
- seeded multi-hop `subject_search_steps`
- seeded page snapshots for opened intermediate/final pages
- accepted full action chain
- expected final page state
- expected final carried research subject

## Out Of Scope For V6

V6 still does not claim:
- arbitrary open-web planning
- unrestricted recursive browsing
- login/auth flows
- cloud-agent parity across every site
- self-expanding ontology during the benchmark

V6 is bounded multi-hop subject persistence, not universal browser autonomy.

## What Counts As A Real V6 Win

A real Browser Ontology V6 win looks like:
- same seeded GitHub state
- same seeded YouTube and Reddit follow-on cards
- same seeded page snapshots
- same base model
- raw planning fails to carry the subject cleanly across hops
- Memla keeps the original subject alive and completes the cross-site research chain

That is the point where browser C2A stops looking like a single-hop assistant and starts looking like a bounded research runtime with memory of what the task is actually about.
