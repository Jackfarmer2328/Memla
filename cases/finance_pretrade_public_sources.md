# Public Finance Demo Pack

This pack keeps the current finance demo grounded in public market-access guidance while we wait on real client exception exports.

Files:
- `cases/finance_pretrade_public_eval_cases.jsonl`
- `cases/finance_pretrade_eval_cases.jsonl`

What this public pack covers:
- hard pre-trade credit or capital thresholds
- pre-order regulatory checks via restricted symbols
- duplicate-order soft review controls
- erroneous price or reference-band controls
- supervisor approval thresholds
- unsupported access path controls
- projected long and short exposure controls

Case mapping:

| Case ID | Public control family |
| --- | --- |
| `public_credit_limit_reduce` | hard credit or capital threshold remediation |
| `public_restricted_symbol_block` | pre-order regulatory check |
| `public_duplicate_soft_review_escalate` | soft duplicate-order review |
| `public_price_band_reprice` | erroneous order or price-band control |
| `public_approval_threshold_escalate` | soft approval threshold |
| `public_unsupported_route_block` | direct control over enabled access paths |
| `public_projected_long_position_block` | projected long exposure limit |
| `public_projected_short_position_block` | projected short exposure limit |

Primary public sources:
- SEC Rule 15c3-5 overview:
  - https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access
- SEC Rule 15c3-5 FAQ:
  - https://www.sec.gov/rules-regulations/staff-guidance/trading-markets-frequently-asked-questions/divisionsmarketregfaq-0
- FINRA 2026 Market Access Rule report:
  - https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/market-access-rule

How to run it:

```powershell
memla finance benchmark-pretrade `
  --cases cases\finance_pretrade_public_eval_cases.jsonl `
  --raw-model qwen3.5:9b `
  --memla-model qwen3.5:9b `
  --raw-provider ollama `
  --raw-base-url http://127.0.0.1:11435 `
  --memla-provider ollama `
  --memla-base-url http://127.0.0.1:11435
```

What this is not:
- real broker-dealer exception data
- a substitute for client exports, reject logs, or release rationales
- a claim that public rule text alone is enough for production integration

Useful public next step:
- overlay market-event realism from public order book data such as LOBSTER sample files:
  - https://data.lobsterdata.com/info/WhatIsLOBSTER.php
