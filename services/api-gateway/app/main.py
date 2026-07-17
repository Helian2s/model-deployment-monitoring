from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import Settings
from .metrics import (
    CHAT_COMPLETIONS,
    GUARDRAILS_DURATION,
    GUARDRAILS_INTERVENTIONS,
    GUARDRAILS_REQUESTS,
    HELPDESK_TRIAGE,
    HELPDESK_TRIAGE_CONFIDENCE,
    HELPDESK_TRIAGE_DECISIONS,
    HELPDESK_TRIAGE_LOW_CONFIDENCE,
    HELPDESK_TRIAGE_REPAIRS,
    HELPDESK_TRIAGE_SAFETY_FLAGS,
    REQUEST_DURATION,
    REQUESTS,
    TOKENS,
    TRITON_REQUESTS,
)
from .models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    HelpdeskTriageRequest,
    HelpdeskTriageResponse,
    TokenUsage,
)
from .helpdesk import (
    HelpdeskOutputParseError,
    HelpdeskSafetyBlock,
    apply_helpdesk_decision_policy,
    build_helpdesk_triage_messages,
    enforce_helpdesk_input_policy,
    merge_safety_flags,
    parse_helpdesk_triage_output_with_repairs,
)
from .guardrails import GuardrailsClientError, NemoGuardrailsClient
from .prompting import estimate_token_count, messages_to_qwen_prompt, strip_echoed_prompt
from .rate_limit import FixedWindowRateLimiter
from .triton import TritonClientError, TritonGenerateClient

logger = logging.getLogger("api_gateway")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(
    settings: Settings | None = None,
    triton_client: TritonGenerateClient | None = None,
    guardrails_client: NemoGuardrailsClient | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    triton_client = triton_client or TritonGenerateClient(
        settings.triton_base_url,
        settings.triton_model_name,
        settings.triton_timeout_seconds,
    )
    guardrails_client = guardrails_client or NemoGuardrailsClient(
        settings.guardrails_base_url,
        settings.guardrails_timeout_seconds,
    )
    rate_limiter = FixedWindowRateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(
        title="NCP-GENL API Gateway",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.triton_client = triton_client
    app.state.guardrails_client = guardrails_client

    async def generate_raw_chat_completion(
        body: ChatCompletionRequest,
        *,
        record_chat_metric: bool,
    ) -> ChatCompletionResponse:
        if body.stream:
            raise HTTPException(
                status_code=400,
                detail="Streaming responses are not implemented in this gateway yet",
            )

        max_tokens = body.max_tokens or settings.default_max_tokens
        if max_tokens > settings.max_tokens_limit:
            raise HTTPException(
                status_code=400,
                detail=f"max_tokens must be <= {settings.max_tokens_limit}",
            )

        prompt = messages_to_qwen_prompt(body.messages)
        if len(prompt) > settings.max_prompt_chars:
            raise HTTPException(
                status_code=400,
                detail=f"Prompt exceeds {settings.max_prompt_chars} characters",
            )

        sampling_parameters = {
            "max_tokens": max_tokens,
            "temperature": (
                settings.default_temperature
                if body.temperature is None
                else body.temperature
            ),
            "top_p": settings.default_top_p if body.top_p is None else body.top_p,
        }

        try:
            TRITON_REQUESTS.labels("started").inc()
            result = await triton_client.generate(prompt, sampling_parameters)
        except TritonClientError as exc:
            TRITON_REQUESTS.labels("failed").inc()
            if record_chat_metric:
                CHAT_COMPLETIONS.labels("failed").inc()
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        TRITON_REQUESTS.labels("succeeded").inc()
        if record_chat_metric:
            CHAT_COMPLETIONS.labels("succeeded").inc()

        content = strip_echoed_prompt(result.text, prompt)
        prompt_tokens = result.prompt_tokens or estimate_token_count(prompt)
        output_tokens = result.output_tokens or estimate_token_count(content)
        total_tokens = prompt_tokens + output_tokens
        TOKENS.labels("prompt").inc(prompt_tokens)
        TOKENS.labels("completion").inc(output_tokens)

        model = body.model or settings.triton_model_name
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason=result.finish_reason or "stop",
                )
            ],
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
        )

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        response: Response | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - started
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            status_class = f"{status_code // 100}xx"
            REQUESTS.labels(request.method, path, status_class).inc()
            REQUEST_DURATION.labels(request.method, path).observe(duration)
            if response is not None:
                response.headers["x-request-id"] = request_id
            logger.info(
                json.dumps(
                    {
                        "event": "request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 2),
                    },
                    separators=(",", ":"),
                )
            )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.detail,
                    "type": "gateway_error",
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers=getattr(exc, "headers", None),
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        if settings.require_api_key and not settings.api_keys:
            raise HTTPException(
                status_code=503,
                detail="API key enforcement is enabled but no API keys are configured",
            )
        if not await triton_client.is_ready():
            raise HTTPException(status_code=503, detail="Triton is not ready")
        return {"status": "ready", "triton_model": settings.triton_model_name}

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    async def chat_completions(
        body: ChatCompletionRequest, request: Request
    ) -> ChatCompletionResponse:
        principal = _authorize(request, settings)
        decision = rate_limiter.check(principal)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"retry-after": str(decision.retry_after_seconds)},
            )

        return await generate_raw_chat_completion(body, record_chat_metric=True)

    @app.post("/internal/v1/chat/completions", response_model=ChatCompletionResponse)
    async def internal_chat_completions(
        body: ChatCompletionRequest,
        request: Request,
    ) -> ChatCompletionResponse:
        if not settings.enable_internal_model_endpoint:
            raise HTTPException(status_code=404, detail="Not found")
        _authorize(request, settings)
        return await generate_raw_chat_completion(body, record_chat_metric=False)

    @app.post("/v1/helpdesk/triage", response_model=HelpdeskTriageResponse)
    async def helpdesk_triage(
        body: HelpdeskTriageRequest, request: Request
    ) -> HelpdeskTriageResponse:
        principal = _authorize(request, settings)
        decision = rate_limiter.check(principal)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"retry-after": str(decision.retry_after_seconds)},
            )

        max_tokens = body.max_tokens or settings.helpdesk_default_max_tokens
        if max_tokens > settings.max_tokens_limit:
            raise HTTPException(
                status_code=400,
                detail=f"max_tokens must be <= {settings.max_tokens_limit}",
            )

        try:
            gateway_safety_flags = enforce_helpdesk_input_policy(body)
        except HelpdeskSafetyBlock as exc:
            GUARDRAILS_INTERVENTIONS.labels(
                "gateway", "input", "blocked", exc.reason
            ).inc()
            HELPDESK_TRIAGE.labels("blocked").inc()
            raise HTTPException(
                status_code=403,
                detail=f"Helpdesk ticket blocked by gateway safety policy: {exc.reason}",
            ) from exc

        for flag in gateway_safety_flags:
            GUARDRAILS_INTERVENTIONS.labels(
                "gateway", "input", "flagged", flag
            ).inc()

        messages = build_helpdesk_triage_messages(body)
        prompt = messages_to_qwen_prompt(messages)
        if len(prompt) > settings.max_prompt_chars:
            raise HTTPException(
                status_code=400,
                detail=f"Prompt exceeds {settings.max_prompt_chars} characters",
            )

        sampling_parameters = {
            "max_tokens": max_tokens,
            "temperature": (
                settings.helpdesk_default_temperature
                if body.temperature is None
                else body.temperature
            ),
            "top_p": settings.helpdesk_default_top_p if body.top_p is None else body.top_p,
        }

        content: str | None = None
        usage: TokenUsage | None = None
        if settings.helpdesk_guardrails_enabled:
            started = time.perf_counter()
            GUARDRAILS_REQUESTS.labels("nemo", "chat", "started").inc()
            try:
                guardrails_result = await guardrails_client.chat_completion(
                    model=settings.triton_model_name,
                    messages=messages,
                    sampling_parameters=sampling_parameters,
                    config_id=settings.helpdesk_guardrails_config_id,
                )
            except GuardrailsClientError as exc:
                GUARDRAILS_REQUESTS.labels("nemo", "chat", "failed").inc()
                HELPDESK_TRIAGE.labels("guardrails_failed").inc()
                if settings.guardrails_fail_closed:
                    raise HTTPException(
                        status_code=exc.status_code,
                        detail=str(exc),
                    ) from exc
                logger.warning(
                    json.dumps(
                        {
                            "event": "guardrails_fallback",
                            "reason": str(exc),
                        },
                        separators=(",", ":"),
                    )
                )
            else:
                GUARDRAILS_REQUESTS.labels("nemo", "chat", "succeeded").inc()
                content = guardrails_result.text
                usage = guardrails_result.usage
                if guardrails_result.guardrails_data:
                    GUARDRAILS_INTERVENTIONS.labels(
                        "nemo", "chat", "observed", "guardrails_data"
                    ).inc()
            finally:
                GUARDRAILS_DURATION.labels("nemo", "chat").observe(
                    time.perf_counter() - started
                )
        if content is None:
            try:
                TRITON_REQUESTS.labels("started").inc()
                result = await triton_client.generate(prompt, sampling_parameters)
            except TritonClientError as exc:
                TRITON_REQUESTS.labels("failed").inc()
                HELPDESK_TRIAGE.labels("failed").inc()
                raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

            TRITON_REQUESTS.labels("succeeded").inc()
            content = strip_echoed_prompt(result.text, prompt)
            prompt_tokens = result.prompt_tokens or estimate_token_count(prompt)
            output_tokens = result.output_tokens or estimate_token_count(content)
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=output_tokens,
                total_tokens=prompt_tokens + output_tokens,
            )

        try:
            triage_decision, repairs = parse_helpdesk_triage_output_with_repairs(
                content
            )
        except HelpdeskOutputParseError as exc:
            HELPDESK_TRIAGE.labels("invalid_model_output").inc()
            raise HTTPException(
                status_code=502,
                detail="Model output failed helpdesk triage schema validation",
            ) from exc

        triage_decision, policy_repairs = apply_helpdesk_decision_policy(
            body, triage_decision
        )
        repairs.extend(policy_repairs)

        for field, reason in repairs:
            HELPDESK_TRIAGE_REPAIRS.labels(field, reason).inc()

        triage_decision = triage_decision.model_copy(
            update={
                "safety_flags": merge_safety_flags(
                    triage_decision.safety_flags, gateway_safety_flags
                )
            }
        )

        HELPDESK_TRIAGE.labels("succeeded").inc()
        HELPDESK_TRIAGE_DECISIONS.labels(
            triage_decision.category,
            triage_decision.priority,
            str(triage_decision.requires_human).lower(),
        ).inc()
        HELPDESK_TRIAGE_CONFIDENCE.observe(triage_decision.confidence)
        if triage_decision.confidence < settings.helpdesk_low_confidence_threshold:
            HELPDESK_TRIAGE_LOW_CONFIDENCE.labels(
                triage_decision.priority,
                str(triage_decision.requires_human).lower(),
            ).inc()
        for flag in triage_decision.safety_flags:
            HELPDESK_TRIAGE_SAFETY_FLAGS.labels(flag).inc()

        prompt_tokens = usage.prompt_tokens or estimate_token_count(prompt)
        output_tokens = usage.completion_tokens or estimate_token_count(content)
        total_tokens = usage.total_tokens or (prompt_tokens + output_tokens)
        TOKENS.labels("prompt").inc(prompt_tokens)
        TOKENS.labels("completion").inc(output_tokens)

        return HelpdeskTriageResponse(
            id=f"triage-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=settings.triton_model_name,
            decision=triage_decision,
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=output_tokens,
                total_tokens=total_tokens,
            ),
        )

    return app


def _authorize(request: Request, settings: Settings) -> str:
    if not settings.require_api_key:
        return request.client.host if request.client else "anonymous"

    if not settings.api_keys:
        raise HTTPException(
            status_code=503,
            detail="API key enforcement is enabled but no API keys are configured",
        )

    candidate = request.headers.get("x-api-key")
    authorization = request.headers.get("authorization", "")
    if not candidate and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()

    if not candidate or not any(
        secrets.compare_digest(candidate, api_key) for api_key in settings.api_keys
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return candidate


app = create_app()
