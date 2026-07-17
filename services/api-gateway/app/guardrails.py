from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .models import ChatMessage, TokenUsage


class GuardrailsClientError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GuardrailsChatResult:
    text: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    guardrails_data: dict[str, Any] | None = None


class NemoGuardrailsClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def is_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/v1/health/ready")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        sampling_parameters: dict[str, Any],
        config_id: str,
    ) -> GuardrailsChatResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            "guardrails": {"config_id": config_id},
            "stream": False,
            "max_tokens": sampling_parameters.get("max_tokens"),
            "temperature": sampling_parameters.get("temperature"),
            "top_p": sampling_parameters.get("top_p"),
        }
        url = f"{self._base_url}/v1/guardrail/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise GuardrailsClientError(
                "NeMo Guardrails request timed out", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            raise GuardrailsClientError(
                "NeMo Guardrails is unavailable", status_code=503
            ) from exc

        if response.status_code >= 400:
            raise GuardrailsClientError(
                f"NeMo Guardrails returned HTTP {response.status_code}: {response.text[:500]}",
                status_code=502,
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise GuardrailsClientError("NeMo Guardrails response contained no choices")
        first_choice = choices[0]
        message = first_choice.get("message") or {}
        content = message.get("content")
        if content is None:
            raise GuardrailsClientError("NeMo Guardrails response contained no content")

        usage_data = data.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens"),
            completion_tokens=usage_data.get("completion_tokens"),
            total_tokens=usage_data.get("total_tokens"),
        )
        return GuardrailsChatResult(
            text=str(content),
            finish_reason=first_choice.get("finish_reason"),
            usage=usage,
            guardrails_data=data.get("guardrails_data"),
        )
