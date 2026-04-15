# Action Ontology V2

Action Ontology V2 turns the V1 safety map into draft-only action payloads.

V2 still does not send messages, emails, rides, or purchases automatically.

It can now produce safe confirmation payloads for:

- `ask_contact`
- `draft_message`
- `send_email`

Example:

```text
ask my sister what she wants from DoorDash
```

Becomes:

```text
Action: ask_contact
Recipient: Sister
Draft: What do you want from DoorDash?
Confirmation: required
```

Planned service actions such as `book_ride_quote` and `food_order_quote` remain bridge-gated. They return residuals such as `service_bridge_required` instead of pretending a real Uber or DoorDash transaction is possible.

Successful draft payloads are also recorded as governed memory objects with `action_*` kinds, so the Memory card can distinguish language, autonomy, and action learning.
