# Paper 9 experiment design (locked)

**Topic:** SLO-Aware Adaptive Concurrency Control for Managed LLM APIs  
**Provider:** Amazon Bedrock  
**Model:** Llama 4 Maverick (`us.meta.llama4-maverick-17b-instruct-v1:0`, US geo inference)  
**Control variable:** \(C_t\) = gateway → Bedrock max in-flight requests  

Do **not** adjust RPM/TPM quota. Quota is static context only.

## Question

When Bedrock backend capacity is opaque and both request length and offered load change, how should a gateway adapt concurrency to maximize SLO-compliant goodput?

## Architecture

```
Open-loop Load Generator
        ↓
    LLM Gateway
        ↓
Adaptive Concurrency Controller
        ↓
Amazon Bedrock (direct ConverseStream)
        ↓
Llama 4 Maverick
```

The paper gateway calls Bedrock directly. It does **not** proxy through `bedrock-inference-mvp` (Lambda Function URL). That stack only proves `llama4` streaming works in this account. Putting Lambda on the path would mix Lambda concurrency into \(C_{knee}\).

Streaming is confirmed. TTFT is time from gateway arrival to first stream token (includes queue wait).

When \(C\) is full: bounded queue. Overflow is rejected and does not count as goodput. User-facing TTFT = queue wait + backend TTFT.

## Quota vs runtime (do not collapse these)

Published Llama 4 Maverick defaults (per account, per region, US geo / CRIS):

| Quota | Default | Adjustable |
|---|---|---|
| Cross-region TPM (input + output) | 600,000 | Yes |
| Cross-region RPM | 800 | No |
| Tokens per day (cross-region, doubled) | 432,000,000 | No |

These are **static context**, not the control variable.

| Signal | Role |
|---|---|
| `bedrock_rpm_quota` = 800 | Static upper bound. Exposed, never used as a control law. |
| `bedrock_tpm_quota` = 600000 | Static upper bound. Exposed, never used as a control law. |
| `bedrock_tpd_quota` = 432000000 | Daily ceiling. Not binding for a single E1–E6 run. |
| Throughput, TTFT, 429, tokens | Runtime observations. |
| \(C\) | Controller output. |

**Forbidden control law:** `TPM > 80% quota → decrease C`.

Hard RPS envelopes (do not treat as the paper controller):

- RPM cap: \(800 / 60 = 13.33\) RPS
- `short` (512+128=640 tok): TPM cap \(600000 / (640 \times 60) = 15.63\) RPS → **RPM binds** at 13.33 RPS
- `long` (4096+512=4608 tok): TPM cap \(600000 / (4608 \times 60) = 2.17\) RPS → **TPM binds** at 2.17 RPS

That gap is why E4 exists: an RPS that is safe on `short` can be several times the `long` TPM cap.

- E1–E3: stay \(\le 0.75 \times 13.33 \approx 10\) RPS unless \(R_{knee}\) is lower. If E1 starts returning 429s at high \(C\), stop the sweep and treat that as the quota cliff, not \(C_{knee}\).
- E3 \(1.5 R_{knee}\): if that exceeds 13.33 RPS, the burst overlaps E5; record it, do not hide the 429s.
- E4: keep constant \(0.9 R_{knee}\). The long phase will typically exceed 600k TPM; token-aware \(W_t\) should drop \(C\) from token pressure, not from `TPM/quota`.
- E5: \(1.0\times\) = quota envelope for `short` (13.33 RPS), not \(R_{knee}\). This is the only experiment that aims at the cliff.

## Workloads

| Class | Input | Output | Stream | Temperature |
|---|---|---|---|---|
| `short` | ~512 tokens | ~128 tokens | yes | 0 |
| `long` | ~4096 tokens | ~512 tokens | yes | 0 |

## Derived parameters (from E1, not guessed)

- \(C_{knee}\): throughput begins to plateau **and** TTFT / E2E tail rises.
- \(R_{knee}\): sustainable achieved RPS at \(C_{knee}\).
- TTFT SLO: \(1.5 \times\) P95 TTFT at \(C_{knee}\) on `short`.
- Fixed-Low = \(\max(1, \lfloor C_{knee}/2 \rfloor)\); Fixed-Knee = \(C_{knee}\); Fixed-High = \(2 C_{knee}\).
- Controller: \(C_{min}=1\), \(C_{max}=\max(64, 2C_{knee})\), window = 5s, \(C \leftarrow C+1\) or \(C \leftarrow \max(C_{min}, 0.7C)\).

## E1 — Concurrency characterization

Prove adaptive concurrency is necessary.

- Fixed `short` workload.
- Sweep \(C \in \{1,2,4,8,16,32,64\}\). If unsaturated, keep doubling.
- Saturate each \(C\) (closed-loop \(C\) workers).
- 60s warm-up, 180s measure, 5 repetitions.
- Record: throughput, SLO-goodput, TTFT P50/P95/P99, E2E P95/P99, 429, 5xx, token throughput.
- Output: \(C_{knee}\), \(R_{knee}\), SLO. **E1 before E2–E6.**

## E2 — Static vs adaptive (main comparison)

Same open-loop offered rate \(0.9 R_{knee}\) (stay off E5):

| Policy | Behavior |
|---|---|
| Fixed-Low | Conservative static \(C\) |
| Fixed-Knee | Best static \(C\) from E1 |
| Fixed-High | Aggressive static \(C\) |
| Retry/Backoff | High \(C\) + exponential backoff on 429/5xx; \(C\) does not adapt |
| Generic Gradient | Adapt \(C\) from TTFT-P95 gradient, not an absolute SLO |
| SLO-AIMD | Paper controller |

SLO-AIMD, every 5 seconds:

```
if TTFT P95 < SLO and throttle/error rate low:
    C = C + 1
if TTFT P95 > SLO or throttling occurs:
    C = 0.7 × C
```

Prefer decrease when both could apply.

**Primary metric:**

\[
\mathrm{Goodput} = \frac{\#\{\text{successful requests meeting SLO}\}}{\text{time}}
\]

## E3 — Dynamic load / burst

Open-loop RPS, `short` workload:

| Time | Offered RPS |
|---|---|
| 0–120s | \(0.5 R_{knee}\) |
| 120–240s | \(0.9 R_{knee}\) |
| 240–300s | \(1.5 R_{knee}\) |
| 300–420s | \(0.6 R_{knee}\) |

Time series: offered/achieved RPS, \(C(t)\), in-flight, TTFT P95, latency P95, goodput, 429, queue delay.

Derived: adaptation time, recovery time, SLO-violation duration, overshoot, goodput.

## E4 — Token-demand shift (novelty)

RPS held at \(0.9 R_{knee}\) (request count unchanged, token demand changes):

| Time | Workload |
|---|---|
| 0–180s | 512 / 128 |
| 180–300s | 4096 / 512 |
| 300–480s | 512 / 128 |

Compare SLO-AIMD vs token-aware SLO-AIMD. Token-aware extra signal:

\[
W_t = \sum_{i \in \mathrm{inflight}} \bigl(\mathrm{inputTokens}_i + \lambda \cdot \widehat{\mathrm{outputTokens}}_i\bigr)
\]

If \(W_t\) is high, hold or decrease even when request-count \(C\) looks fine. Do **not** use quota percentage.

**Finding:** the same RPS is not the same LLM backend pressure.

## E5 — Capacity / quota pressure

Separate section. Sweep offered load at 0.5 / 0.75 / 0.9 / 1.0 / 1.1 / 1.25× sustainable capacity. Record 429, retry amplification, queue growth, TTFT, goodput, adaptive \(C\). This is the only experiment that should aim at the quota cliff.

## E6 — Ablation

Full controller = token-aware SLO-AIMD. Remove:

1. token-awareness (most important)
2. TTFT signal
3. 429/error signal
4. multiplicative decrease (secondary; becomes \(C-1\))

## Metrics

Gateway `/metrics` (Prometheus):

- `llm_offered_rps`, `llm_achieved_rps`
- `llm_input_tokens_per_sec`, `llm_output_tokens_per_sec`
- `llm_inflight_requests`, `llm_concurrency_limit`
- `llm_ttft_seconds`, `llm_request_latency_seconds`
- `llm_throttle_total`, `llm_error_total`
- `llm_slo_goodput_rps`
- `bedrock_rpm_quota`, `bedrock_tpm_quota`, `bedrock_tpd_quota` (static gauges)

Per-request JSONL is the paper source of truth (`queue_ms`, `ttft_ms`, `e2e_ms`, `slo_met`, `c_limit`, `w_t`, …).

## Findings the experiments are built to support

1. Bedrock Llama 4 Maverick has a clear concurrency knee.
2. Best concurrency moves with offered load, so a fixed \(C\) is unstable.
3. SLO-aware adaptive concurrency improves SLO-goodput and cuts tail violations.
4. Token demand changes the best \(C\) even when RPS is constant, so token-aware control fits LLM APIs better than request-count controllers.
