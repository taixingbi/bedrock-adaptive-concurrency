from pathlib import Path

from scripts.run_experiment import cells_from_spec, expand_spec, load_spec


def test_e1_cells():
    spec = load_spec(Path("experiments/e1_sweep.yaml"))
    cells = cells_from_spec(spec, {})
    assert [c["c"] for c in cells] == [1, 2, 4, 8, 16, 32, 64]


def test_e2_light_load_cells():
    spec = expand_spec(load_spec(Path("experiments/e2_static_vs_adaptive.yaml")), {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    assert [c["name"] for c in cells] == ["fixed_1", "fixed_2", "slo_aimd"]
    assert [c["c"] for c in cells] == [1, 2, 1]
    assert spec["offered_rps"] == 0.92


def test_e2_derived_cells_when_unspecified():
    cells = cells_from_spec({"experiment": "E2"}, {"c_knee": 16})
    names = [c["name"] for c in cells]
    assert names == ["fixed_low", "fixed_knee", "fixed_high", "retry_backoff", "gradient", "slo_aimd"]
    assert cells[0]["c"] == 8
    assert cells[2]["c"] == 32


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
