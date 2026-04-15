# Public Policy-as-Code Demo Pack

This starter pack uses public policy-testing and access-control ideas while we wait on real policy audit trails.

Files:
- `cases/policy_authz_eval_cases.jsonl`

What this pack covers:
- MFA-gated actions
- owner-scope allows
- break-glass review flows
- region boundary routing
- change-window enforcement
- restricted resource roles
- missing-role denials

Primary public source:
- Open Policy Agent policy testing:
  - https://www.openpolicyagent.org/docs/latest/policy-testing/

How to run it:

```powershell
memla policy benchmark-authz `
  --cases cases\policy_authz_eval_cases.jsonl `
  --raw-model qwen3.5:9b `
  --memla-model qwen3.5:9b `
  --raw-provider ollama `
  --raw-base-url http://127.0.0.1:11435 `
  --memla-provider ollama `
  --memla-base-url http://127.0.0.1:11435
```

What this is not:
- real OPA bundles from a customer
- a substitute for policy audit logs or approval histories
- a claim that this pack covers the full expressiveness of Rego or enterprise authorization systems
