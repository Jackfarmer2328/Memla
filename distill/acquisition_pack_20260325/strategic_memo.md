# Memla Strategic Memo

## What Memla Is

Memla is a coding intelligence layer that sits in front of a frontier model, captures accepted coding work, and distills that work into reusable structure.

The critical step is not just memory. Memla stores:
- file-role structure
- constraint tags
- transmutations, meaning the constraint trade that solved the task
- verification rituals like the tests or commands that close the loop

## Why This Matters

Most coding assistants remain stateless. They can answer one task well, but they do not convert that work into owned transferable capability.

Memla's thesis is that successful coding work should compound. Once a model and user solve a task, the next similar task should become easier, faster, and more repo-shaped. The new transfer results show that this compounding can cross repo boundaries when the stored unit is a transmutation rather than just a file path.

## Proof

- Home repo coding holdout: `1` file recall / `1` command recall
- Free second-repo transfer eval: `0.6111` -> `0.8611` file recall and `0` -> `1` command recall
- Paid Claude second-repo head-to-head: `0.1667` -> `0.9167` file recall and `0` -> `1` command recall

## Why It Is Novel

Memla is not just retrieval, not just trace logging, and not just fine-tuning from outputs. Its novel layer is transmutation reuse: it learns the role/constraint trade behind a successful fix, then maps that trade onto the next repo's local files and validation rituals.

## Why A Buyer Would Care

- It makes a strong general model feel repo-native faster.
- It turns expensive frontier-model spend into owned capability.
- It creates compounding product value instead of one-off completions.
- It can sit under an existing coding assistant, agent platform, or memory product.

## Honest Limits

- Proof is still internal.
- Eval size is still small.
- This is not universal coding solved.

But it is already beyond a toy. The second-repo results are strong enough to support serious design-partner or acquisition conversations.
