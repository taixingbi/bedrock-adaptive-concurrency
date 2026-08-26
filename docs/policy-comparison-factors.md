# Policy comparison factors

Hold workload, tenants, and environment fixed; vary only the admission / concurrency policy.

## Fixed

- Model and region
- Request mix per phase
- Prompt / output token distribution per class
- Test duration
- Per-class SLO
- Isolation caps \(C_{global}\), \(C_t\), \(C_{t,c}\) when the policy uses them

## Environment

- Provider default RPM quota
- Provider default TPM quota
- Provider default capacity (opaque)

## Variable

- Admission policy: global fixed / request-AIMD / token-aware vs tenant-only vs class-aware vs tenant+class

## Evaluation

- Per-tenant SLO-goodput \(G_A, G_B\) (primary for E5/E6)
- Per-class TTFT / E2E
- Rejection rate by tenant and class
- Fairness and recovery time
- Aggregate SLO-goodput (secondary)
- Bedrock 429 / error rate
- Queue length, inflight, \(C(t)\)
