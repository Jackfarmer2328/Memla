# Action Ontology V1

Action Ontology V1 is the first bounded app-action layer for Memla.

It does not blindly execute purchases, rides, or messages. It defines safe action capabilities with:

- domain
- risk level
- confirmation requirements
- status
- input slots
- safe transmutations

Initial capabilities:

- `browser_scout`
- `ask_contact`
- `draft_message`
- `send_email`
- `book_ride_quote`
- `food_order_quote`
- `track_reply`

The safety rule is simple:

- low-risk browser scouting can run when implemented
- messages, email, rides, and purchases are confirmation-gated
- planned or workaround-required actions return residual constraints instead of pretending they are solved

This is the first step toward "ask Memla instead of opening apps" without copying the Rabbit-style mistake of unbounded app puppeteering.
