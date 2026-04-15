# Mission Queue V1

Mission Queue V1 turns Memla action capsules into checkpointed jobs.

V1 adds:

- `POST /missions`
- `GET /missions`
- `GET /missions/{mission_id}`
- `POST /missions/{mission_id}/decision`

Each mission stores:

- prompt
- action capsule
- status
- current checkpoint
- decision history

Checkpoints expose explicit decisions such as:

- approve
- open
- cancel
- modify

Commerce and messaging missions remain confirmation-gated. A food delivery mission can move from capsule approval into a user-browser checkpoint, but Memla still blocks final payment, send, booking, and place-order actions. The iPhone app can now act as the approval surface for the local runtime without pretending that the phone can keep a hidden browser worker alive after iOS suspends the app.

V1 is intentionally local and in-memory. Later versions can attach durable storage, actionable notifications, APNs, and a worker that resumes missions between checkpoints.
