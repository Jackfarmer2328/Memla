# Public Healthcare Denial Demo Pack

This starter pack uses public medical-claim control families while we wait on real denied-claim exports.

Files:
- `cases/healthcare_denial_eval_cases.jsonl`

What this pack covers:
- unit ceilings similar to medically unlikely edits
- required modifier fixes
- NCCI-style code pair conflicts
- diagnosis support mismatches
- prior authorization follow-up
- place-of-service corrections
- non-covered service codes

Primary public sources:
- CMS ICD-10:
  - https://www.cms.gov/medicare/coding-billing/icd-10-codes
- CMS National Correct Coding Initiative:
  - https://www.cms.gov/medicare/coding/nationalcorrectcodinited/index.html
- CMS review reason codes:
  - https://www.cms.gov/data-research/monitoring-programs/medicare-fee-service-compliance-programs/review-reason-codes-and-statements
- X12 claim adjustment reason codes:
  - https://x12.org/codes/claim-adjustment-reason-codes

How to run it:

```powershell
memla healthcare benchmark-denials `
  --cases cases\healthcare_denial_eval_cases.jsonl `
  --raw-model qwen3.5:9b `
  --memla-model qwen3.5:9b `
  --raw-provider ollama `
  --raw-base-url http://127.0.0.1:11435 `
  --memla-provider ollama `
  --memla-base-url http://127.0.0.1:11435
```

What this is not:
- real payer policy exports
- a substitute for client denial logs and remittance files
- a claim that CPT reimbursement logic is fully captured by this pack
