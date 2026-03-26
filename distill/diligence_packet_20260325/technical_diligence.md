# Memla Technical Diligence

## Core Loop

1. A user asks a coding question through Memla.
2. Memla retrieves accepted traces, role matches, and transmutations relevant to the task.
3. Memla predicts likely files, commands, tests, and patch steps before the teacher answers.
4. The teacher answers with that repo-shaped context in front of it.
5. Accepted outcomes feed back into the trace log and become future priors.

## Why this is more than RAG

RAG mostly returns similar text. Memla stores reusable structure that survives repo changes:
- roles: what a file does in the workflow
- constraints: what is broken or blocked
- transmutations: what constraint trade solved the task
- verification rituals: which commands and tests close the loop

That structure is what allowed the same-model comparison on the second repo to move from `0.1667` to `0.9167` file recall.

## What the current proof supports

- Strong repo-local compounding
- Real cross-repo transfer once there is enough structural foothold
- Same-model improvement without modifying the target repo

## What the current proof does not support

- Universal coding superiority
- Reliable cold-start dominance on arbitrary repos
- Production-complete governance and retention guarantees

## Public Seeded Support

The public seeded run uses `trpc examples next prisma starter` and a git-history holdout. After the seeding-policy fix, the bootstrap accepted enough traces to create a real compounding test instead of another cold start.

- Seed accept count: `4/8`
- Raw file recall: `0.2653`
- Memla combined file recall: `0.4597`
- Raw command recall: `0`
- Memla combined command recall: `0.5833`

This is supporting evidence because the tasks are noisier and the overlap metric is harsher, but it still matters because it shows the bootstrap pipeline is not limited to the internal repo cluster.

## Most defensible next step

Run the exact same public seeded protocol on a stronger frontier model once credits return, then repeat the workflow on one outside-user repo.
