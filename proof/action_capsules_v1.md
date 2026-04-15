# Action Capsules V1

Action Capsules V1 turns action-ontology matches into authorization-aware workflow objects.

The goal is to separate "Memla understands the request" from "Memla is allowed to finish the real-world action."

Capsules expose:

- `authorization_level`
- `confirmation_required`
- `auto_submit_allowed`
- `verifier_requirements`
- `auto_submit_blockers`
- `bridge_kind`
- `bridge_options`
- `bridge_instructions`
- structured `slots`

Current behavior:

- `browser_scout` can remain `auto_execute` because it only searches, reads, ranks, and reports.
- messaging drafts can reach `open_confirmation_screen` through the iOS Messages compose bridge, but the user still chooses the recipient and presses Send.
- food order and ride requests become structured capsules, but stay `service_bridge_required` and `auto_submit_allowed=false`.
- food order capsules now expose separate bridge options for the service app and in-app web search, so the service-specific bridge can improve without turning the capsule itself into a DoorDash-only bot.

This is the first explicit trust ladder for app-like actions:

```text
draft_only -> open_confirmation_screen -> future auto_submit_candidate
```

V1 intentionally does not auto-submit purchases, rides, or messages.
