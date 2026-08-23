from pathlib import Path

from scripts.run_experiment import cells_from_spec, expand_spec, load_spec


def test_e1_cells():
    spec = load_spec(Path("experiments/e1_sweep.yaml"))
    cells = cells_from_spec(spec, {})
    assert [c["c"] for c in cells] == [1, 2, 4, 8, 16, 32, 64]


def test_e2_cells_need_knee():
    spec = expand_spec(load_spec(Path("experiments/e2_static_vs_adaptive.yaml")), {"c_knee": 16, "r_knee": 4.0})
    cells = cells_from_spec(spec, spec["_derived"])
    names = [c["name"] for c in cells]
    assert names == ["fixed_low", "fixed_knee", "fixed_high", "retry_backoff", "gradient", "slo_aimd"]
    assert cells[0]["c"] == 8
    assert cells[2]["c"] == 32


def test_e2_cells_skip_fixed_low_when_c_knee_is_1():
    spec = expand_spec(load_spec(Path("experiments/e2_static_vs_adaptive.yaml")), {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    names = [c["name"] for c in cells]
    assert names == ["fixed_knee", "fixed_high", "retry_backoff", "gradient", "slo_aimd"]
    assert cells[0]["c"] == 1
    assert cells[1]["c"] == 2
    assert spec["offered_rps"] == 0.92


def test_e4_phase_rps():
    spec = expand_spec(load_spec(Path("experiments/e4_token_shift.yaml")), {"r_knee": 10.0, "c_knee": 8})
    assert spec["phases"][1]["prompt_class"] == "long"
    assert spec["phases"][1]["rps"] == 9.0


def test_e5_uses_quota_envelope():
    spec = expand_spec(load_spec(Path("experiments/e5_quota_pressure.yaml")), {})
    cells = cells_from_spec(spec, spec["_derived"])
    ones = [c for c in cells if c["name"] == "slo_aimd_f1.0"]
    assert ones
    assert abs(ones[0]["rps"] - 800 / 60) < 1e-9
    highs = [c for c in cells if c["name"] == "slo_aimd_f1.25"]
    assert highs[0]["rps"] > 800 / 60


def test_e6_ablation_cells():
    spec = load_spec(Path("experiments/e6_ablation.yaml"))
    cells = cells_from_spec(spec, {"c_knee": 8, "r_knee": 4})
    assert [c["name"] for c in cells] == [
        "full",
        "minus_token",
        "minus_ttft",
        "minus_throttle",
        "minus_md",
    ]
