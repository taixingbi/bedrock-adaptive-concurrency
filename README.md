# bedrock-adaptive-concurrency

Multi-tenant and class-aware admission control for opaque managed LLM APIs (Amazon Bedrock). Gateway-visible signals only — no GPU / KV-cache telemetry. Nested budgets \(C_{global}\), \(C_t\), \(C_{t,c}\); quota is static context, not the control law.

Locked design: [docs/experiment-design.md](docs/experiment-design.md). RQ1 claims (E1–E4): [results/SUMMARY.md](results/SUMMARY.md).

```
Open-loop loadgen → LLM gateway → tenant/class admission + adaptive C → Bedrock ConverseStream → Llama 4 Maverick
```

Model: `us.meta.llama4-maverick-17b-instruct-v1:0` (US geo, `us-east-1`). Call Bedrock directly. Do not put `bedrock-inference-mvp` (Lambda Function URL) on this path.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Use Python 3.11 or 3.12. The pinned stack does not install cleanly on 3.14. After `source .venv/bin/activate`, use `python` (not system `python3`).

AWS credentials in `~/.aws/credentials` must be able to invoke the Maverick geo ID above.

## Smoke

Mock first (no AWS). TTFT will be ~25ms and closed-loop \(C=1\) can do tens of RPS:

```bash
MOCK_BEDROCK=true PYTHONPATH=gateway uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```bash
python -m loadgen.openloop --url http://127.0.0.1:8080 --mode closed_loop --concurrency 1 --measure-s 2 --prompt-class short
```

Then stop that process and start a **real** gateway. Do not set `MOCK_BEDROCK`:

```bash
PYTHONPATH=gateway uvicorn app.main:app --host 127.0.0.1 --port 8080
```

```bash
python -m loadgen.openloop --url http://127.0.0.1:8080 --mode closed_loop --concurrency 1 --measure-s 1 --prompt-class short
```

Real Maverick on `short` (512/128) should look like: 1–2 OK requests in 1s, TTFT P95 a few hundred ms (smoke saw ~360ms), gateway log `Found credentials in shared credentials file`. If you still see ~25ms TTFT or 30+ RPS, the mock server is still bound to :8080.

## Experiments

`scripts/run_experiment.py` starts and stops its own gateway. Stop any uvicorn on the same port first.

RQ1 (E1–E4) is done — do not rerun. Nested tenant/class admission is implemented. Next: mock `dryrun_tenants`, then **new E5** / **new E6** on Bedrock. Retired: `e5_quota_pressure.yaml`. Old `results/e6_ablation/` is E7 traces, not the new E6.

```bash
# cheap knee scout: C=1,2,4,8; 30s warmup + 60s measure; 1 rep
python scripts/run_experiment.py experiments/e1_pilot.yaml --port 8080

# read derived knobs
cat results/e1_pilot/summary.json
```

Pilot is healthy when `inflight` matches \(C\), `w_t \approx C \times 640` on `short`, responses are 200, and 429s are absent. If 429s start, stop: that is the 800 RPM cliff, not \(C_{knee}\).

After the pilot, pass `--c-knee`, `--r-knee`, and `--slo-ms` (use \(1.5 \times\) P95 TTFT at \(C_{knee}\)). This account's E1 pilot found \(C_{knee}=1\), \(R_{knee}\approx 1.84\), SLO \(\approx 576\) ms. Do **not** run `e1_sweep.yaml` (C=16/32/64) — throughput already flat at C≥2 and tails explode.

When \(C_{knee}=1\), open-loop at \(0.9 R_{knee}\) (1.66 rps) plus an unbounded wait queue is unstable: user-facing TTFT includes queue wait and climbs without bound. E2 now offers \(0.5 R_{knee}\) (~0.92 rps) and waiters time out after 2s (`queue_timeout`). Discard any E2 numbers from the killed `fixed_low` run.

```bash
# E2 light-load sanity → results/e2_light_load (C must stay 1–2)
python scripts/run_experiment.py experiments/e2_static_vs_adaptive.yaml --c-knee 1 --r-knee 1.84 --slo-ms 576 --port 8080

# E3 main rerun → results/e3_dynamic_load_v2
python scripts/run_experiment.py experiments/e3_dynamic_load.yaml --c-knee 1 --r-knee 1.84 --slo-ms 576 --port 8080

# E4 token-shift decision → results/e4_token_shift_v2
python scripts/run_experiment.py experiments/e4_token_shift.yaml --c-knee 1 --r-knee 1.84 --slo-ms 576 --port 8080

# nested admission mock
python scripts/run_experiment.py experiments/dryrun_tenants.yaml --mock --reps 1 --port 8080

# new E5 / E6 (Bedrock; 5 reps)
python scripts/run_experiment.py experiments/e5_noisy_neighbor.yaml --c-knee 1 --r-knee 1.84 --slo-ms 576 --port 8080
python scripts/run_experiment.py experiments/e6_mixed_class.yaml --c-knee 1 --r-knee 1.84 --slo-ms 576 --port 8080
```

Optional PNGs: add `--plot`. Local harness check: `python scripts/run_experiment.py experiments/dryrun.yaml --mock --reps 1 --port 8080`.

## Load generator (manual)

Closed-loop saturation (E1-style):

```bash
python -m loadgen.openloop --url http://127.0.0.1:8080 --mode closed_loop --concurrency 8 --warmup-s 60 --measure-s 180 --prompt-class short
```




Open-loop RPS (E2–E4, later E5/E6):

```bash
python -m loadgen.openloop --url http://127.0.0.1:8080 --mode open_loop --rps 4 --measure-s 180 --prompt-class short
```

## Quota (static context only)

Published Maverick defaults: 800 RPM, 600k TPM, 432M TPD.

- `short` (640 tok): RPM binds at 13.33 RPS
- `long` (4608 tok): TPM binds at 2.17 RPS

E1–E4 stay \(\le 0.75 \times 13.33 \approx 10\) RPS unless \(R_{knee}\) is lower. Same RPS on `long` can exceed 600k TPM; that is the E4 finding, not a `TPM > 80% quota → decrease C` control law. The old quota-pressure E5 is retired.

Gauges `bedrock_rpm_quota`, `bedrock_tpm_quota`, and `bedrock_tpd_quota` are exposed and never used to set \(C\).

## Policies

| Name | Role |
|---|---|
| `fixed` | Static \(C\) |
| `retry_backoff` | High static \(C\) + exponential backoff on 429/5xx |
| `gradient` | Adapt \(C\) from TTFT P95 trend |
| `slo_aimd` | \(C+1\) / \(0.7C\) from TTFT P95 and throttle |
| `token_slo_aimd` | SLO-AIMD plus inflight token pressure \(W_t\) |
| `tenant_admit` | Nested caps \(C_{global}\), \(C_t\), \(C_{t,c}\) (E5/E6) |

## Tests

```bash
python -m pytest
```
