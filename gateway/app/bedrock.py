from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError


THROTTLE_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceQuotaExceededException",
}


@dataclass
class StreamResult:
    text: str
    input_tokens: int
    output_tokens: int
    ttft_ms: float | None
    e2e_ms: float
    first_token_ts: float | None
    finish_ts: float
    bedrock_429: bool
    bedrock_5xx: bool
    error: str | None = None
    retries: int = 0


def converse_stream(
    client,
    *,
    model_id: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    start_ts: float,
    temperature: float = 0.0,
    collect_text: bool = False,
) -> StreamResult:
    """Call Bedrock ConverseStream and measure TTFT from the first content token."""
    kwargs = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    text_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0
    first_token_ts: float | None = None
    bedrock_429 = False
    bedrock_5xx = False
    error = None

    try:
        response = client.converse_stream(**kwargs)
        for event in response.get("stream") or []:
            if "contentBlockDelta" in event:
                if first_token_ts is None:
                    first_token_ts = time.time()
                if collect_text:
                    piece = (event["contentBlockDelta"].get("delta") or {}).get("text") or ""
                    if piece:
                        text_parts.append(piece)
            elif "metadata" in event:
                usage = event["metadata"].get("usage") or {}
                input_tokens = int(usage.get("inputTokens") or input_tokens)
                output_tokens = int(usage.get("outputTokens") or output_tokens)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        error = str(exc)
        if code in THROTTLE_CODES:
            bedrock_429 = True
        else:
            bedrock_5xx = True
    except Exception as exc:  # noqa: BLE001
        bedrock_5xx = True
        error = str(exc)

    finish_ts = time.time()
    ttft_ms = None if first_token_ts is None else (first_token_ts - start_ts) * 1000
    return StreamResult(
        text="".join(text_parts),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        ttft_ms=ttft_ms,
        e2e_ms=(finish_ts - start_ts) * 1000,
        first_token_ts=first_token_ts,
        finish_ts=finish_ts,
        bedrock_429=bedrock_429,
        bedrock_5xx=bedrock_5xx,
        error=error,
    )


class MockBedrock:
    """Deterministic local backend for tests and dry runs."""

    def __init__(
        self,
        *,
        ttft_s: float = 0.02,
        token_s: float = 0.0,
        throttle_when_inflight: int | None = None,
        inflight_fn=None,
    ) -> None:
        self.ttft_s = ttft_s
        self.token_s = token_s
        self.throttle_when_inflight = throttle_when_inflight
        self.inflight_fn = inflight_fn

    def converse_stream(self, **kwargs):
        inflight = 0 if self.inflight_fn is None else int(self.inflight_fn())
        if self.throttle_when_inflight is not None and inflight >= self.throttle_when_inflight:
            raise ClientError(
                {"Error": {"Code": "ThrottlingException", "Message": "mock throttle"}},
                "ConverseStream",
            )
        max_tokens = int((kwargs.get("inferenceConfig") or {}).get("maxTokens") or 8)
        if self.ttft_s or self.token_s:
            time.sleep(self.ttft_s + self.token_s * max_tokens)
        return {
            "stream": [
                {"contentBlockDelta": {"delta": {"text": "ok"}}},
                {"metadata": {"usage": {"inputTokens": 16, "outputTokens": max_tokens}}},
            ]
        }
