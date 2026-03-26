# Memla Proof Table

| Proof Layer | Repo Type | Setup | Model | File Recall | Command Recall | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Home repo holdout | Internal | Seeded holdout | Mixed internal pipeline | 1 | 1 | Best repo-local compounding proof |
| Second-repo transfer eval | Local/private | Empty-memory vs Memla planner | Local planner stack | 0.6111 -> 0.8611 | 0 -> 1 | Shows transfer without changing the teacher model |
| Second-repo same-model head-to-head | Local/private | Same-model comparison | Frontier model | 0.1667 -> 0.9167 | 0 -> 1 | Headline proof for buyer outreach |
| Public seeded head-to-head | Public OSS | 8 seed + 12 unseen | Local qwen3.5:9b | 0.2653 -> 0.4597 | 0 -> 0.5833 | Supporting public proof (trpc examples next prisma starter); accepted `4/8` seed cases |
| Public curriculum rerun | Public OSS multi-family | Focused family-aware rerun | Local qwen3.5:9b | `6/7` repos reached holdout | stripe_nextjs_supabase: `0` -> `1`, fastapi_template: `0.0625` -> `0.875`, oauth4webapi: `0` -> `0.75` | Shows seeded transfer across backend API, auth/security, and CLI/tooling families |

Use the second-repo same-model row as the headline proof and the public seeded row as supporting diligence material.