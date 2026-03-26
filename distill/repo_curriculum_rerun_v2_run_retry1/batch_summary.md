# Memla Repo Curriculum Batch

- Teacher model: `qwen3.5:9b`
- Case model: `qwen3.5:4b`
- Repos attempted: `7`
- Repos with holdouts: `0`
- Skip threshold: `< 4/8` accepted seeds

## Repo Results

### oauth4webapi

- Repo: `oauth4webapi`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `2/8`
- Seed file recall: `0.1875`
- Seed command recall: `0.125`
- Notes: Seeded at 4/8 in the first batch but timed out on holdout; rerun with a shorter holdout.

### teamhide_fastapi_boilerplate

- Repo: `teamhide fastapi boilerplate`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `1/8`
- Seed file recall: `0.1367`
- Seed command recall: `1.0`
- Notes: Under-seeded in the first batch; rerun to test same-family backend weighting.

### fastapi_template

- Repo: `fastapi template`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `3/8`
- Seed file recall: `0.1846`
- Seed command recall: `0.25`
- Notes: Borderline seed acceptance in the first batch; rerun after backend/security transmutation refinements.

### express_rate_limit

- Repo: `express rate limit`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `2/8`
- Seed file recall: `0.25`
- Seed command recall: `0.375`
- Notes: Security middleware repo that under-seeded previously; good test of family-aware transfer.

### redocly_cli

- Repo: `redocly cli`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `1/8`
- Seed file recall: `0.125`
- Seed command recall: `0.375`
- Notes: CLI/tooling repo that should benefit from stronger repo-family routing and CLI transmutations.

### stripe_nextjs_supabase

- Repo: `launch mvp stripe nextjs supabase`
- Tier: `rerun`
- Status: `error`
- Seed accepted: `0/6`
- Seed file recall: `0.0`
- Seed command recall: `0.0`
- Notes: Sparse commit history repo; start smaller so adaptive fallback has a realistic path.

### guardian_cli

- Repo: `guardian cli`
- Tier: `rerun`
- Status: `skipped_low_seed_signal`
- Seed accepted: `1/6`
- Seed file recall: `0.2022`
- Seed command recall: `0.0`
- Notes: Sparse CLI repo kept in the rerun set to test adaptive fallback and CLI-family transfer.
