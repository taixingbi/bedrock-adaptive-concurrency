# Policy comparison factors

Hold workload and environment fixed; vary only the routing / orchestration policy.

## Fixed

- Concurrency \(= C\)
- Request mix
- Prompt / output token distribution
- Test duration
- Model
- Region

## Environment

- Provider default RPM quota
- Provider default TPM quota
- Provider default capacity

## Variable

- Routing / orchestration policy

## Evaluation
- TTFT
- E2E latency
- SLO goodput
- 429 / error rate

- Queue length over time
- In-flight requests
- Current concurrency limit
