# Results claims (locked)

Campaign index: RQ1 (E1–E4) and RQ2/RQ3 (E5–E7). Per-request JSONL is the source of truth. Each `summary.json` is one row per cell×rep — it does not store means, medians, or phase splits.

Design: [docs/experiment-design.md](../docs/experiment-design.md). Do not rerun E1–E4.

Derived knobs (from `results/e1_pilot/` and `results/e1_long_scout/`, do not re-guess): \(C^*=1\) (best observed point), \(R_{knee}\approx 1.84\) rps, interactive TTFT SLO \(= 576\) ms, **long TTFT SLO \(= 769\) ms**. Controller uses **backend** TTFT; user-facing TTFT is the goodput SLO. Gateway HTTP 429s in logs are `queue_timeout` / `*_full`, not provider throttle.

E5–E7 all sit on the E4 controller \(C_g(t)=\mathrm{TokenAwareController}\). Isolation budgets are static. Primary metrics are per-tenant-class goodput, not aggregate.

## Canonical vs do-not-cite

| Use | Dir | Why |
|---|---|---|
| E1 knobs | `e1_pilot/` | Cheap C=1,2,4,8 scout. Do not run `e1_sweep`. |
| E1 long SLO | `e1_long_scout/` | C=1 long; SLO_long = 769 ms. |
| E2 sanity | `e2_light_load/` | Demand-gated SLO-AIMD. |
| E3 main | `e3_dynamic_load_v2/` | Backend-TTFT + demand gate, 5 reps. |
| E4 novelty | `e4_token_shift_v2/` | Keep token-aware. RQ1. |
| RQ1 ablation | `e6_ablation/` | Token/TTFT ablation. **Not** paper E7. |
| ignore | `e2_static_vs_adaptive/`, `e2_pilot/` | Vacant-\(C\) climb under light load. |
| ignore | `e3_dynamic_load/` | Vacant \(C\approx 20\). Do **not** claim that run’s P95 cut. |
| ignore | `e4_token_shift/` | Same vacant-\(C\) controller. |
| retired | `e5_quota_pressure/` | Gateway \(C=1\) overload, not quota. Do not cite. |
| do not cite | `e5_noisy_neighbor/`, `e6_mixed_class/` | v1: A=short/B=long confound; static `tenant_admit`. |
| E5 tenant isolation | `e5_tenant_isolation/` | Same-class noisy neighbor. 4×5. |
| E6 class isolation | `e6_class_isolation/` | Same-tenant mixed class. 4×5. |
| E7 joint | `e7_joint_interference/` | Tenant × class. 3×3. Optional `--reps 5`. |
| P0 overflow-reject | `e5_overflow_reject/`, `e6_overflow_reject/` | Unified immediate reject. 3 reps. Ran. |
| ignore | `dryrun/`, `dryrun_tenants/`, `dryrun_joint/`, `dryrun_overflow/`, `local/` | Mock / smoke. |

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

## RQ1 ablation — controller (`e6_ablation/`, 3 reps, same workload as E4)

YAML that ran: full, −token, −TTFT, −throttle, −MD. Spec wanted −demand-gate; **that cell was not run.**

| Cell | SLO-goodput mean (median) | vs full | Notes |
|---|---:|---:|---|
| Full | 0.946 (0.824) | — | P2 \(C=1\), P3 goodput 1.58. Reps 2–3 match E4 token-aware. Rep 1 is hot (1.201). |
| **− token** | **0.256 (0.195)** | **−73%** | P2 \(C\to 7\), P3 goodput 0.14. Only material ablation. |
| − TTFT | 0.760 (0.822) | P3 still 1.57 | P1 \(C\to 6\); **12.7 Bedrock 429s/rep**. |
| − throttle | 0.837 (0.836) | ~0 | Null: provider 429s already ~0. |
| − MD | 0.877 (0.885) | ~0 | Unidentifiable: at \(C\in\{1,2,3\}\), \(0.7C \equiv C-1\). |

**Claim:** token term is the ablation that matters. −TTFT shows TTFT still needed to avoid Bedrock 429s on short. Do not over-claim −MD or −throttle. Optional later cell: −demand-gate (E2 already showed vacant-\(C\) climb without it).

## E5 / E6 v1 — do not cite

`results/e5_noisy_neighbor/` and `results/e6_mixed_class/` bound tenant identity to class (A=short, B=long) and ran isolation cells on static `tenant_admit` instead of token-aware \(C_g(t)\). Numbers below are historical only.

E5 v1 isolation vs global: \(G_A\) 0.92 vs 0.52, P95 ~390 ms vs ~2.2 s. Tenant-only ≈ class-only because tenant **was** class. E6 v1 tenant+class vs tenant-only: short 1.00 vs 0.91. Do not use these as the paper E5/E6 claims.

## E5 — tenant isolation (`e5_tenant_isolation/`, 5 reps, 420 s)

A and B both **short**. \(R_A=0.5 R_{\mathrm{ref}}\) always; B bursts at \(0.9 R_{\mathrm{ref}}\) in P2 (120–300 s). All four cells are token-aware \(C_g(t)\). Primary: P2 \(G_A^{\mathrm{short}}\). Gateway 429s in the log are `queue_timeout` / `tenant_full` / `class_full`, not Bedrock (Bedrock 429 \(\le 1.2\)/rep).

P2 (arrival-time split):

| Policy | \(G_A^{\mathrm{short}}\) | A SLO att. | A P95 | \(G_B\) | P2 rejects A / B |
|---|---:|---:|---:|---:|---:|
| Global Token | 0.301 | 0.54 | 3044 ms | 0.557 | 62 / 81 |
| Class-only | 0.424 | 0.71 | 2324 ms | 0.785 | 57 / 86 |
| **Tenant-only** | **0.492** | 0.57 | 2209 ms | 0.682 | **9 / 135** |
| Hierarchical | **0.509** | 0.59 | 2046 ms | 0.678 | **7 / 136** |

Whole-run \(G_A\): Global 0.639, Class-only 0.697, Tenant-only 0.724, Hierarchical 0.738. P1 and P3 \(G_A\) are ~0.91 / ~0.89 on every policy.

**Claim:** the tenant layer is necessary. It is the only policy that **moves rejects onto B** (A’s P2 rejects 9 vs B’s 135). Global lets B share the queue; A’s P2 goodput collapses to 0.30. Hierarchical ≈ tenant-only, as designed (both tenants are short).

**Do not write “class-only ≈ global.”** Class-only cannot see A vs B (rejA still ~57), but `class_full` is an immediate reject, so it beats global’s `queue_timeout` tail (0.42 vs 0.30). That is a queueing artifact, not tenant isolation.

## E6 — class isolation (`e6_class_isolation/`, 5 reps, 420 s)

One tenant. P2 is 70% short / 30% long at \(0.9 R_{\mathrm{ref}}\). Bedrock 429 = 0. Primary: P2 \(G_{\mathrm{short}}\).

| Policy | P2 \(G_{\mathrm{short}}\) | P2 att. | P2 P95 | Whole-run \(G_{\mathrm{short}}\) | Whole-run \(G_{\mathrm{long}}\) |
|---|---:|---:|---:|---:|---:|
| Global Token | 0.127 | 0.17 | 2140 ms | 0.569 | 0.070 |
| Tenant-only | 0.253 | 0.39 | 2147 ms | 0.622 | 0.117 |
| **Class-only** | **0.436** | 0.46 | 2037 ms | **0.702** | 0.122 |
| Hierarchical | **0.443** | 0.48 | 2074 ms | **0.709** | 0.125 |

**Claim:** the class layer is necessary. Same-tenant long traffic wrecks short under global (P2 \(G_{\mathrm{short}}=0.13\)). Tenant-only cannot split classes (0.25). Class-only ≈ hierarchical (0.44). Hierarchical reject reasons are `tenant_class_full` (50/rep) plus some `tenant_full`.

Tenant-only is **not** equal to global: `tenant_full` vs `queue_timeout` again. Rank is Global < Tenant-only < Class-only ≈ Hierarchical. The identified gap is class vs tenant, not tenant vs global.

## E7 — joint interference (`e7_joint_interference/`, 3 reps, 420 s)

A mixed + B mixed burst. Bedrock 429 = 0. Primary: P2 \(G_{A,\mathrm{short}}\).

| Policy | P2 \(G_{A,\mathrm{short}}\) | P2 att. | P2 P95 | P2 \(G_B\) | Whole-run \(G_{A,\mathrm{short}}\) |
|---|---:|---:|---:|---:|---:|
| Tenant-only | 0.188 | 0.37 | 2082 ms | 0.169 | 0.599 |
| Class-only | 0.205 | 0.39 | 2121 ms | **0.290** | 0.607 |
| Hierarchical | **0.220** | 0.41 | 2029 ms | 0.219 | **0.616** |

**Claim, weakly:** hierarchical is best on \(G_{A,\mathrm{short}}\) in all 3 reps vs tenant-only, and in 2/3 vs class-only. It does not zero \(G_B\). The complementary gap is **small** (~0.188 → 0.220). Do not sell E7 as the main result; E5 and E6 identify the two layers. Optional: more reps if a reviewer wants a significance test. The P2 log’s `decrease-token` + HTTP 429s are longs occupying \(W_t=4608\) at \(C_g=1\), then gateway sheds — expected.

## P0 — overflow-reject control (`e5_overflow_reject/`, `e6_overflow_reject/`, 3 reps, 420 s)

Same workloads and policies as the queued 5-rep E5/E6; `overflow_mode=reject`, `queue_max=0`. Every overflow is an immediate `*_full` (never `queue_timeout`). Bedrock 429 = 0. Admitted P95 is backend TTFT (~400–760 ms), not a wait tail.

E5 P2 (arrival-time split):

| Policy | \(G_A^{\mathrm{short}}\) | A SLO att. | A P95 | \(G_B\) | Rejects /rep |
|---|---:|---:|---:|---:|---|
| Global Token | 0.338 | 0.99 | 401 ms | 1.347 | `global_full` 156 |
| Class-only | 0.442 | 0.95 | 513 ms | 1.206 | `class_full` 17 + `global_full` 130 |
| **Tenant-only** | **0.453** | 0.92 | 761 ms | 1.206 | `tenant_full` 42 + `global_full` 105 |
| Hierarchical | 0.427 | 0.97 | 449 ms | 1.204 | `tenant_full` 47 + `global_full` 109 |

E6 P2:

| Policy | \(G_{\mathrm{short}}\) | att. | P95 | Rejects /rep |
|---|---:|---:|---:|---|
| Global Token | 0.504 | 0.99 | 426 ms | `global_full` 163 |
| Tenant-only | 0.518 | 0.98 | 463 ms | `global_full` 165 (`tenant_full` 0.7) |
| **Class-only** | **0.545** | 0.99 | 439 ms | `class_full` 43 + `global_full` 114 |
| Hierarchical | 0.450 | 0.91 | 785 ms | `tenant_class_full` 40 + `global_full` 128 |

**Claim:** both pass criteria hold on the mean. E6 Class-only \(>\) Tenant-only in **3/3** reps (0.545 vs 0.518). E5 Tenant-only \(>\) Class-only on the mean (0.453 vs 0.442) but only **2/3** reps — the identified tenant-vs-class gap **collapses** once A cannot wait in a queue while B is rejected. The robust leftover: E5 Tenant-only \(>\) Global (0.45 vs 0.34); E6 Tenant-only \(\approx\) Global (0.518 vs 0.504), which is the artifact the control was meant to kill. Hierarchical is noisy at 3 reps (E6 rep2 P95 1.45 s). Do not retune budgets. Do not cite queued Global vs Class/Tenant as isolation.

P1/P3 \(G_A\) / \(G_{\mathrm{short}}\) stay ~0.9 on E5. E6 P1 is a bit noisier (tenant 0.80 vs global 0.92).

Optional later: E7 `--reps 5` (do not retune). E1 C=1,2,4 × 3 reps (write “best observed,” not universal knee, if skipped).

## Allowed paper claims

1. Bedrock Llama 4 Maverick has a concurrency knee at \(C=1\) (E1).
2. Best \(C\) moves with offered load; Fixed-1 collapses in the E3 burst.
3. SLO-AIMD (+15.5% whole-run goodput vs Fixed) by raising \(C\) only under demand + healthy backend TTFT.
4. Token demand changes the right \(C\) at constant RPS; token-aware recovers after long→short where request-count AIMD does not (E4, RQ1 ablation −token).
5. Same-class noisy neighbor (queued 5-rep): tenant cap moves rejects onto B (E5 P2 \(G_A\) 0.49 vs global 0.30). Under unified reject the tenant-vs-class gap is tiny; Tenant-only still beats Global (0.45 vs 0.34).
6. Same-tenant mixed class (queued 5-rep): class cap restores short (E6 P2 \(G_{\mathrm{short}}\) 0.44 vs tenant-only 0.25). Under unified reject Class-only \(>\) Tenant-only in 3/3 and Tenant-only \(\approx\) Global.
7. Hierarchical is directionally best under joint interference, but the extra gap is small (E7).

## Traps

- Do not cite `e3_dynamic_load/` “+19% / −33% P95 / \(C\approx 20\)”.
- Do not claim E3 v2 cut P95 (2140 vs 2173 ms).
- Do not treat gateway `queue_timeout` 429s as Bedrock throttle.
- Do not write `TPM > 80% quota → decrease C`.
- Retired quota E5 does not support a quota-cliff claim.
- `results/e6_ablation/` did not ablate the demand gate. −MD is not identified at this \(C\). RQ1 appendix, not paper E7.
- E4 / ablation P2 token-aware goodput is ~0 by design (reject longs). The metric that matters is P3.
- Do not cite v1 `e5_noisy_neighbor/` / `e6_mixed_class/` (tenant=class confound; static admit).
- E5–E7 primary split is P2 \(G_A^{\mathrm{short}}\) / \(G_{\mathrm{short}}\), not whole-run aggregate. P1/P3 wash.
- Do not write E5 “class-only ≈ global”: class-only still cannot prefer A, but immediate reject beats `queue_timeout`.
- Do not write E6 “tenant-only ≈ global”: same reject-vs-queue artifact.
- E7 complementary effect is small (3 reps). Do not hang the paper on it.
- Watch \(G_B\): isolation is not “refuse all of B.” Tenant-only on E5 still gives P2 \(G_B\approx 0.68\) (queued) / \(\approx 1.21\) (reject; almost all admits meet SLO).
- P0: do not sell the queued E5 tenant-vs-class gap (0.492 vs 0.424) as causal identity — it shrinks to 0.453 vs 0.442 with unified reject. The E6 class-vs-tenant ordering survives.

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

Phase splits: bucket `events.jsonl` by `arrival_ts - min(arrival_ts)` using the YAML `until_s` edges (E3: 120/240/300/420; E4/ablation: 180/300/480; E5–E7: 120/300/420). Per-tenant / per-class / pair: `summary["by_tenant"]` / `by_class` / `by_tenant_class`.
