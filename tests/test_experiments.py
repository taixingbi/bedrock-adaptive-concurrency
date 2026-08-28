from pathlib import Path

from scripts.run_experiment import (
    cell_already_done,
    cells_for_rep,
    cells_from_spec,
    collect_summaries,
    expand_spec,
    load_spec,
    streams_for,
)


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


def test_e5_noisy_cells_and_streams():
    spec = expand_spec(load_spec(Path("experiments/e5_noisy_neighbor.yaml")), {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    assert [c["name"] for c in cells] == ["global_token", "tenant_only", "class_only", "hierarchical"]
    assert all(c["policy"] == "token_slo_aimd" for c in cells)
    assert cells[-1]["caps"] == ["global", "tenant", "class"]
    assert spec["phases"][1]["tenants"]["B"]["prompt_class"] == "short"
    assert spec["phases"][1]["tenants"]["B"]["rps"] == 0.9 * 1.84
    streams = streams_for(spec, cells[-1])
    assert [s[0].tenant_id for s in streams] == ["A", "B"]
    assert streams[1][0].rps == 0
    assert streams[1][1].prompt_class == "short"
    order = cells_for_rep(cells, spec, 1)
    assert [c["name"] for c in order] == ["global_token", "tenant_only", "class_only", "hierarchical"]
    order2 = cells_for_rep(cells, spec, 2)
    assert [c["name"] for c in order2] == ["class_only", "hierarchical", "global_token", "tenant_only"]


def test_e6_mixed_cells_and_mix():
    spec = expand_spec(load_spec(Path("experiments/e6_mixed_class.yaml")), {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    assert [c["name"] for c in cells] == ["global_token", "tenant_only", "class_only", "hierarchical"]
    streams = streams_for(spec, cells[1])
    assert len(streams) == 1
    assert streams[0][0].tenant_id == "A"
    assert streams[0][1].mix == {"short": 0.7, "long": 0.3}
    assert spec["phases"][1]["rps"] == 0.9 * 1.84


def test_e7_joint_mix_per_tenant():
    spec = expand_spec(load_spec(Path("experiments/e7_joint_interference.yaml")), {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    assert [c["name"] for c in cells] == ["tenant_only", "class_only", "hierarchical"]
    streams = streams_for(spec, cells[-1])
    assert [s[0].tenant_id for s in streams] == ["A", "B"]
    assert streams[0][1].mix == {"short": 0.8, "long": 0.2}
    assert streams[1][1].mix == {"short": 0.5, "long": 0.5}
    assert spec["phases"][1]["tenants"]["B"]["rps"] == 0.7 * 1.84
    assert spec["repetitions"] == 5
    assert len(spec["policy_schedules"]) == 5
    assert [c["name"] for c in cells_for_rep(cells, spec, 4)] == [
        "tenant_only",
        "hierarchical",
        "class_only",
    ]
    assert [c["name"] for c in cells_for_rep(cells, spec, 5)] == [
        "class_only",
        "tenant_only",
        "hierarchical",
    ]


def test_overflow_reject_specs_use_immediate_reject():
    e5 = load_spec(Path("experiments/e5_overflow_reject.yaml"))
    e6 = load_spec(Path("experiments/e6_overflow_reject.yaml"))
    assert e5["overflow_mode"] == e6["overflow_mode"] == "reject"
    assert e5["queue_max"] == e6["queue_max"] == 0
    assert e5["repetitions"] == e6["repetitions"] == 3
    spec = expand_spec(e5, {"c_knee": 1, "r_knee": 1.84})
    cells = cells_from_spec(spec, spec["_derived"])
    assert [c["name"] for c in cells] == ["global_token", "tenant_only", "class_only", "hierarchical"]


def test_skip_existing_cell_and_collect_summaries(tmp_path):
    cell = tmp_path / "e7_joint_interference" / "hierarchical" / "rep1"
    cell.mkdir(parents=True)
    (cell / "events.jsonl").write_text("{}\n")
    (cell / "summary.json").write_text('{"cell":"hierarchical","rep":1}')
    assert cell_already_done(tmp_path, "e7_joint_interference", "hierarchical", 1)
    assert not cell_already_done(tmp_path, "e7_joint_interference", "hierarchical", 2)
    rows = collect_summaries(tmp_path / "e7_joint_interference")
    assert rows == [{"cell": "hierarchical", "rep": 1}]
