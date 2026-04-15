# Browser Ontology V1

This document locks the first Memla browser ontology into a stable, backtestable surface.

The point of this lock is not to claim a finished browser agent. The point is to stop ontology drift long enough to:
- run same-model before/after comparisons
- build a browser benchmark harness
- collect human-approved transmutation traces
- distinguish real C2A improvement from ad hoc browser scripting

This is bounded-runtime evidence, not universal browser-agent proof complete.

## V1 Goal

Browser Ontology V1 covers a narrow but useful browser scout/control wedge:
- open a search page
- continue from search results
- open or switch tabs
- move backward or forward
- scroll
- type and submit into the active browser
- extract current result cards
- extract the current page
- take a screenshot
- do lightweight media pause/play on supported systems

V1 is designed for:
- GitHub search -> repo open -> repo read
- YouTube search -> video open -> pause/play
- Reddit or Amazon search continuation
- human-in-the-loop workbench approval and trace logging

V1 is not designed for:
- arbitrary DOM agents
- login-heavy flows
- CAPTCHA handling
- arbitrary coordinate clicking
- general autonomous web browsing across unknown sites

## Why This Is Locked

Without an ontology lock, every failure can be hidden by adding another special case.

With an ontology lock:
- the world state is fixed
- the allowed transmutations are fixed
- success and failure are fixed
- raw vs Memla comparisons become meaningful
- browser traces become reusable training signal instead of one-off demos

## State Schema

The runtime state for Browser Ontology V1 is the current `BrowserSessionState`.

| Field | Type | Meaning |
| --- | --- | --- |
| `current_url` | `str` | Current browser URL if known. |
| `page_kind` | `str` | Page archetype label for the current page. |
| `search_engine` | `str` | Search engine or site context for the current search flow. |
| `search_query` | `str` | Normalized active search query when the current state came from search. |
| `result_urls` | `list[str]` | Cached result URLs for the active search flow. |
| `result_cards` | `list[dict]` | Cached structured cards for the active search flow. |

### Locked Page Kinds

| `page_kind` | Meaning |
| --- | --- |
| `blank_tab` | A fresh tab created by `browser_new_tab` and not yet navigated. |
| `search_results` | A supported search page such as GitHub search, YouTube results, Reddit search, or Amazon search. |
| `repo_page` | A GitHub repository root page matching `owner/repo`. |
| `video_page` | A YouTube watch page. |
| `post_page` | A Reddit comments/post page. |
| `web_page` | Fallback for any page that does not match a more specific V1 archetype. |

Unknown or unsupported page types collapse to `web_page`.

### Locked Search Engines

The planner may generate or continue search flows for:
- `github`
- `youtube`
- `reddit`
- `amazon`
- `google`
- `web`

Only some of these currently have richer extraction behavior. V1 still allows the full list as search contexts.

### Locked Result Card Shape

Every cached card must contain at least:
- `index`
- `title`
- `url`
- `summary`

Cards may additionally contain fields such as:
- `meta`
- `repo`
- `stars`
- `forks`
- `language`
- `topics`

V1 does not require every card source to populate every optional field.

## Action Schema

These are the locked browser transmutations for V1.

| Action kind | Meaning in V1 |
| --- | --- |
| `open_url` | Open a concrete URL. When paired with `browser_new_tab` and `tab_mode=new_tab`, navigate the newly opened active tab instead of opening a separate extra tab. |
| `browser_new_tab` | Send the new-tab shortcut to the active browser window. |
| `browser_close_tab` | Send the close-tab shortcut to the active browser window. |
| `browser_switch_tab` | Switch tabs by `next`, `previous`, or numeric target such as `2`. |
| `browser_back` | Send browser back. |
| `browser_forward` | Send browser forward. |
| `browser_scroll` | Scroll the active browser `up` or `down`. |
| `open_search_result` | Open the Nth result URL from the active cached search state. |
| `browser_click_index` | Open the Nth cached result card. |
| `browser_click_text` | Open the cached result card whose title, URL, or summary best matches the requested text. |
| `browser_read_page` | Read the current page and render a human-readable structured summary message. |
| `browser_extract_page` | Extract a structured page snapshot from the current page. |
| `browser_extract_cards` | Extract or refresh cached structured cards from the current search-results page. |
| `browser_type_text` | Type literal text into the active browser focus target. |
| `browser_submit` | Send Enter/submit into the active browser. |
| `browser_wait` | Wait a bounded number of seconds. |
| `browser_screenshot` | Capture a screenshot to a local file. |
| `browser_media_pause` | Pause media playback if the platform supports it. |
| `browser_media_play` | Resume media playback if the platform supports it. |

### Grounding Rules

These rules are part of the ontology lock.

1. `browser_click_index` and `browser_click_text` are not arbitrary DOM clicks.
They are card-grounded transmutations over `result_cards`.

2. `open_search_result` is not arbitrary search inference.
It is grounded to `search_engine`, `search_query`, `result_urls`, and `result_cards`.

3. `browser_read_page` and `browser_extract_page` are not freeform summaries over arbitrary browser memory.
They are grounded to the fetched HTML of `current_url`.

4. `browser_new_tab`, `browser_close_tab`, `browser_switch_tab`, `browser_back`, `browser_forward`, `browser_scroll`, `browser_type_text`, and `browser_submit` are active-browser shortcuts.
They act on the currently focused browser, not a tracked browser identity.

5. V1 does not include browser affinity.
If Brave owns the session state but Chrome has focus, the shortcut lands in Chrome. That is a known V1 limitation, not hidden behavior.

## Page Extraction Contract

`browser_extract_page` returns a structured snapshot with:
- `url`
- `page_kind`
- `title`
- `summary`

And may additionally return page-kind-specific fields such as:

### `repo_page`
- `repo`
- `description`
- `stars`
- `forks`
- `language`
- `homepage`
- `topics`

### `video_page`
- `channel`

### `post_page`
- post summary fields when available from page metadata

V1 explanation quality is judged against extracted evidence, not against unconstrained prose.

## Adjudication Rules

Browser Ontology V1 is only useful if actions are adjudicated.

### Step-Level Success

Each executed action yields:
- `status = ok` or `failed`
- a human-readable message
- optional structured `details`

### State Transition Success

A browser action is considered state-valid when it produces the expected transition class:

| Action family | Expected transition |
| --- | --- |
| `open_url` | `current_url` changes to the requested URL and `page_kind` is recomputed. |
| `browser_new_tab` | `page_kind -> blank_tab` and `current_url -> browser://new-tab`. |
| `browser_close_tab` | Browser state is cleared. |
| `browser_switch_tab` | Shortcut sent successfully; state may be unknown until the next grounded read/extract. |
| `browser_back` / `browser_forward` | Shortcut sent successfully; state may be unknown until the next grounded read/extract. |
| `open_search_result` | Result URL opens and browser state updates to the resolved target page. |
| `browser_click_index` / `browser_click_text` | Cached card resolves to a URL and that target opens. |
| `browser_extract_cards` | Non-error card extraction occurs and cached card state is refreshed. |
| `browser_read_page` / `browser_extract_page` | Current page fetch succeeds and a structured snapshot is produced. |
| `browser_type_text` / `browser_submit` / `browser_scroll` / `browser_wait` | Action executes without platform failure; later state change depends on follow-up extraction. |
| `browser_screenshot` | Screenshot file exists at the recorded path. |
| `browser_media_pause` / `browser_media_play` | Media command executes without platform failure. |

### Task-Level Success

A browser task should eventually be evaluated on:
- action execution success
- expected state transition achieved
- required fields extracted
- residual constraints emitted
- latency

V1 does not claim that shortcut execution alone proves semantic completion. For many tasks, semantic completion requires a follow-up read, extract, or screenshot.

## Residual Classes

V1 treats residuals as first-class evidence. The following residual families are canonical:

### Planning residuals
- `unsupported_risky_action`
- `unsupported_or_ambiguous_request`
- `llm_fallback_unavailable`

### Browser state residuals
- `browser_state_missing_search_results`
- `browser_state_missing_current_url`
- `browser_state_persist_failed`

### Search/result residuals
- `search_result_fetch_failed`
- `search_result_unavailable`
- `click_target_unavailable`

### Page/extraction residuals
- `browser_page_fetch_failed`

### Platform capability residuals
- `browser_new_tab_unavailable:<platform>`
- `browser_close_tab_unavailable:<platform>`
- `browser_switch_tab_unavailable:<platform>`
- `browser_back_unsupported:<platform>`
- `browser_back_unavailable`
- `browser_forward_unavailable:<platform>`
- `browser_scroll_unavailable:<platform>`
- `browser_type_text_unavailable:<platform>`
- `browser_submit_unavailable:<platform>`
- `browser_screenshot_unavailable:<platform>`
- `browser_media_unavailable:<action_kind>`

### Generic execution residuals
- `open_command_unavailable:<platform>`
- `unsupported_action:<action_kind>`

Exact residual strings may carry parameters, but these families are the locked semantic categories for V1 reporting.

## Trace Contract

Human-in-the-loop approvals in the workbench are logged as JSONL rows.

Each row includes:
- `generated_ts`
- `prompt`
- `constraints`
- `chosen_candidate_id`
- `chosen_label`
- `chosen_origin`
- `chosen_rationale`
- `chosen_plan`
- `execution`

This trace contract matters because V1 is not only a browser runtime. It is also the substrate for:
- human-approved browser transmutation banks
- later policy distillation
- browser ontology expansion from repeated failure clusters

## Benchmark Fairness Rules

Any future browser benchmark or public result using Browser Ontology V1 should obey these rules:

1. Hold the ontology constant.
Do not add or remove primitives mid-benchmark.

2. Hold the browser state contract constant.
Raw and Memla lanes must receive the same prompt and the same browser state fields.

3. Report both execution success and semantic success.
Do not treat shortcut issuance alone as the whole task if the task requires extraction or verification.

4. Report residuals.
Residual constraints are part of the evidence, not just debugging noise.

5. Report latency.
V1 is partly about making small local models practical, so time-to-action matters.

6. Prefer same-model controls.
The cleanest browser claim is same model, same ontology, raw versus Memla runtime.

## V1 Eval Pack Categories

The first browser benchmark pack should draw tasks from these categories:

1. Search initiation
- open GitHub and search `llama.cpp`
- search YouTube for `nine vicious`

2. Search continuation
- click the first repo
- click item 2
- click `ollama`

3. Tab control
- open a new tab
- close the tab
- switch to the next tab

4. Navigation
- go back
- go forward
- scroll down

5. Page extraction
- extract cards
- what is this repo
- extract current page

6. Input and submit
- type `hello world`
- submit
- wait 2 seconds

7. Media and screenshot
- pause it
- play it
- take screenshot

## Out Of Scope For V1

V1 explicitly does not cover:
- browser identity or browser affinity
- DOM selectors
- mouse coordinates
- authenticated flows
- CAPTCHA resolution
- arbitrary multi-site workflows with hidden state
- form semantics beyond type and submit
- table extraction
- ranking or comparison as a first-class primitive
- autonomous plan synthesis beyond the locked primitive grammar

Those may belong to V2 or later, but they are not part of the V1 claim.

## What Counts As A Real V1 Win

A real Browser Ontology V1 win looks like:
- a fixed browser state
- a fixed primitive grammar
- a fixed adjudicator
- the same prompt/task pack
- the same base model
- Memla choosing or sequencing better transmutations than the raw lane

That is the standard that turns browser use from a cool demo into actual C2A evidence.
