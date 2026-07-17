from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _float_from_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _api_keys_from_env() -> tuple[str, ...]:
    values: list[str] = []
    single_key = os.getenv("API_GATEWAY_API_KEY", "").strip()
    if single_key:
        values.append(single_key)

    for key in os.getenv("API_GATEWAY_API_KEYS", "").split(","):
        key = key.strip()
        if key:
            values.append(key)

    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class Settings:
    service_name: str = "ncp-genl-api-gateway"
    triton_base_url: str = "http://triton:8000"
    triton_model_name: str = "vllm_model"
    triton_timeout_seconds: float = 90.0
    require_api_key: bool = False
    api_keys: tuple[str, ...] = ()
    rate_limit_per_minute: int = 60
    max_prompt_chars: int = 12000
    default_max_tokens: int = 256
    max_tokens_limit: int = 1024
    default_temperature: float = 0.2
    default_top_p: float = 0.95
    helpdesk_default_max_tokens: int = 384
    helpdesk_default_temperature: float = 0.0
    helpdesk_default_top_p: float = 0.9
    helpdesk_low_confidence_threshold: float = 0.7
    helpdesk_guardrails_enabled: bool = False
    helpdesk_guardrails_config_id: str = "self-check"
    guardrails_base_url: str = "http://nemo-guardrails:7331"
    guardrails_timeout_seconds: float = 120.0
    guardrails_fail_closed: bool = True
    enable_internal_model_endpoint: bool = False
    environment: str = "local"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            service_name=os.getenv("SERVICE_NAME", cls.service_name),
            triton_base_url=os.getenv("TRITON_BASE_URL", cls.triton_base_url).rstrip("/"),
            triton_model_name=os.getenv("TRITON_MODEL_NAME", cls.triton_model_name),
            triton_timeout_seconds=_float_from_env(
                "TRITON_TIMEOUT_SECONDS", cls.triton_timeout_seconds
            ),
            require_api_key=_bool_from_env(
                "API_GATEWAY_REQUIRE_API_KEY", cls.require_api_key
            ),
            api_keys=_api_keys_from_env(),
            rate_limit_per_minute=_int_from_env(
                "API_GATEWAY_RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute
            ),
            max_prompt_chars=_int_from_env("MAX_PROMPT_CHARS", cls.max_prompt_chars),
            default_max_tokens=_int_from_env("DEFAULT_MAX_TOKENS", cls.default_max_tokens),
            max_tokens_limit=_int_from_env("MAX_TOKENS_LIMIT", cls.max_tokens_limit),
            default_temperature=_float_from_env(
                "DEFAULT_TEMPERATURE", cls.default_temperature
            ),
            default_top_p=_float_from_env("DEFAULT_TOP_P", cls.default_top_p),
            helpdesk_default_max_tokens=_int_from_env(
                "HELPDESK_DEFAULT_MAX_TOKENS", cls.helpdesk_default_max_tokens
            ),
            helpdesk_default_temperature=_float_from_env(
                "HELPDESK_DEFAULT_TEMPERATURE", cls.helpdesk_default_temperature
            ),
            helpdesk_default_top_p=_float_from_env(
                "HELPDESK_DEFAULT_TOP_P", cls.helpdesk_default_top_p
            ),
            helpdesk_low_confidence_threshold=_float_from_env(
                "HELPDESK_LOW_CONFIDENCE_THRESHOLD",
                cls.helpdesk_low_confidence_threshold,
            ),
            helpdesk_guardrails_enabled=_bool_from_env(
                "HELPDESK_GUARDRAILS_ENABLED", cls.helpdesk_guardrails_enabled
            ),
            helpdesk_guardrails_config_id=os.getenv(
                "HELPDESK_GUARDRAILS_CONFIG_ID", cls.helpdesk_guardrails_config_id
            ),
            guardrails_base_url=os.getenv(
                "NEMO_GUARDRAILS_BASE_URL", cls.guardrails_base_url
            ).rstrip("/"),
            guardrails_timeout_seconds=_float_from_env(
                "NEMO_GUARDRAILS_TIMEOUT_SECONDS", cls.guardrails_timeout_seconds
            ),
            guardrails_fail_closed=_bool_from_env(
                "GUARDRAILS_FAIL_CLOSED", cls.guardrails_fail_closed
            ),
            enable_internal_model_endpoint=_bool_from_env(
                "ENABLE_INTERNAL_MODEL_ENDPOINT", cls.enable_internal_model_endpoint
            ),
            environment=os.getenv("ENVIRONMENT", cls.environment),
        )
