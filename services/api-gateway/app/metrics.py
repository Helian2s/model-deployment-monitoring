from __future__ import annotations

from prometheus_client import Counter, Histogram


REQUESTS = Counter(
    "api_gateway_requests_total",
    "Total API gateway HTTP requests.",
    ["method", "path", "status_class"],
)

REQUEST_DURATION = Histogram(
    "api_gateway_request_duration_seconds",
    "API gateway request duration in seconds.",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

CHAT_COMPLETIONS = Counter(
    "api_gateway_chat_completions_total",
    "Chat completion requests handled by the gateway.",
    ["result"],
)

TRITON_REQUESTS = Counter(
    "api_gateway_triton_requests_total",
    "Triton requests made by the gateway.",
    ["result"],
)

TOKENS = Counter(
    "api_gateway_tokens_total",
    "Token counts observed or estimated by the gateway.",
    ["kind"],
)

HELPDESK_TRIAGE = Counter(
    "api_gateway_helpdesk_triage_total",
    "Helpdesk triage requests handled by the gateway.",
    ["result"],
)

HELPDESK_TRIAGE_DECISIONS = Counter(
    "api_gateway_helpdesk_triage_decisions_total",
    "Validated helpdesk triage decisions by category, priority, and escalation.",
    ["category", "priority", "requires_human"],
)

HELPDESK_TRIAGE_CONFIDENCE = Histogram(
    "api_gateway_helpdesk_triage_confidence",
    "Model-reported confidence for validated helpdesk triage decisions.",
    buckets=(0.0, 0.25, 0.5, 0.7, 0.85, 0.95, 1.0),
)

HELPDESK_TRIAGE_SAFETY_FLAGS = Counter(
    "api_gateway_helpdesk_triage_safety_flags_total",
    "Safety flags emitted by validated helpdesk triage decisions.",
    ["flag"],
)

HELPDESK_TRIAGE_LOW_CONFIDENCE = Counter(
    "api_gateway_helpdesk_triage_low_confidence_total",
    "Validated helpdesk triage decisions below the configured confidence threshold.",
    ["priority", "requires_human"],
)

HELPDESK_TRIAGE_REPAIRS = Counter(
    "api_gateway_helpdesk_triage_repairs_total",
    "Deterministic repairs applied to model output before helpdesk triage validation.",
    ["field", "reason"],
)

GUARDRAILS_REQUESTS = Counter(
    "api_gateway_guardrails_requests_total",
    "Guardrails calls made by the gateway.",
    ["provider", "stage", "result"],
)

GUARDRAILS_DURATION = Histogram(
    "api_gateway_guardrails_duration_seconds",
    "Guardrails request duration in seconds.",
    ["provider", "stage"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

GUARDRAILS_INTERVENTIONS = Counter(
    "api_gateway_guardrails_interventions_total",
    "Guardrails interventions or policy flags observed by the gateway.",
    ["provider", "stage", "action", "reason"],
)
