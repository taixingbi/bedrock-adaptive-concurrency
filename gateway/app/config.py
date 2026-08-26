from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    model_id: str = "us.meta.llama4-maverick-17b-instruct-v1:0"
    policy: str = "fixed"
    concurrency_limit: int = 8
    c_min: int = 1
    c_max: int = 64
    queue_max: int = 16
    queue_timeout_s: float = 2.0
    controller_window_s: float = 5.0
    aimd_beta: float = 0.7
    min_samples: int = 5
    throttle_rate_low: float = 0.02
    error_rate_low: float = 0.02
    ttft_slo_ms: float = 2000.0
    token_lambda: float = 1.0
    token_pressure_gamma: float = 1.2
    short_input_tokens: int = 512
    short_output_tokens: int = 128
    gradient_epsilon: float = 0.05
    bedrock_rpm_quota: int = 800
    bedrock_tpm_quota: int = 600000
    bedrock_tpd_quota: int = 432000000
    results_path: str = "results"
    run_id: str = "local"
    use_token_awareness: bool = True
    use_ttft_signal: bool = True
    use_throttle_signal: bool = True
    use_multiplicative_decrease: bool = True
    use_demand_gate: bool = True
    demand_queue_ms: float = 5.0
    retry_max: int = 3
    retry_base_s: float = 0.25
    timeseries_s: float = 1.0
    mock_bedrock: bool = False
    admit_caps: str = "global"
    tenant_caps: dict[str, int] = Field(default_factory=dict)
    class_caps: dict[str, int] = Field(default_factory=dict)
    class_slo_ms: dict[str, float] = Field(default_factory=dict)

    @property
    def w_short(self) -> float:
        return self.short_input_tokens + self.token_lambda * self.short_output_tokens

    @property
    def admit_cap_set(self) -> set[str]:
        return {part.strip() for part in self.admit_caps.split(",") if part.strip()}

    @property
    def use_tenant_cap(self) -> bool:
        return "tenant" in self.admit_cap_set

    @property
    def use_class_cap(self) -> bool:
        return "class" in self.admit_cap_set

    def slo_ms_for(self, prompt_class: str) -> float:
        if prompt_class in self.class_slo_ms:
            return float(self.class_slo_ms[prompt_class])
        return float(self.ttft_slo_ms)
