# Paper 9 experiment design (locked)

**Topic:** Multi-Tenant and Class-Aware Admission Control for Opaque Managed LLM APIs  
**Provider:** Amazon Bedrock  
**Model:** Llama 4 Maverick (`us.meta.llama4-maverick-17b-instruct-v1:0`, US geo inference)  
**Setting:** opaque backend — no GPU, KV-cache, or provider-scheduler telemetry. Gateway-visible signals only (queue, inflight \(C\), TTFT, 429, token occupancy \(W_t\)).

Do **not** adjust RPM/TPM quota. Quota is static context only. Do **not** rerun E1–E4.

## Questions (compressed)

**RQ1 — Why is global concurrency insufficient?**  
E1–E4. Fixed \(C\) is load-dependent; demand-gated AIMD helps under bursts; request-count \(C\) fails when token size shifts at constant RPS.

**RQ2 — How do tenant and class interference show up on a managed LLM gateway?**  
New E5 (noisy neighbor) and new E6 (same tenant, mixed classes). Tenant isolation and workload-class isolation are different problems.

**RQ3 — Can tenant- and class-aware admission protect interactive SLOs with only gateway-visible signals?**  
Nested budgets \(C_{global}\), \(C_t\), \(C_{t,c}\). No RL, no WFQ in v1.

## Architecture

Characterization (E1–E4, already run):

```
Open-loop Load Generator
        ↓
    LLM Gateway
        ↓
Adaptive global C controller
        ↓
Amazon Bedrock (direct ConverseStream)
        ↓
Llama 4 Maverick
```

Contribution (new E5/E6):

```
             Gateway
                ↓
        tenant admission
          ↙           ↘
      Tenant A      Tenant B
          ↓            ↓
       short         long
          ↓            ↓
       C_A(t)        C_B(t)
          ↘            ↙
          global budget
                ↓
             Bedrock
```

The paper gateway calls Bedrock directly. It does **not** proxy through `bedrock-inference-mvp`. Putting Lambda on the path would mix Lambda concurrency into \(C_{knee}\).

Streaming is confirmed. TTFT is time from gateway arrival to first stream token (includes queue wait). Overflow is rejected and does not count as goodput.

## Quota vs runtime (do not collapse these)

Published Llama 4 Maverick defaults (per account, per region, US geo / CRIS):

| Quota | Default | Adjustable |
|---|---|---|
| Cross-region TPM (input + output) | 600,000 | Yes |
| Cross-region RPM | 800 | No |
| Tokens per day (cross-region, doubled) | 432,000,000 | No |

These are **static context**, not the control variable.

**Forbidden control law:** `TPM > 80% quota → decrease C`.

Hard RPS envelopes (not the paper controller):

- RPM cap: \(800 / 60 = 13.33\) RPS
- `short` (512+128=640 tok): RPM binds at 13.33 RPS
- `long` (4096+512=4608 tok): TPM binds at 2.17 RPS

E1–E4 stay well below the RPM cliff. Retired quota-pressure E5 (`results/e5_quota_pressure/`) measured gateway \(C=1\) shedding, not Bedrock quota. Do not rerun. Do not cite.

## Workloads / classes

Keep E1–E4 classes so new runs are comparable. Do not invent a third length for E5/E6.

| Class | Role | Input | Output | Stream | Temperature | SLO |
|---|---|---|---|---|---|---|
| `short` | interactive | ~512 | ~128 | yes | 0 | TTFT \(\le 576\) ms |
| `long` | heavy / batch | ~4096 | ~512 | yes | 0 | TTFT \(\le 769\) ms |

Production can use per-class SLOs. Characterization E1 still uses **one** class (short) so \(C\) is not confounded with length.

## Derived parameters (from E1, not guessed)

This account: \(C^*=1\) (best **observed** operating point on short, not “Bedrock knee must be 1”), \(R_{knee}\approx 1.84\) rps, interactive SLO \(= 576\) ms, long SLO \(= 769\) ms (`results/e1_long_scout/`: \(C=1\) long P95 TTFT 513 ms \(\times 1.5\)). Long E2E P95 is ~2.9 s; the SLO is still TTFT.

- Controller window = 5s, \(C \leftarrow C+1\) or \(C \leftarrow \max(C_{min}, 0.7C)\).
- Demand gate: increase only if backend TTFT is healthy **and** the current \(C\) is pressed (waiters, or queue-wait P95 \(\ge 5\) ms).
- Control uses **backend** TTFT. User-facing TTFT remains the goodput SLO.

Isolation budgets for E5/E6 are derived from \(C^*\), not from a generic \(C_{global}=4\):

\[
C_{global} = 2,\quad C_A^{\max}=2,\quad C_B^{\max}=1,\quad C_{short}^{\max}=2,\quad C_{long}^{\max}=1
\]

Two slots is the smallest split that can isolate a noisy neighbor when \(C^*=1\). \(C_{global}=4\) would overshoot this backend.

## Admission (v1, no RL)

Admit iff all that apply for the selected policy:

\[
\mathrm{inflight}_{global} < C_{global}
\quad\land\quad
\mathrm{inflight}_{t} < C_{t}
\quad\land\quad
\mathrm{inflight}_{t,c} < C_{t,c}
\]

Reject does not count as goodput. Policies below enable a subset of these caps. Global AIMD still adapts \(C_{global}(t)\) inside \([C_{min}, C_{max}]\) when the policy is adaptive; tenant/class caps stay static in v1.

| Policy | Caps |
|---|---|
| Global Fixed | \(C_{global}=2\) |
| Global Request-AIMD | demand-gated SLO-AIMD on \(C_{global}\) |
| Global Token-Aware | token SLO-AIMD on \(C_{global}\) |
| Tenant-only | \(C_{global}\) + \(C_A,C_B\) |
| Class-aware | \(C_{global}\) + \(C_{short},C_{long}\) |
| Tenant + class | all three nested |

## RQ1 — E1–E4 (done, do not rerun)

Canonical traces: `results/e1_pilot/`, `e2_light_load/`, `e3_dynamic_load_v2/`, `e4_token_shift_v2/`. Claims: `results/SUMMARY.md`.

### E1 — Concurrency characterization

Fixed `short`. Closed-loop sweep \(C\). This account used cheap scout \(C\in\{1,2,4,8\}\), 1 rep. Output: \(C^*\), \(R_{knee}\), interactive SLO. Optional later: C=1,2,4 × 3–5 reps. Do not run `e1_sweep` (16/32/64).

Write **best observed operating point \(C^*=1\)**, not “true Bedrock knee equals 1”.

### E2 — Light-load sanity

Offered \(0.5 R_{knee}\). Not a ranking. Fixed-1 vs Fixed-2 vs SLO-AIMD. Pass: goodput/TTFT match Fixed-1, Bedrock 429 = 0, adaptive \(C\) does not climb. Also shows \(C=2\) is fine under light load — usable \(C\) is load-dependent.

### E3 — Dynamic load / burst

Fixed-1 vs Gradient vs SLO-AIMD. Short only.

| Phase | Time | Offered |
|---|---|---|
| P1 | 0–120s | \(0.5 R_{knee}\) |
| P2 | 120–240s | \(0.9 R_{knee}\) |
| P3 | 240–300s | \(1.5 R_{knee}\) burst |
| P4 | 300–420s | \(0.6 R_{knee}\) recovery |

### E4 — Token-demand shift

RPS held at \(0.9 R_{knee}\). SLO-AIMD vs token-aware.

| Phase | Time | Workload |
|---|---|---|
| P1 | 0–180s | short |
| P2 | 180–300s | long |
| P3 | 300–480s | short recovery |

Token occupancy:

\[
W_t = \sum_{i \in \mathrm{inflight}} \bigl(\mathrm{inputTokens}_i + \lambda \cdot \widehat{\mathrm{outputTokens}}_i\bigr)
\]

## RQ2 / RQ3 — new E5 / E6

Gateway nested limiter is implemented (`admit_caps` = global / tenant / class). Harness expands `e5_noisy_neighbor.yaml` and `e6_mixed_class.yaml`. Mock first: `experiments/dryrun_tenants.yaml`. Old `experiments/e5_quota_pressure.yaml` stays retired.

### E5 — Multi-tenant noisy neighbor

Two tenants, one Bedrock backend.

| Tenant | Class | Offer | SLO |
|---|---|---|---|
| A | short (interactive) | always on | TTFT 576 ms |
| B | long (heavy) | burst, then off | TTFT 769 ms |

| Phase | Time | A | B |
|---|---|---|---|
| P1 | 0–120s | \(0.5 R_{knee}\) short | 0 |
| P2 | 120–300s | \(0.5 R_{knee}\) short | \(0.9 R_{knee}\) long |
| P3 | 300–420s | \(0.5 R_{knee}\) short | 0 |

Policies: Global Fixed, Global Request-AIMD, Global Token-Aware, Tenant-only, Class-aware, Tenant+class. 5 reps.

**Primary metrics — not aggregate goodput alone:**

\[
G_A,\ G_B
\]

plus A P95 TTFT, B completion rate, reject rate by tenant/class, global goodput, fairness (\(G_A\) vs \(G_B\)), A recovery time after B stops, Bedrock 429.

Pass for Tenant+class: during P2, \(G_A\) stays near P1; Global Fixed / Request-AIMD let B crush A.

### E6 — Same tenant, mixed classes

One tenant. Mix short+long so a reviewer cannot say “tenant isolation was enough.”

| Phase | Time | Mix |
|---|---|---|
| P1 | 0–120s | short only, \(0.5 R_{knee}\) |
| P2 | 120–300s | 70% short / 30% long, total \(0.9 R_{knee}\) |
| P3 | 300–420s | short only, \(0.5 R_{knee}\) |

Policies: Tenant-only vs Tenant+class (Global Token-Aware as a third cell if budget allows). 5 reps.

If tenant-only still lets long drag short, and class-aware restores short \(G\) / P95, then tenant isolation and workload isolation are distinct.

## Retired / relocated

| Old | Status |
|---|---|
| Quota-pressure E5 | Out. `results/e5_quota_pressure/` do not cite. |
| Controller ablation (`results/e6_ablation/`) | Relabeled **E7 traces**. Token / TTFT ablations still support RQ1. Not the new paper E6. Optional rerun later (−demand-gate, 5 reps). |

## Metrics

Gateway `/metrics` (existing) plus E5/E6 labels `tenant`, `class`:

- `llm_offered_rps`, `llm_achieved_rps`, `llm_slo_goodput_rps` (also per tenant/class)
- `llm_inflight_requests`, `llm_concurrency_limit`, `llm_queue_depth`
- `llm_ttft_seconds`, `llm_request_latency_seconds`
- `llm_throttle_total`, `llm_error_total`
- `bedrock_rpm_quota`, `bedrock_tpm_quota`, `bedrock_tpd_quota` (static, never control)

Per-request JSONL is the source of truth. New required fields: `tenant_id`, `class`, `slo_ms` (per-class), `slo_met`, `c_global`, `c_tenant`, `c_class`.

Paper figures: 5–10 s rolling windows. Do not plot raw 1 s `achieved_rps`.

## Findings the campaign is built to support

1. Global usable \(C\) is workload-dependent (E1+E2).
2. Adaptive global \(C\) helps under demand bursts (E3).
3. Request-count \(C\) fails under token-size shifts (E4).
4. Multi-tenant sharing creates noisy-neighbor interference on an opaque backend (new E5).
5. Tenant isolation ≠ class isolation; nested admission protects interactive SLOs without GPU telemetry (new E5+E6).
