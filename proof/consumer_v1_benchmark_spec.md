# Memla Consumer V1 Benchmark Spec

## Purpose

This document defines the benchmark, roadmap, and funding gate for a consumer Memla V1.

The product goal is not "do everything on every app."

The product goal is:

- a user speaks a common high-frequency request
- Memla compiles it into conserved constraints
- Memla reaches the intended terminal state with no non-boundary human intervention
- Memla does this reliably enough that it feels magical

For V1, the highest-priority lanes are:

1. food ordering
2. rides
3. navigation
4. reorder and status operations

## Core Product Claim

The V1 claim is:

`You ask, it does. Food, rides, navigation, reorders, status.`

That claim is only real if the benchmark measures the right thing.

The north-star metric is:

`completion rate = initiated tasks that reach the intended terminal state without non-boundary human intervention`

## Why This Metric Matters

At this stage, completion rate is more important than:

- downloads
- DAU
- top-line session counts
- raw model quality

Completion rate directly measures whether the C2A runtime works.

If Memla can repeatedly preserve constraints from prompt to terminal state, the product thesis is real.

If it cannot, no amount of interface polish will save it.

## C2A Framing For This Benchmark

Consumer V1 is measured as a constraint-preserving transaction runtime.

Each run should follow this pattern:

1. user request compiles into typed constraints
2. app/page state distills into local executable constraints
3. planner selects the next legal transition
4. execution acts on the live UI
5. state only advances after postcondition confirmation
6. the run stops at the correct boundary or completes the intended task

The benchmark should reward:

- correct completion
- preservation of requested constraints
- correct traversal of derived local constraints
- minimal human rescue

The benchmark should punish:

- wrong merchant/item/destination
- silent constraint loss
- random page drift
- loops
- irreversible wrong actions

## V1 Scope

### Included

- DoorDash food ordering
- Uber Eats food ordering
- Uber ride quoting and booking-ready flows
- map navigation start flows
- Amazon reorder and status flows
- Target reorder, pickup, and status flows

### Explicitly Not In V1

- arbitrary open-ended shopping across all ecommerce
- arbitrary email triage
- broad calendar assistant behavior
- full smart home orchestration
- payment sending without stronger identity/approval policies

## Terminal States

Each task class needs an explicit terminal state.

### DoorDash

- `checkout_ready`
  - correct merchant selected
  - correct item selected
  - requested size/modifiers preserved
  - cart contains intended item configuration
  - Memla has reached checkout boundary or checkout-adjacent confirmation screen

### Uber Eats

- `checkout_ready`
  - same semantics as DoorDash

### Uber

- `quote_ready`
  - pickup and destination are correct
  - price/options are visible
  - request is ready but not irrevocably submitted without required approval

### Navigation

- `navigation_started`
  - destination is correct
  - route is actively started in the maps app

### Amazon

- `reorder_complete`
  - reorder placed or checkout-ready for exact reorder flow, depending on policy

- `status_resolved`
  - requested package or order status page is reached and answer is available

### Target

- `pickup_ready`
  - pickup order built or checkout-ready

- `status_resolved`
  - requested order state is reached and answer is available

## Intervention Taxonomy

This must be enforced consistently.

### Allowed Without Failing Completion

- wake word / initial request
- one boundary approval, if policy requires it
- a clarification question only when the request is genuinely ambiguous

### Counts As Failure

- user manually tapping through the app because Memla got stuck
- user correcting merchant/item/modifier/destination
- user recovering a wrong turn
- user re-inspecting because Memla failed to progress
- user manually exiting loops

### Boundary Approval

Boundary approval is not failure when it is policy-consistent.

Examples:

- "Ready for checkout, confirm?"
- "Ride quote is ready, confirm?"
- "Start navigation?"

If Memla needs boundary approval on every step, that is failure of autonomy, not success.

## Benchmark Dashboard

Track these metrics per app and per suite:

- completion_rate
- median_time_to_terminal_state
- p90_time_to_terminal_state
- clarification_rate
- non_boundary_intervention_rate
- wrong_target_rate
- loop_or_stall_rate
- catastrophic_error_rate
- retry_recovery_rate

### Catastrophic Error

A catastrophic error is any run where Memla:

- selects the wrong merchant or item and continues
- submits or nearly submits the wrong order
- starts navigation to the wrong destination
- opens the wrong irreversible payment/request flow

Target for catastrophic error rate:

- effectively `0`

## Funding Gate

This is the proposed pre-raise gate for V1.

- DoorDash checkout-ready completion `>= 92%`
- Uber Eats checkout-ready completion `>= 90%`
- Uber quote-ready completion `>= 95%`
- Navigation started completion `>= 97%`
- Amazon reorder/status completion `>= 95%`
- Target reorder/pickup/status completion `>= 92%`
- weighted V1 completion across the full corpus `>= 93%`
- catastrophic error rate `0`
- repeatable live demo across at least 3 app families

If these numbers are met, the software wedge is fundable even with a scrappy hardware shell.

## Corpus Format

Every benchmark case should be stored in a structured format with these fields:

- `case_id`
- `app_family`
- `merchant_or_service`
- `prompt`
- `task_class`
- `initial_state_assumptions`
- `terminal_state`
- `boundary_policy`
- `allowed_clarifications`
- `expected_constraints`
- `expected_derived_constraints`
- `notes`

### Example Schema

```json
{
  "case_id": "DD-PIZZA-003",
  "app_family": "doordash",
  "merchant_or_service": "Domino's",
  "prompt": "Doordash a large cheese pizza from dominos, with chicken and pineapple",
  "task_class": "food_customizer_multimodifier",
  "initial_state_assumptions": [
    "logged_in",
    "delivery_address_set"
  ],
  "terminal_state": "checkout_ready",
  "boundary_policy": "allow_checkout_confirmation_only",
  "allowed_clarifications": [],
  "expected_constraints": [
    "service=DoorDash",
    "restaurant=Domino's",
    "item=cheese pizza",
    "size=large",
    "toppings=chicken",
    "toppings=pineapple"
  ],
  "expected_derived_constraints": [
    "crust",
    "topping_side"
  ],
  "notes": "Primary hard customizer regression case."
}
```

## DoorDash Roadmap

DoorDash is the anchor runtime.

It should be treated as the main proving ground for:

- prompt -> order spec compilation
- customizer traversal
- add-to-cart
- cart to checkout

### DoorDash Success Definition

DoorDash is considered "conquered for V1" when Memla can:

- reliably reach checkout on the common item grammars
- preserve requested modifiers under customizer branching
- recover from default selections and required local constraints
- reorder common items
- answer order status

### DoorDash Test Lanes

#### A. Pizza Customizer

- `DD-PIZZA-001` Domino's cheese pizza, no modifiers
- `DD-PIZZA-002` Domino's large cheese pizza
- `DD-PIZZA-003` Domino's large cheese pizza with chicken and pineapple
- `DD-PIZZA-004` Domino's medium cheese pizza with one topping
- `DD-PIZZA-005` Domino's pizza with explicit crust request
- `DD-PIZZA-006` Domino's pizza with explicit no seasoning
- `DD-PIZZA-007` Domino's pizza quantity two
- `DD-PIZZA-008` Domino's pizza plus one add-on item

#### B. Same Platform, Different Merchant

- `DD-PIZZAHUT-001` Pizza Hut simple pizza
- `DD-PAPAJOHNS-001` Papa Johns simple pizza
- `DD-LOCALPIZZA-001` local pizza restaurant with different customizer layout

#### C. Non-Pizza Food Grammars

- `DD-BURGER-001` burger with cheese and one add-on
- `DD-BURRITO-001` burrito/bowl flow with protein and toppings
- `DD-COFFEE-001` coffee chain usual order
- `DD-SANDWICH-001` sandwich with bread/protein/toast

#### D. Reorder And Status

- `DD-REORDER-001` order my usual from Domino's
- `DD-REORDER-002` reorder last coffee order
- `DD-STATUS-001` where is my order
- `DD-STATUS-002` when does my order arrive

#### E. Recovery

- `DD-RECOVERY-001` stale cart already open
- `DD-RECOVERY-002` background item modal still mounted
- `DD-RECOVERY-003` item unavailable
- `DD-RECOVERY-004` required group already default-selected
- `DD-RECOVERY-005` cart drawer/item modal overlap

### DoorDash Benchmark Thresholds

- smoke suite completion `>= 95%`
- release suite completion `>= 92%`
- median time to checkout-ready `< 90s`
- wrong modifier rate `<= 1%`
- catastrophic error rate `0`

## Uber Eats Roadmap

Uber Eats is the transfer test.

The rule is:

- do not redesign the architecture first
- port the same C2A grammar and see what transfers

### Uber Eats Test Lanes

#### A. Mirror DoorDash Pizza Cases

- `UE-PIZZA-001` simple cheese pizza
- `UE-PIZZA-002` large cheese pizza
- `UE-PIZZA-003` large cheese pizza with chicken and pineapple
- `UE-PIZZA-004` one topping
- `UE-PIZZA-005` explicit crust if merchant exposes it

#### B. Other Common Food Grammars

- `UE-BURGER-001`
- `UE-BURRITO-001`
- `UE-COFFEE-001`
- `UE-SANDWICH-001`

#### C. Reorder And Status

- `UE-REORDER-001`
- `UE-STATUS-001`

### Uber Eats Thresholds

- first-pass transfer rate on mirrored DoorDash cases: track separately
- adapted checkout-ready completion `>= 90%`
- median time `< 90s`
- catastrophic error rate `0`

## Uber Roadmap

Uber is a separate workflow family:

- location resolution
- quote retrieval
- vehicle option surface
- booking boundary

### Uber Test Lanes

- `UB-RIDE-001` get me an Uber to the airport
- `UB-RIDE-002` get me an Uber home
- `UB-RIDE-003` get me an Uber to U.S. Bank Stadium
- `UB-RIDE-004` current location to typed destination
- `UB-RIDE-005` quote only, no booking
- `UB-RIDE-006` ambiguous destination requiring clarification

### Uber Thresholds

- quote-ready completion `>= 95%`
- median time `< 45s`
- wrong destination rate `<= 1%`
- catastrophic error rate `0`

## Navigation Roadmap

Navigation is likely one of the cleanest wearable-native lanes.

### Navigation Test Lanes

- `MAP-001` take me home
- `MAP-002` take me to Whole Foods
- `MAP-003` navigate to the nearest Target
- `MAP-004` walk me to the coffee shop
- `MAP-005` drive me to the airport avoiding tolls
- `MAP-006` take me to saved place
- `MAP-007` disambiguate between two same-brand destinations

### Navigation Thresholds

- navigation-started completion `>= 97%`
- median time `< 15s`
- wrong destination rate `<= 1%`

## Amazon Roadmap

Amazon V1 is not broad shopping.

Amazon V1 is:

- reorder
- exact-item buy
- status

### Amazon Test Lanes

#### A. Reorder

- `AMZ-REORDER-001` order more of my coffee
- `AMZ-REORDER-002` reorder batteries
- `AMZ-REORDER-003` reorder paper towels

#### B. Status

- `AMZ-STATUS-001` where is my package
- `AMZ-STATUS-002` when does my order arrive

#### C. Exact Item

- `AMZ-EXACT-001` buy the same phone case again
- `AMZ-EXACT-002` buy the same protein powder again

### Amazon Thresholds

- reorder/status completion `>= 95%`
- exact-item checkout-ready completion `>= 90%`
- median reorder/status time `< 20s`

## Target Roadmap

Target V1 should focus on:

- pickup
- reorder
- order status

### Target Test Lanes

- `TGT-PICKUP-001` add paper towels to my pickup order
- `TGT-PICKUP-002` add dish soap to my pickup order
- `TGT-REORDER-001` reorder what I got last time
- `TGT-STATUS-001` is my order ready
- `TGT-STATUS-002` when can I pick up my order

### Target Thresholds

- pickup/reorder/status completion `>= 92%`
- exact-item add-to-order completion `>= 88%`

## Named Benchmark Suites

These suites should exist for every app family.

### Smoke Suite

Purpose:

- detect immediate regressions

Size:

- 5 cases per app family

Runs:

- every code change touching that app adapter or workflow runtime

### Daily Regression Suite

Purpose:

- protect the current wedge

Size:

- 20 cases per app family

Runs:

- daily
- before shipping builds

### Release Suite

Purpose:

- produce investor-grade numbers

Size:

- 50 to 100 cases per app family

Runs:

- before every milestone demo
- before fundraising deck numbers are updated

### Live Audit Suite

Purpose:

- prove the benchmark reflects real user behavior

Size:

- 10 runs per app family

Requirements:

- screen recording
- timestamped terminal state
- manual auditor notes

## Pass/Fail Rules

### Pass

A run passes if:

- it reaches the declared terminal state
- requested constraints are satisfied
- there was no non-boundary human intervention
- no catastrophic error occurred

### Fail

A run fails if:

- it stalls
- it loops
- it lands on the wrong merchant/item/destination
- it loses a requested constraint
- it requires manual rescue before terminal state
- it hits the wrong irreversible flow

### Soft Fail

Use a separate label for:

- successful completion only after one allowed clarification

Soft fails should not be merged into full pass rate.

Track them separately as:

- `clarified_completion_rate`

## Weekly Execution Plan

This is the recommended near-term plan from the current state.

### Week 1: DoorDash Hardening

Goals:

- turn current DoorDash success into a real benchmark
- stop depending on heroic one-off fixes

Deliverables:

- 25 DoorDash benchmark cases encoded
- smoke suite runnable
- release dashboard with completion, time, and failure taxonomy
- Domino's and one additional pizza merchant above `90%`

### Week 2: DoorDash Breadth

Goals:

- prove transfer across item grammars inside the same platform

Deliverables:

- burger, burrito, coffee, sandwich lanes added
- reorder and status flows added
- DoorDash release suite at `>= 92%`

### Week 3: Uber Eats Transfer

Goals:

- run mirrored food cases on Uber Eats with minimal new architecture

Deliverables:

- mirrored corpus for Uber Eats
- clear transfer report: what worked without code, what needed adapter fixes
- Uber Eats smoke suite above `85%`

### Week 4: Uber Reliability And Navigation

Goals:

- turn Uber into a stable quote-ready lane
- bring navigation online as a second magical wearable-native lane

Deliverables:

- Uber quote-ready suite above `95%`
- navigation-started suite above `95%`

### Week 5: Amazon And Target Narrow Lanes

Goals:

- prove non-food commerce without taking on full open-ended shopping

Deliverables:

- Amazon reorder/status suite above `90%`
- Target pickup/reorder/status suite above `88%`

### Week 6: V1 Fundraise Gate

Goals:

- produce investor-grade numbers
- tighten the story to "food, rides, navigation, reorders"

Deliverables:

- full release suite runs
- weighted V1 completion report
- catastrophic error audit
- live demo script
- earpiece interaction demo on top of phone runtime

## Reporting Format

Every milestone report should include:

- suite name
- run date
- app family
- number of cases
- completion rate
- clarified completion rate
- median time
- p90 time
- wrong target rate
- catastrophic error count
- top 5 failure modes

### Example Summary

```text
DoorDash Release Suite
cases: 60
completion_rate: 0.933
clarified_completion_rate: 0.967
median_time_to_checkout_ready: 72s
wrong_target_rate: 0.0
catastrophic_error_rate: 0.0
top_failures:
- customizer save/add bridge
- stale cart drawer detection
- unavailable merchant item
```

## The Fundable Story

By the time this benchmark is green, the pitch is:

- Memla is a constraint-preserving transaction runtime
- it already completes real consumer tasks from voice to terminal state
- the earpiece is just the thinnest possible shell over that runtime

The raise should be based on:

- repeatable completion numbers
- visible transfer across app families
- low-friction voice interaction
- clear path from phone runtime to wearable interface

That is much stronger than a pure hardware pitch.

## Immediate Next Move

The next move is not "add random new apps."

The next move is:

1. encode the DoorDash cases
2. run them repeatedly
3. drive DoorDash above the threshold
4. then mirror the same corpus into Uber Eats

That is the shortest path from current success to a fundable V1.
