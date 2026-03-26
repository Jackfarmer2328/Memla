# Memla Repo Curriculum Batch

- Teacher model: `qwen3.5:9b`
- Case model: `qwen3.5:4b`
- Repos attempted: `7`
- Repos with holdouts: `4`
- Skip threshold: `< 4/8` accepted seeds

## Repo Results

### oauth4webapi

- Repo: `oauth4webapi`
- Tier: `rerun`
- Status: `completed`
- Seed accepted: `4/8`
- Seed threshold: `3/8` (family_structural)
- Seed file recall: `0.2708`
- Seed role recall: `0.5`
- Seed command recall: `0.25`
- Raw file recall: `0.0417`
- Memla combined file recall: `0.0`
- Raw command recall: `0.0`
- Memla combined command recall: `0.75`
- Notes: Seeded at 4/8 in the first batch but timed out on holdout; rerun with a shorter holdout.

### teamhide_fastapi_boilerplate

- Repo: `teamhide fastapi boilerplate`
- Tier: `rerun`
- Status: `completed`
- Seed accepted: `4/8`
- Seed threshold: `3/8` (family_structural)
- Seed file recall: `0.0456`
- Seed role recall: `0.4583`
- Seed command recall: `1.0`
- Raw file recall: `0.125`
- Memla combined file recall: `0.4167`
- Raw command recall: `1.0`
- Memla combined command recall: `1.0`
- Notes: Under-seeded in the first batch; rerun to test same-family backend weighting.

### fastapi_template

- Repo: `fastapi template`
- Tier: `rerun`
- Status: `completed`
- Seed accepted: `3/8`
- Seed threshold: `3/8` (family_structural)
- Seed file recall: `0.1013`
- Seed role recall: `0.5417`
- Seed command recall: `0.25`
- Raw file recall: `0.0`
- Memla combined file recall: `0.1375`
- Raw command recall: `0.0625`
- Memla combined command recall: `0.875`
- Notes: Borderline seed acceptance in the first batch; rerun after backend/security transmutation refinements.

### express_rate_limit

- Repo: `express rate limit`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `2/8`
- Seed threshold: `4/8` (default)
- Seed file recall: `0.25`
- Seed role recall: `0.375`
- Seed command recall: `0.375`
- Notes: Security middleware repo that under-seeded previously; good test of family-aware transfer.

### redocly_cli

- Repo: `redocly cli`
- Tier: `rerun`
- Status: `completed`
- Seed accepted: `3/8`
- Seed threshold: `3/8` (family_structural)
- Seed file recall: `0.125`
- Seed role recall: `0.5`
- Seed command recall: `0.375`
- Raw file recall: `0.1354`
- Memla combined file recall: `0.125`
- Raw command recall: `0.125`
- Memla combined command recall: `0.875`
- Notes: CLI/tooling repo that should benefit from stronger repo-family routing and CLI transmutations.

### stripe_nextjs_supabase

- Repo: `launch mvp stripe nextjs supabase`
- Tier: `rerun`
- Status: `error`
- Seed accepted: `0/6`
- Seed threshold: `4/6` (default)
- Seed file recall: `0.0`
- Seed role recall: `0.0`
- Seed command recall: `0.0`
- Notes: Sparse commit history repo; start smaller so adaptive fallback has a realistic path.

### guardian_cli

- Repo: `guardian cli`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `2/6`
- Seed threshold: `4/6` (default)
- Seed file recall: `0.2022`
- Seed role recall: `0.375`
- Seed command recall: `0.0`
- Notes: Sparse CLI repo kept in the rerun set to test adaptive fallback and CLI-family transfer.

## Top Transmutations

- `14` x Trade permissive request flow for stricter authentication and session integrity.
- `10` x Trade loose input handling for stricter schema-driven validation.
- `10` x Trade local implementation freedom for a preserved external contract.
- `8` x Trade shell flexibility for a repeatable command-line workflow.
- `7` x Trade stale dependency stability for updated compatibility plus verification.
- `4` x Trade downstream flexibility for earlier middleware enforcement and validation.
- `2` x Trade transient UI state for recoverable session-backed booking state.
