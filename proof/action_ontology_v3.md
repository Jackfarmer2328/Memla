# Action Ontology V3

Action Ontology V3 adds the first safe message bridge.

The app can now take a Memla message draft and open an iOS Messages draft with the body prefilled.

V3A intentionally does not use Contacts yet:

- Memla drafts the body
- the user taps `Open Message Draft`
- iOS opens Messages
- the user chooses the recipient
- the user presses Send

Memla does not auto-send messages.

This keeps the product aligned with the safety boundary:

```text
Memla prepares and routes.
The user confirms and sends.
```

Contact alias binding can come later as V3B.
