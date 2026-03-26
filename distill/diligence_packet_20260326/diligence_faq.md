# Memla Diligence FAQ

## What does Memla store?

Memla stores accepted and rejected coding traces plus derived structure: likely files, likely commands, likely tests, file-role hints, constraint tags, and transmutations. In the current prototype it can also attach workspace evidence such as touched files and diff snapshots when feedback is recorded.

## What makes it different from naive RAG?

Naive RAG retrieves similar text. Memla stores why a fix worked: the role a file played, the constraint that was being resolved, the transmutation that traded one constraint for another, and the verification ritual that closed the loop. That lets it shape the next coding task instead of only adding snippets to context.

## What is the strongest supported claim today?

Memla can materially improve coding-task routing and verification for the same model by reusing accepted coding structure, and that improvement can transfer across repos once there is enough foothold.

## What is not yet supported?

Universal coding superiority is not supported. Cold-start dominance on arbitrary repos is not supported. The public-repo proof is supportive, not yet the main headline.

## Does Memla modify the evaluated repo?

No. The git-history eval packs are generated read-only from commit history and diffs. The target repos used in these evaluations were not edited by Memla during benchmarking.

## What proof exists right now?

- Home repo holdout: `1` / `1`
- Second-repo transfer eval: `0.6111` -> `0.8611`
- Second-repo same-model head-to-head: `0.1667` -> `0.9167`
- Public seeded support (`trpc examples next prisma starter`): `0.2653` -> `0.4597` file recall and `0` -> `0.5833` command recall; seed accept rate `0.5`
- Multi-family curriculum rerun: `6/7` repos reached holdout, with best command lifts including stripe_nextjs_supabase: `0` -> `1`, fastapi_template: `0.0625` -> `0.875`, oauth4webapi: `0` -> `0.75`

## Why is the public proof weaker?

The public backend tasks come from git history, are broader, and are scored against the full changed-file set. That makes the overlap metric much harsher than the focused second-repo proof, but it is still valuable because it shows the bootstrap mechanism works outside the internal repo cluster.

## Best next diligence step

Rerun the exact public seeded protocol on a stronger frontier model once credits are back, then repeat the same workflow on one outside-user repo.
