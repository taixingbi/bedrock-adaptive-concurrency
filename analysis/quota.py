from __future__ import annotations

from typing import Any

# Published Llama 4 Maverick defaults (per account, per region, US geo / CRIS).
# Context only — never a control law.
BEDROCK_RPM_QUOTA = 800
BEDROCK_TPM_QUOTA = 600_000
BEDROCK_TPD_QUOTA = 432_000_000
SHORT_TOKENS = (512, 128)
LONG_TOKENS = (4096, 512)


def tokens_per_request(input_tokens: int, output_tokens: int) -> int:
    return int(input_tokens) + int(output_tokens)


def rps_from_rpm(rpm: int = BEDROCK_RPM_QUOTA) -> float:
    return float(rpm) / 60.0


def rps_from_tpm(tpm: int, input_tokens: int, output_tokens: int) -> float:
    tpr = max(tokens_per_request(input_tokens, output_tokens), 1)
    return float(tpm) / (tpr * 60.0)


def tpm_at_rps(rps: float, input_tokens: int, output_tokens: int) -> float:
    return float(rps) * tokens_per_request(input_tokens, output_tokens) * 60.0


def envelope(
    input_tokens: int,
    output_tokens: int,
    *,
    rpm: int = BEDROCK_RPM_QUOTA,
    tpm: int = BEDROCK_TPM_QUOTA,
) -> dict[str, Any]:
    r_rpm = rps_from_rpm(rpm)
    r_tpm = rps_from_tpm(tpm, input_tokens, output_tokens)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens_per_request": tokens_per_request(input_tokens, output_tokens),
        "rps_rpm": r_rpm,
        "rps_tpm": r_tpm,
        "rps_cap": min(r_rpm, r_tpm),
        "binding": "rpm" if r_rpm <= r_tpm else "tpm",
    }


def published_envelopes() -> dict[str, dict[str, Any]]:
    return {
        "short": envelope(*SHORT_TOKENS),
        "long": envelope(*LONG_TOKENS),
    }


def warn_rps(rps: float, prompt_class: str, *, frac: float = 0.75) -> str | None:
    env = published_envelopes()["long" if prompt_class == "long" else "short"]
    if rps > env["rps_cap"]:
        return (
            f"offered {rps:.2f} rps on {prompt_class} exceeds {env['binding']} cap "
            f"{env['rps_cap']:.2f} rps ({env['binding']} binds)"
        )
    if rps > frac * env["rps_cap"]:
        return (
            f"offered {rps:.2f} rps on {prompt_class} is {rps / env['rps_cap']:.2f}× "
            f"the {env['binding']} cap {env['rps_cap']:.2f} rps"
        )
    return None
