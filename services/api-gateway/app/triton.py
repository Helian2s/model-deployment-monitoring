from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class TritonClientError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class TritonGenerateResult:
    text: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None


def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return _first(value[0])
    return value


def _optional_int(value: Any) -> int | None:
    value = _first(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    value = _first(value)
    if value is None:
        return None
    return str(value)


class TritonGenerateClient:
    def __init__(self, base_url: str, model_name: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = timeout_seconds

    async def is_ready(self) -> bool:
        url = f"{self._base_url}/v2/health/ready"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def generate(
        self, prompt: str, sampling_parameters: dict[str, Any]
    ) -> TritonGenerateResult:
        url = f"{self._base_url}/v2/models/{self._model_name}/generate"
        payload = {
            "text_input": prompt,
            "parameters": sampling_parameters,
            "return_finish_reason": True,
            "return_num_input_tokens": True,
            "return_num_output_tokens": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise TritonClientError("Triton request timed out", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise TritonClientError("Triton is unavailable", status_code=503) from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            raise TritonClientError(
                f"Triton returned HTTP {response.status_code}: {detail}",
                status_code=502,
            )

        data = response.json()
        text = _first(data.get("text_output"))
        if text is None:
            raise TritonClientError("Triton response did not contain text_output")

        return TritonGenerateResult(
            text=str(text),
            finish_reason=_optional_str(data.get("finish_reason")),
            prompt_tokens=_optional_int(data.get("num_input_tokens")),
            output_tokens=_optional_int(data.get("num_output_tokens")),
        )
