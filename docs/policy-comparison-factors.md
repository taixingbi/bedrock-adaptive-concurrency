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

- Admission policy: global token-aware vs class-only vs tenant-only vs hierarchical (all share token-aware \(C_g(t)\))

## Evaluation

- Per-tenant-class SLO-goodput \(G_A^{\mathrm{short}}\) (primary for E5/E7)
- Per-class SLO-goodput \(G_{\mathrm{short}}\) (primary for E6)
- Rejection rate by tenant and class (and \(G_B\), so isolation is not refuse-all-B)
- Fairness and recovery time
- Aggregate SLO-goodput (secondary)
- Bedrock 429 / error rate
- Queue length, inflight, \(C(t)\)
