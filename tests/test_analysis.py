from analysis.knee import find_knee
from analysis.metrics import filter_warmup, percentile, summarize, summarize_groups


def test_percentile():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([], 0.95) is None


def test_find_knee_plateau_and_latency():
    points = [
        {"c": 1, "throughput_rps": 1.0, "p95_ttft_ms": 200},
        {"c": 2, "throughput_rps": 1.9, "p95_ttft_ms": 220},
        {"c": 4, "throughput_rps": 3.4, "p95_ttft_ms": 250},
        {"c": 8, "throughput_rps": 3.5, "p95_ttft_ms": 400},
        {"c": 16, "throughput_rps": 3.55, "p95_ttft_ms": 900},
    ]
    knee = find_knee(points)
    assert knee["c_knee"] == 4
    assert knee["r_knee"] == 3.4
    assert knee["slo_ms"] == 1.5 * 250
    assert knee["c_low"] == 2
    assert knee["c_high"] == 8


def test_summarize_goodput_and_warmup():
    events = [
        {
            "arrival_ts": 100.0,
            "finish_ts": 100.2,
            "decision": "ADMIT",
            "ttft_ms": 80,
            "e2e_ms": 120,
            "slo_met": True,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "input_tokens": 10,
            "output_tokens": 5,
            "c_limit": 4,
        },
        {
            "arrival_ts": 110.0,
            "finish_ts": 110.2,
            "decision": "ADMIT",
            "ttft_ms": 90,
            "e2e_ms": 130,
            "slo_met": True,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "input_tokens": 10,
            "output_tokens": 5,
            "c_limit": 4,
        },
    ]
    assert len(filter_warmup(events, 5)) == 1
    summary = summarize(events, warmup_s=5)
    assert summary["achieved_n"] == 1
    assert summary["slo_goodput_rps"] > 0


def test_summarize_groups_by_tenant():
    events = [
        {
            "arrival_ts": 1.0,
            "finish_ts": 2.0,
            "decision": "ADMIT",
            "ttft_ms": 80,
            "e2e_ms": 120,
            "slo_met": True,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "tenant_id": "A",
            "c_limit": 2,
        },
        {
            "arrival_ts": 1.0,
            "finish_ts": 2.0,
            "decision": "REJECT",
            "ttft_ms": None,
            "e2e_ms": 0,
            "slo_met": False,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "tenant_id": "B",
            "c_limit": 2,
        },
    ]
    by = summarize_groups(events, key="tenant_id")
    assert by["A"]["slo_goodput_rps"] > 0
    assert by["B"]["reject_n"] == 1


def test_summarize_tenant_class_and_reject_reason():
    events = [
        {
            "arrival_ts": 1.0,
            "finish_ts": 2.0,
            "decision": "ADMIT",
            "ttft_ms": 80,
            "e2e_ms": 120,
            "slo_met": True,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "tenant_id": "A",
            "prompt_class": "short",
            "c_limit": 2,
        },
        {
            "arrival_ts": 1.0,
            "finish_ts": 2.0,
            "decision": "REJECT",
            "reason": "tenant_class_full",
            "ttft_ms": None,
            "e2e_ms": 0,
            "slo_met": False,
            "bedrock_429": False,
            "bedrock_5xx": False,
            "tenant_id": "A",
            "prompt_class": "long",
            "c_limit": 2,
        },
    ]
    from analysis.metrics import tenant_class_key

    by = summarize_groups(events, key_fn=tenant_class_key)
    assert by["A:short"]["slo_goodput_rps"] > 0
    assert by["A:long"]["reject_by_reason"]["tenant_class_full"] == 1
