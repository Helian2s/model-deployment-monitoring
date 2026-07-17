from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    stream: bool = False
    user: str | None = None
    metadata: dict[str, Any] | None = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str | None = None


class TokenUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: TokenUsage | None = None


HelpdeskCategory = Literal[
    "access",
    "hardware",
    "software",
    "network",
    "email",
    "security",
    "business_application",
    "other",
]

HelpdeskPriority = Literal["P1", "P2", "P3", "P4"]

HelpdeskRoutingQueue = Literal[
    "service_desk_l1",
    "identity_access",
    "endpoint_support",
    "network_operations",
    "messaging_collaboration",
    "security_operations",
    "business_apps",
]

HelpdeskSafetyFlag = Literal[
    "none",
    "possible_pii",
    "possible_secret",
    "prompt_injection",
    "security_sensitive",
    "policy_or_legal",
]


class HelpdeskTicketHistoryItem(BaseModel):
    role: Literal["requester", "agent", "system"] = "requester"
    content: str = Field(min_length=1, max_length=2000)
    timestamp: str | None = Field(default=None, max_length=64)


class HelpdeskTriageRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    requester_department: str | None = Field(default=None, max_length=120)
    requester_role: str | None = Field(default=None, max_length=120)
    product_or_service: str | None = Field(default=None, max_length=160)
    business_impact: str | None = Field(default=None, max_length=500)
    history: list[HelpdeskTicketHistoryItem] = Field(default_factory=list, max_length=10)
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class HelpdeskTriageDecision(BaseModel):
    category: HelpdeskCategory
    priority: HelpdeskPriority
    routing_queue: HelpdeskRoutingQueue
    summary: str = Field(min_length=1, max_length=500)
    recommended_action: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human: bool
    safety_flags: list[HelpdeskSafetyFlag] = Field(min_length=1, max_length=5)


class HelpdeskTriageResponse(BaseModel):
    id: str
    object: Literal["helpdesk.triage"] = "helpdesk.triage"
    created: int
    model: str
    decision: HelpdeskTriageDecision
    usage: TokenUsage | None = None


class ErrorResponse(BaseModel):
    error: dict[str, Any]
