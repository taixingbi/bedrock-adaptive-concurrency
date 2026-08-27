# Results claims (locked)

Campaign index for RQ1 (E1–E4) and RQ2/RQ3 (new E5/E6). Per-request JSONL is the source of truth. Each `summary.json` is one row per cell×rep — it does not store means, medians, or phase splits.

Design: [docs/experiment-design.md](../docs/experiment-design.md). Do not rerun E1–E4.

Derived knobs (from `results/e1_pilot/` and `results/e1_long_scout/`, do not re-guess): \(C^*=1\) (best observed point), \(R_{knee}\approx 1.84\) rps, interactive TTFT SLO \(= 576\) ms, **long TTFT SLO \(= 769\) ms**. Controller uses **backend** TTFT; user-facing TTFT is the goodput SLO. Gateway HTTP 429s in logs are `queue_timeout`, not provider throttle.

## Canonical vs do-not-cite

| Use | Dir | Why |
|---|---|---|
| E1 knobs | `e1_pilot/` | Cheap C=1,2,4,8 scout. Do not run `e1_sweep`. |
| E1 long SLO | `e1_long_scout/` | C=1 long; SLO_long = 769 ms. |
| E2 sanity | `e2_light_load/` | Demand-gated SLO-AIMD. |
| E3 main | `e3_dynamic_load_v2/` | Backend-TTFT + demand gate, 5 reps. |
| E4 novelty | `e4_token_shift_v2/` | Keep token-aware. RQ1. |
| E7 traces (old ablation) | `e6_ablation/` | Global token/TTFT ablation. **Not** the new paper E6. |
| ignore | `e2_static_vs_adaptive/`, `e2_pilot/` | Vacant-\(C\) climb under light load. |
| ignore | `e3_dynamic_load/` | Vacant \(C\approx 20\). Do **not** claim that run’s P95 cut. |
| ignore | `e4_token_shift/` | Same vacant-\(C\) controller. |
| retired | `e5_quota_pressure/` | Gateway \(C=1\) overload, not quota. Do not cite. |
| E5 noisy neighbor | `e5_noisy_neighbor/` | RQ2. 6 cells × 5 reps. |
| E6 mixed class | `e6_mixed_class/` | RQ2/RQ3. 3 cells × 5 reps. |
| ignore | `dryrun/`, `dryrun_tenants/`, `local/` | Mock / smoke. |

## E1 — knee (`e1_pilot/`, 1 rep, closed-loop)

| \(C\) | Throughput | SLO-goodput | TTFT P95 | Bedrock 429 |
|---|---:|---:|---:|---:|
| 1 | 1.84 | 1.84 | 384 ms | 0 |
| 2 | 1.30 | 1.04 | 3181 ms | 1 |
| 4 | 1.25 | 0.90 | 9381 ms | 6 |
| 8 | 1.25 | 0.81 | 8282 ms | 31 |

**Claim:** Maverick has a concurrency knee at \(C=1\). Extra in-flight cuts goodput and blows the tail. Those 429s are runtime congestion, not the 800 RPM cliff (C=1 is ~110 RPM).

### E1 long scout (`e1_long_scout/`, C=1, 1 rep)

Same formula as short: SLO \(= 1.5 \times\) P95 TTFT. 35 measure requests, 0 Bedrock 429s.

| | Throughput | TTFT P50 / P95 | E2E P95 | SLO |
|---|---:|---:|---:|---:|
| long \(C=1\) | 0.39 rps | 402 / 513 ms | 2894 ms | **769 ms** |

TTFT only rises ~130 ms vs short. The long cost is occupancy / E2E (~2.9 s), not first-token. Do not use 3000 ms.

## E2 — light-load sanity (`e2_light_load/`, 5 reps, \(0.5 R_{knee}\))

| Policy | SLO-goodput | TTFT P95 | Mean \(C\) | Bedrock 429 |
|---|---:|---:|---:|---:|
| Fixed-1 | 0.911 | 434 ms | 1.00 | 0 |
| Fixed-2 | 0.913 | 377 ms | 2.00 | 0 |
| SLO-AIMD | 0.892 | 468 ms | 1.00 | 0 |

**Claim:** not a ranking. Revised SLO-AIMD stays at \(C=1\), matches Fixed-1, zero Bedrock 429s. Pass.

## E3 — dynamic load (`e3_dynamic_load_v2/`, 5 reps, 420 s)

Whole-run means:

| Policy | SLO-goodput | vs Fixed | TTFT P95 | Bedrock 429 /rep | Mean \(C\) |
|---|---:|---:|---:|---:|---:|
| Fixed-1 | 1.038 | — | 2173 ms | 0.0 | 1.00 |
| Gradient | 1.173 | +13% | 2306 ms | 1.2 | 2.77 |
| **SLO-AIMD** | **1.199** | **+15.5%** | 2140 ms | **0.4** | **1.38** |

Phase SLO-goodput (arrival-time split; P3 = 240–300 s at \(1.5 R_{knee}\)):

| Policy | P1 0.5× | P2 0.9× | **P3 burst** | P4 0.6× |
|---|---:|---:|---:|---:|
| Fixed-1 | 0.917 | 1.622 | **0.127** | 1.032 |
| Gradient | 0.915 | 1.617 | 1.117 | 1.012 |
| SLO-AIMD | 0.917 | 1.630 | **1.243** | 1.023 |

**Claim:** adaptive \(C\) beats a knee-static cap under burst. The win is P3 (~10× Fixed goodput). Whole-run P95 is a wash (~2.1–2.3 s) because the burst tail dominates; \(C\) only reaches 2–3. Do not claim a P95 reduction from this rerun.

## E4 — token shift (`e4_token_shift_v2/`, 5 reps, 480 s, RPS held at \(0.9 R_{knee}\))

Whole-run:

| Policy | SLO-goodput mean (median) | TTFT P50 | TTFT P95 | Mean \(C\) |
|---|---:|---:|---:|---:|
| SLO-AIMD | 0.321 (0.228) | 1532 ms | 2983 ms | 2.07 |
| **Token SLO-AIMD** | **0.809 (0.831)** | **304 ms** | 2466 ms | 1.87 |

Mean goodput **+152%** (median **+264%**). SLO-AIMD rep 1 is an outlier (0.895); use median.

Phase:

| Policy | P1 short | P2 long | P3 short |
|---|---|---|---|
| SLO-AIMD | goodput 0.40, \(C\to 2.6\) | goodput 0.48, \(C\to 6.4\) | goodput **0.14**, wrecked |
| Token | goodput 0.56 | goodput **0**, \(C=1\), ~148 rejects | goodput **1.60**, 98% attainment, P95 **432 ms** |

Recovery after long→short (\(t\ge 300\)): first 3 consecutive 1 s windows with user TTFT P95 \(\le\) SLO. Token: **16.8 s**, 5/5. SLO-AIMD: 3/5 (6.8 / 11.8 / 76.5 s); **2/5 never**. Violation windows (TTFT P95 > SLO): **252 s vs 410 s**.

**Claim:** keep token-aware as core novelty. Win is **P3 recovery**, not P2 goodput: token pins \(C=1\) via `decrease-token` (\(W_t=4608\)), discards longs, then short recovers. SLO-AIMD raises \(C\) to 6–7 on long occupancy and poisons P3. Offered TPM is below the 600k quota — occupancy, not `TPM/quota`.

## E7 — controller ablation (`e6_ablation/`, 3 reps, same workload as E4)

YAML that ran: full, −token, −TTFT, −throttle, −MD. Spec wanted −demand-gate; **that cell was not run.**

| Cell | SLO-goodput mean (median) | vs full | Notes |
|---|---:|---:|---|
| Full | 0.946 (0.824) | — | P2 \(C=1\), P3 goodput 1.58. Reps 2–3 match E4 token-aware. Rep 1 is hot (1.201). |
| **− token** | **0.256 (0.195)** | **−73%** | P2 \(C\to 7\), P3 goodput 0.14. Only material ablation. |
| − TTFT | 0.760 (0.822) | P3 still 1.57 | P1 \(C\to 6\); **12.7 Bedrock 429s/rep**. |
| − throttle | 0.837 (0.836) | ~0 | Null: provider 429s already ~0. |
| − MD | 0.877 (0.885) | ~0 | Unidentifiable: at \(C\in\{1,2,3\}\), \(0.7C \equiv C-1\). |

**Claim:** token term is the ablation that matters. −TTFT shows TTFT still needed to avoid Bedrock 429s on short. Do not over-claim −MD or −throttle. Optional later cell: −demand-gate (E2 already showed vacant-\(C\) climb without it).

## E5 — noisy neighbor (`e5_noisy_neighbor/`, 5 reps, 420 s)

Two tenants, one backend. A = short @ \(0.5 R_{knee}\) always; B = long @ \(0.9 R_{knee}\) in P2 (120–300 s). Bedrock 429 = 0 all cells. Primary metrics \(G_A, G_B\), not aggregate goodput.

| Policy | \(G_A\) | \(G_B\) | P95 TTFT | Aggregate goodput |
|---|---:|---:|---:|---:|
| Global Fixed | 0.518 | 0.011 | 2211 ms | 0.523 |
| Global SLO-AIMD | 0.519 | 0.011 | 2194 ms | 0.523 |
| Global Token | 0.518 | 0.011 | 2210 ms | 0.522 |
| Tenant-only | **0.916** | **0.366** | **388 ms** | 1.075 |
| Class-only | **0.914** | **0.364** | **386 ms** | 1.071 |
| Tenant+class | **0.917** | **0.366** | **391 ms** | 1.075 |

**Claim:** a shared global \(C\) lets the heavy tenant crush interactive SLO-goodput (\(G_A\) 0.52, P95 ~2.2 s). Nested caps restore \(G_A\approx 0.92\) and cut P95 to ~390 ms, and also raise \(G_B\) (0.37 vs 0.01) because B is no longer fighting an overloaded shared queue. Tenant-only ≈ class-only ≈ tenant+class on this workload because tenant identity **is** class (A=short, B=long). Do not claim nested extra from E5; that split is E6.

## E6 — mixed class (`e6_mixed_class/`, 5 reps, 420 s)

One tenant. P2 is 70% short / 30% long at \(0.9 R_{knee}\). Bedrock 429 = 0.

| Policy | Short goodput | Long goodput | P95 TTFT | Aggregate |
|---|---:|---:|---:|---:|
| Tenant-only | 0.913 | 0.390 | 387 ms | 1.080 |
| **Tenant+class** | **1.002** | 0.245 | 394 ms | 1.105 |
| Global Token | 0.595 | 0.094 | 2029 ms | 0.635 |

**Claim:** tenant isolation is not enough when one tenant mixes classes. Class cap trades some long goodput (0.39 → 0.25) for short (0.91 → 1.00). Global token-aware without class caps still loses (P95 2.0 s). Tenant isolation and workload isolation are different problems.

## Allowed paper claims

1. Bedrock Llama 4 Maverick has a concurrency knee at \(C=1\) (E1).
2. Best \(C\) moves with offered load; Fixed-1 collapses in the E3 burst.
3. SLO-AIMD (+15.5% whole-run goodput vs Fixed) by raising \(C\) only under demand + healthy backend TTFT.
4. Token demand changes the right \(C\) at constant RPS; token-aware recovers after long→short where request-count AIMD does not (E4, E7 −token).
5. Multi-tenant sharing on an opaque backend is a noisy-neighbor problem; nested caps protect interactive \(G_A\) (E5).
6. Tenant isolation ≠ class isolation; same-tenant short/long mix still needs a class cap (E6).

## Traps

- Do not cite `e3_dynamic_load/` “+19% / −33% P95 / \(C\approx 20\)”.
- Do not claim E3 v2 cut P95 (2140 vs 2173 ms).
- Do not treat gateway `queue_timeout` 429s as Bedrock throttle.
- Do not write `TPM > 80% quota → decrease C`.
- Retired quota E5 does not support a quota-cliff claim.
- `results/e6_ablation/` did not ablate the demand gate. −MD is not identified at this \(C\). It is E7 traces, not the new mixed-class E6.
- E4 / old ablation P2 token-aware goodput is ~0 by design (reject longs). The metric that matters is P3.
- E5 tenant-only ≈ tenant+class because A=short and B=long. Do not sell nested extra from E5.
- E6 primary split is short vs long goodput, not aggregate.

## Recompute

```bash
python - <<'PY'
import json
from collections import defaultdict
from statistics import mean, median
d = json.load(open("results/e3_dynamic_load_v2/summary.json"))
by = defaultdict(list)
for r in d["summaries"]:
    by[r["cell"]].append(r)
for cell, rs in by.items():
    print(cell, "good", mean(x["slo_goodput_rps"] for x in rs),
          "med", median(x["slo_goodput_rps"] for x in rs))
PY
```

Phase splits: bucket `events.jsonl` by `arrival_ts - min(arrival_ts)` using the YAML `until_s` edges (E3: 120/240/300/420; E4/E7: 180/300/480; E5/E6: 120/300/420). Per-tenant / per-class: `summary["by_tenant"]` / `by_class`.
