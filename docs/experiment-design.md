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
E5: same-class noisy neighbor (tenant layer). E6: same-tenant mixed class (class layer). E7: both at once (hierarchy is complementary).

**RQ3 — Can tenant- and class-aware admission protect interactive SLOs with only gateway-visible signals?**  
Token-aware global \(C_g(t)\) decides how much backend capacity is safe. Static nested budgets decide who may consume it. No RL, no WFQ in v1.

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

Contribution (E5–E7):

```
Token-aware global controller
          │
          │  determines backend-safe capacity
          ↓
        Cg(t)
          │
     ┌────┴────┐
     │         │
 Tenant A    Tenant B
   Ct=A        Ct=B
     │
 ┌───┴────┐
short    long
C_{t,short}  C_{t,long}
          ↘    ↙
        Bedrock
```

**Core sentence:** the global controller decides how much capacity is safe; hierarchical admission decides who is allowed to consume it.

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

Keep E1–E4 classes so new runs are comparable. Do not invent a third length for E5–E7.

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

Isolation budgets for E5–E7 are derived from \(C^*\), not from a generic \(C_{global}=4\). v1 keeps tenant/class caps **static**; only \(C_g(t)\) is token-aware adaptive.

\[
C_g^{\max}=2,\quad C_A=2,\quad C_B=1
\]

Per-(tenant, class) for the hierarchical policy (E7 example):

\[
C_{A,\mathrm{short}}=2,\; C_{A,\mathrm{long}}=1,\quad C_{B,\mathrm{short}}=1,\; C_{B,\mathrm{long}}=1
\]

Class-only uses a **global** class pool \(C_{\mathrm{short}}=2,\; C_{\mathrm{long}}=1\) so it cannot see tenants. Two slots is the smallest split that can isolate a noisy neighbor when \(C^*=1\). \(C_{global}=4\) would overshoot this backend.

## Admission (v1, no RL)

Global capacity from E4:

\[
C_g(t) = \mathrm{TokenAwareController}
\]

Static isolation budgets \(C_t\) and \(C_{t,c}\). Admit iff all enabled layers pass:

\[
\mathrm{admit}(i)
=
[I_g < C_g(t)]
\;\land\;
[I_t < C_t]
\;\land\;
[I_{t,c} < C_{t,c}]
\]

Counters: `inflight_global`, `inflight[tenant]`, `inflight[(tenant, class)]`. Class-only is the exception: it uses a shared `inflight[class]` so it cannot distinguish tenants (E5 negative control). Reject does not count as goodput.

E5–E7 policies all use **token-aware** \(C_g(t)\) inside \([C_{\min}, C_g^{\max}]\). They differ only in which isolation layers are on.

| Policy | \(C_g(t)\) token-aware | Tenant cap | Class cap |
|---|---|---|---|
| Global Token | yes | — | — |
| Class-only Token | yes | — | global class pool |
| Tenant-only Token | yes | \(C_t\) | — |
| Hierarchical Token | yes | \(C_t\) | \(C_{t,c}\) |

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

## RQ2 / RQ3 — E5 / E6 / E7 (ran)

Do **not** cite `results/e5_noisy_neighbor/` or `results/e6_mixed_class/` from the first nested-admission campaign: those bound Tenant A=short to Tenant B=long, and isolation cells used static `tenant_admit` rather than token-aware \(C_g(t)\). New result dirs: `e5_tenant_isolation/`, `e6_class_isolation/`, `e7_joint_interference/`. Old `experiments/e5_quota_pressure.yaml` stays retired.

Each E5–E7 experiment changes **one** interference dimension. Policies on a rep share a seeded arrival trace. Policy order is interleaved across reps (latin-style `policy_schedules` in the YAML) so opaque Bedrock drift is not aliased to one cell.

The 5-rep E5/E6 campaign used a wait queue (`queue_max=16`, `queue_timeout=2s`). Cap-full policies reject immediately (`tenant_full` / `class_full`), so part of Global vs cap-only is a **queue-vs-reject artifact**. P0 control ran (`e5_overflow_reject/`, `e6_overflow_reject/`): same workloads, `overflow_mode=reject`. Both mean orderings hold; E6 Class-only \(>\) Tenant-only is 3/3, E5 Tenant-only \(>\) Class-only is 2/3 and the gap collapses. E1–E4 keep the queue. Do not retune isolation budgets.

### E5 — Tenant noisy-neighbor isolation

Both tenants are **short**. Class-only cannot see A vs B.

| Tenant | Class | Offer | SLO |
|---|---|---|---|
| A | short | always on \(0.5 R_{\mathrm{ref}}\) | TTFT 576 ms |
| B | short | burst, then off | TTFT 576 ms |

| Phase | Time | A | B |
|---|---|---|---|
| P1 | 0–120s | \(0.5 R_{\mathrm{ref}}\) short | 0 |
| P2 | 120–300s | \(0.5 R_{\mathrm{ref}}\) short | \(0.9 R_{\mathrm{ref}}\) short |
| P3 | 300–420s | \(0.5 R_{\mathrm{ref}}\) short | 0 |

If P2 interference is too weak, add a \(1.2 R_{\mathrm{ref}}\) sensitivity. Policies: Global Token, Class-only Token, Tenant-only Token, Hierarchical Token. 5 reps.

**Expected:** Global Token bad for A; Class-only \(\approx\) Global; Tenant-only protects A; Hierarchical \(\approx\) Tenant-only. That is: **tenant layer is necessary**.

**Primary metric:** \(G_A^{\mathrm{short}}\). Also A short SLO attainment, A P95 TTFT, B completion rate, reject(A)/reject(B), recovery after B leaves, total goodput, Bedrock 429. Do not rank on aggregate goodput.

### E6 — Class isolation (same tenant)

One tenant. Tenant-only cannot split short vs long.

| Phase | Time | Mix |
|---|---|---|
| P1 | 0–120s | 100% short, \(0.5 R_{\mathrm{ref}}\) |
| P2 | 120–300s | 70% short / 30% long, \(0.9 R_{\mathrm{ref}}\) |
| P3 | 300–420s | 100% short, \(0.5 R_{\mathrm{ref}}\) |

Policies: Global Token, Tenant-only Token, Class-only Token, Hierarchical Token. 5 reps.

**Expected:** Tenant-only \(\approx\) Global Token; Class-only and Hierarchical protect short. That is: **class layer is necessary**. Tenant isolation does not solve same-tenant class interference.

**Primary metric:** \(G_{\mathrm{short}}\). Also short P95 TTFT, long completion rate, reject by class, recovery, total goodput, Bedrock 429.

### E7 — Joint interference (closing experiment)

Two tenants, each mixed. This is where tenant \(\times\) class happen together.

| Phase | A | B |
|---|---|---|
| P1 0–120s | \(0.5 R_{\mathrm{ref}}\), 100% short | 0 |
| P2 120–300s | \(0.5 R_{\mathrm{ref}}\), 80% short / 20% long | \(0.7 R_{\mathrm{ref}}\), 50/50 |
| P3 300–420s | \(0.5 R_{\mathrm{ref}}\), 100% short | 0 |

Policies: Tenant-only Token, Class-only Token, Hierarchical Token. 3 reps; optional `--reps 5` on the same YAML. Do not retune the mix to enlarge the hierarchical gap.

**Expected:** \(G_A^{\mathrm{short}}\) satisfies Hierarchical \(>\) Tenant-only and Hierarchical \(>\) Class-only. Watch \(G_B\) so the win is not “protect A by refusing all of B.” That is: **tenant and class controls are complementary**.

**Primary metric:** \(G_{A,\mathrm{short}}\), plus \(G_B\), rejects by tenant/class, Bedrock 429.

## Retired / relocated

| Old | Status |
|---|---|
| Quota-pressure E5 | Out. `results/e5_quota_pressure/` do not cite. |
| Controller ablation (`results/e6_ablation/`) | RQ1 appendix. Token / TTFT ablations. **Not** paper E7. Optional later (−demand-gate, 5 reps). |
| First nested E5/E6 (`e5_noisy_neighbor/`, `e6_mixed_class/`) | Do not cite. A=short/B=long confound; isolation used static `tenant_admit`. |
| E5/E6 overflow control (`e5_overflow_reject/`, `e6_overflow_reject/`) | P0. Same workloads, immediate reject. 3 reps. **Ran.** |

## Metrics

Gateway `/metrics` (existing) plus E5–E7 labels `tenant`, `class`:

- `llm_offered_rps`, `llm_achieved_rps`, `llm_slo_goodput_rps` (also per tenant/class)
- `llm_inflight_requests`, `llm_concurrency_limit`, `llm_queue_depth`
- `llm_ttft_seconds`, `llm_request_latency_seconds`
- `llm_throttle_total`, `llm_error_total`
- `bedrock_rpm_quota`, `bedrock_tpm_quota`, `bedrock_tpd_quota` (static, never control)

Per-request JSONL is the source of truth. Required fields: `tenant_id`, `class`, `slo_ms` (per-class), `slo_met`, `c_global`, `c_tenant`, `c_class`, `c_tenant_class`. Summaries expose `by_tenant`, `by_class`, `by_tenant_class`, `reject_by_reason`.

Paper figures: 5–10 s rolling windows. Do not plot raw 1 s `achieved_rps`.

## Findings the campaign is built to support

1. Global usable \(C\) is workload-dependent (E1+E2).
2. Adaptive global \(C\) helps under demand bursts (E3).
3. Request-count \(C\) fails under token-size shifts (E4).
4. Same-class multi-tenant sharing needs a tenant layer (E5).
5. Same-tenant mixed class needs a class layer (E6).
6. Tenant and class controls are complementary under joint interference (E7).
