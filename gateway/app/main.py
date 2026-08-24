from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import boto3
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.bedrock import MockBedrock, StreamResult, converse_stream
from app.config import Settings
from app.controllers import build_controller
from app.limiter import ConcurrencyLimiter
from app.metrics import GatewayMetrics
from app.prompts import build_prompt, resolve_workload
from app.results import JsonlWriter
from app.window import ObservationWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, bedrock_client: Any = None) -> FastAPI:
    settings = settings or Settings()
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _app.state.controller_task = asyncio.create_task(_controller_loop(_app))
        _app.state.series_task = asyncio.create_task(_timeseries_loop(_app))
        try:
            yield
        finally:
            for name in ("controller_task", "series_task"):
                task = getattr(_app.state, name, None)
                if task:
                    task.cancel()

    app = FastAPI(title="bedrock-adaptive-concurrency", version="0.1.0", lifespan=lifespan)
    limiter = ConcurrencyLimiter(settings.concurrency_limit, settings.queue_max)
    controller = build_controller(settings)
    window = ObservationWindow()
    metrics = GatewayMetrics()
    metrics.set_quotas(settings.bedrock_rpm_quota, settings.bedrock_tpm_quota, settings.bedrock_tpd_quota)
    metrics.set_runtime(inflight=0, c=settings.concurrency_limit, waiting=0)

    run_dir = Path(settings.results_path) / settings.run_id
    events = JsonlWriter(run_dir / "events.jsonl")
    series = JsonlWriter(run_dir / "timeseries.jsonl")

    if bedrock_client is None:
        if settings.mock_bedrock:
            bedrock_client = MockBedrock(inflight_fn=lambda: limiter.inflight)
        else:
            bedrock_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)

    app.state.settings = settings
    app.state.limiter = limiter
    app.state.controller = controller
    app.state.window = window
    app.state.metrics = metrics
    app.state.events = events
    app.state.series = series
    app.state.bedrock = bedrock_client
    app.state.last_snapshot = None
    app.state.totals = {"offered": 0, "achieved": 0, "slo": 0, "input": 0, "output": 0}

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "policy": controller.name,
            "c": limiter.limit,
            "inflight": limiter.inflight,
            "actual_inflight": limiter.inflight,
            "utilization": limiter.inflight / max(limiter.limit, 1),
            "queue_depth": limiter.waiting,
            "waiting": limiter.waiting,
            "w_t": limiter.w_t,
            "ttft_slo_ms": settings.ttft_slo_ms,
            "last_action": controller.last_action,
            "model_id": settings.model_id,
        }

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/infer")
    async def infer(payload: dict[str, Any], request: Request) -> JSONResponse:
        return await _handle_infer(app, payload, request)

    @app.post("/v1/admin/config")
    async def admin_config(payload: dict[str, Any]) -> dict[str, Any]:
        if "concurrency_limit" in payload:
            settings.concurrency_limit = int(payload["concurrency_limit"])
            await limiter.set_limit(settings.concurrency_limit)
        if "ttft_slo_ms" in payload:
            settings.ttft_slo_ms = float(payload["ttft_slo_ms"])
        if "c_max" in payload:
            settings.c_max = int(payload["c_max"])
        return health()

    return app


async def _handle_infer(app: FastAPI, payload: dict[str, Any], request: Request) -> JSONResponse:
    settings: Settings = app.state.settings
    limiter: ConcurrencyLimiter = app.state.limiter
    window: ObservationWindow = app.state.window
    metrics: GatewayMetrics = app.state.metrics
    controller = app.state.controller
    arrival_ts = time.time()
    await window.offered()
    app.state.totals["offered"] += 1

    inp, out, prompt_class = resolve_workload(
        payload.get("prompt_class"),
        payload.get("input_tokens"),
        payload.get("max_tokens"),
    )
    temperature = float(payload.get("temperature", 0.0))
    weight = float(inp) + settings.token_lambda * float(out)

    acquired = await limiter.acquire(weight, timeout_s=settings.queue_timeout_s)
    if not acquired.ok:
        event = _reject_event(
            settings,
            arrival_ts=arrival_ts,
            reason=acquired.reason,
            prompt_class=prompt_class,
            input_tokens=inp,
            max_tokens=out,
            weight=weight,
        )
        await window.observe(
            ttft_ms=None,
            backend_ttft_ms=None,
            queue_ms=0.0,
            throttle=False,
            error=False,
            slo_met=False,
            achieved=False,
            input_tokens=0,
            output_tokens=0,
        )
        app.state.events.write(event)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=acquired.reason)

    admit_ts = time.time()
    queue_ms = (admit_ts - arrival_ts) * 1000
    metrics.set_runtime(inflight=limiter.inflight, c=limiter.limit, waiting=limiter.waiting)
    try:
        result = await _invoke(app, payload, inp, out, temperature, admit_ts)
        retries = 0
        while (
            controller.retry_on_throttle
            and (result.bedrock_429 or result.bedrock_5xx)
            and retries < settings.retry_max
        ):
            delay = settings.retry_base_s * (2**retries)
            await asyncio.sleep(delay)
            retries += 1
            result = await _invoke(app, payload, inp, out, temperature, time.time())
            result.retries = retries
    finally:
        await limiter.release(weight)
        metrics.set_runtime(inflight=limiter.inflight, c=limiter.limit, waiting=limiter.waiting)

    user_ttft_ms = None if result.first_token_ts is None else (result.first_token_ts - arrival_ts) * 1000
    user_e2e_ms = (result.finish_ts - arrival_ts) * 1000
    achieved = bool(result.first_token_ts) and not result.bedrock_429 and not result.bedrock_5xx
    slo_met = achieved and user_ttft_ms is not None and user_ttft_ms <= settings.ttft_slo_ms

    if result.bedrock_429:
        metrics.throttle_total.inc()
    if result.bedrock_5xx:
        metrics.error_total.inc()
    if user_ttft_ms is not None:
        metrics.ttft.observe(user_ttft_ms / 1000.0)
    metrics.latency.observe(user_e2e_ms / 1000.0)

    if achieved:
        app.state.totals["achieved"] += 1
        app.state.totals["input"] += result.input_tokens
        app.state.totals["output"] += result.output_tokens
    if slo_met:
        app.state.totals["slo"] += 1
    await window.observe(
        ttft_ms=user_ttft_ms,
        backend_ttft_ms=result.ttft_ms,
        queue_ms=queue_ms,
        throttle=result.bedrock_429,
        error=result.bedrock_5xx,
        slo_met=slo_met,
        achieved=achieved,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
    event = {
        "run_id": settings.run_id,
        "policy": controller.name,
        "arrival_ts": arrival_ts,
        "admit_ts": admit_ts,
        "first_token_ts": result.first_token_ts,
        "finish_ts": result.finish_ts,
        "queue_ms": queue_ms,
        "backend_ttft_ms": result.ttft_ms,
        "ttft_ms": user_ttft_ms,
        "e2e_ms": user_e2e_ms,
        "decision": "ADMIT",
        "reason": "ok" if achieved else (result.error or "backend_error"),
        "slo_met": slo_met,
        "bedrock_429": result.bedrock_429,
        "bedrock_5xx": result.bedrock_5xx,
        "retries": result.retries,
        "prompt_class": prompt_class,
        "requested_input_tokens": inp,
        "requested_max_tokens": out,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "c_limit": limiter.limit,
        "inflight": limiter.inflight,
        "w_t": limiter.w_t,
        "weight": weight,
        "ttft_slo_ms": settings.ttft_slo_ms,
        "model_id": settings.model_id,
        "path": request.url.path,
    }
    app.state.events.write(event)
    status_code = 200 if achieved else (429 if result.bedrock_429 else 502)
    return JSONResponse(event, status_code=status_code)


async def _invoke(
    app: FastAPI,
    payload: dict[str, Any],
    inp: int,
    out: int,
    temperature: float,
    start_ts: float,
) -> StreamResult:
    settings: Settings = app.state.settings
    messages = payload.get("messages") or [{"role": "user", "content": [{"text": build_prompt(inp, out)}]}]
    return await asyncio.to_thread(
        converse_stream,
        app.state.bedrock,
        model_id=settings.model_id,
        messages=messages,
        max_tokens=out,
        start_ts=start_ts,
        temperature=temperature,
        collect_text=False,
    )


def _reject_event(
    settings: Settings,
    *,
    arrival_ts: float,
    reason: str,
    prompt_class: str,
    input_tokens: int,
    max_tokens: int,
    weight: float,
) -> dict[str, Any]:
    return {
        "run_id": settings.run_id,
        "policy": settings.policy,
        "arrival_ts": arrival_ts,
        "admit_ts": None,
        "first_token_ts": None,
        "finish_ts": time.time(),
        "queue_ms": 0.0,
        "backend_ttft_ms": None,
        "ttft_ms": None,
        "e2e_ms": 0.0,
        "decision": "REJECT",
        "reason": reason,
        "slo_met": False,
        "bedrock_429": False,
        "bedrock_5xx": False,
        "retries": 0,
        "prompt_class": prompt_class,
        "requested_input_tokens": input_tokens,
        "requested_max_tokens": max_tokens,
        "input_tokens": 0,
        "output_tokens": 0,
        "c_limit": settings.concurrency_limit,
        "inflight": 0,
        "w_t": 0.0,
        "weight": weight,
        "ttft_slo_ms": settings.ttft_slo_ms,
        "model_id": settings.model_id,
    }


async def _controller_loop(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    limiter: ConcurrencyLimiter = app.state.limiter
    window: ObservationWindow = app.state.window
    controller = app.state.controller
    while True:
        await asyncio.sleep(settings.controller_window_s)
        snap = await window.flush(
            c=limiter.limit,
            inflight=limiter.inflight,
            waiting=limiter.waiting,
            w_t=limiter.w_t,
        )
        decision = controller.decide(snap)
        if decision.c != limiter.limit:
            await limiter.set_limit(decision.c)
        app.state.last_snapshot = snap
        logger.info(
            "controller policy=%s action=%s c=%s inflight=%s util=%.2f queue_depth=%s w_t=%.1f "
            "backend_ttft_p95=%s ttft_p95=%s",
            controller.name,
            decision.action,
            decision.c,
            snap.inflight,
            snap.utilization,
            snap.queue_depth,
            snap.w_t,
            snap.backend_ttft_p95_ms,
            snap.ttft_p95_ms,
        )


async def _timeseries_loop(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    limiter: ConcurrencyLimiter = app.state.limiter
    metrics: GatewayMetrics = app.state.metrics
    window: ObservationWindow = app.state.window
    last = time.time()
    last_offered = 0
    last_achieved = 0
    last_slo = 0
    last_in = 0
    last_out = 0
    while True:
        await asyncio.sleep(settings.timeseries_s)
        now = time.time()
        dt = max(now - last, 1e-6)
        totals = app.state.totals
        offered_rps = (totals["offered"] - last_offered) / dt
        achieved_rps = (totals["achieved"] - last_achieved) / dt
        slo_rps = (totals["slo"] - last_slo) / dt
        in_tps = (totals["input"] - last_in) / dt
        out_tps = (totals["output"] - last_out) / dt
        last_offered, last_achieved, last_slo = totals["offered"], totals["achieved"], totals["slo"]
        last_in, last_out = totals["input"], totals["output"]
        last = now
        await window.sample_load(limiter.inflight, limiter.waiting)
        metrics.set_runtime(inflight=limiter.inflight, c=limiter.limit, waiting=limiter.waiting)
        metrics.set_rates(
            offered_rps=offered_rps,
            achieved_rps=achieved_rps,
            input_tps=in_tps,
            output_tps=out_tps,
            slo_goodput_rps=slo_rps,
        )
        snap = app.state.last_snapshot
        app.state.series.write(
            {
                "ts": now,
                "c": limiter.limit,
                "inflight": limiter.inflight,
                "actual_inflight": limiter.inflight,
                "utilization": limiter.inflight / max(limiter.limit, 1),
                "queue_depth": limiter.waiting,
                "waiting": limiter.waiting,
                "w_t": limiter.w_t,
                "offered_rps": offered_rps,
                "achieved_rps": achieved_rps,
                "slo_goodput_rps": slo_rps,
                "input_tokens_per_sec": in_tps,
                "output_tokens_per_sec": out_tps,
                "ttft_p95_ms": None if snap is None else snap.ttft_p95_ms,
                "backend_ttft_p95_ms": None if snap is None else snap.backend_ttft_p95_ms,
                "queue_p95_ms": None if snap is None else snap.queue_p95_ms,
                "throttle_n": 0 if snap is None else snap.throttle_n,
                "last_action": app.state.controller.last_action,
            }
        )


app = create_app()
