from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class GatewayMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.offered_rps = Gauge("llm_offered_rps", "Offered requests per second", registry=self.registry)
        self.achieved_rps = Gauge("llm_achieved_rps", "Successful completions per second", registry=self.registry)
        self.input_tokens_per_sec = Gauge(
            "llm_input_tokens_per_sec", "Input tokens per second", registry=self.registry
        )
        self.output_tokens_per_sec = Gauge(
            "llm_output_tokens_per_sec", "Output tokens per second", registry=self.registry
        )
        self.inflight = Gauge("llm_inflight_requests", "Current in-flight Bedrock requests", registry=self.registry)
        self.concurrency_limit = Gauge(
            "llm_concurrency_limit", "Controller concurrency limit C", registry=self.registry
        )
        self.slo_goodput_rps = Gauge(
            "llm_slo_goodput_rps", "SLO-compliant successful requests per second", registry=self.registry
        )
        self.rpm_quota = Gauge("bedrock_rpm_quota", "Static Bedrock RPM quota context", registry=self.registry)
        self.tpm_quota = Gauge("bedrock_tpm_quota", "Static Bedrock TPM quota context", registry=self.registry)
        self.tpd_quota = Gauge("bedrock_tpd_quota", "Static Bedrock TPD quota context", registry=self.registry)
        self.throttle_total = Counter("llm_throttle_total", "Bedrock throttle / 429 count", registry=self.registry)
        self.error_total = Counter("llm_error_total", "Bedrock 5xx / error count", registry=self.registry)
        self.ttft = Histogram(
            "llm_ttft_seconds",
            "User-facing TTFT including queue wait",
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32),
            registry=self.registry,
        )
        self.latency = Histogram(
            "llm_request_latency_seconds",
            "User-facing end-to-end latency",
            buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
            registry=self.registry,
        )

    def set_quotas(self, rpm: int, tpm: int, tpd: int = 0) -> None:
        self.rpm_quota.set(rpm)
        self.tpm_quota.set(tpm)
        self.tpd_quota.set(tpd)

    def set_runtime(self, *, inflight: int, c: int) -> None:
        self.inflight.set(inflight)
        self.concurrency_limit.set(c)

    def set_rates(
        self,
        *,
        offered_rps: float,
        achieved_rps: float,
        input_tps: float,
        output_tps: float,
        slo_goodput_rps: float,
    ) -> None:
        self.offered_rps.set(offered_rps)
        self.achieved_rps.set(achieved_rps)
        self.input_tokens_per_sec.set(input_tps)
        self.output_tokens_per_sec.set(output_tps)
        self.slo_goodput_rps.set(slo_goodput_rps)
