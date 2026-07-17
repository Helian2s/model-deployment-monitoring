import json

import pytest

from app.helpdesk import (
    HelpdeskOutputParseError,
    apply_helpdesk_decision_policy,
    build_helpdesk_triage_prompt,
    extract_first_json_object,
    parse_helpdesk_triage_output,
    parse_helpdesk_triage_output_with_repairs,
)
from app.models import HelpdeskTriageDecision, HelpdeskTriageRequest


def test_build_helpdesk_triage_prompt_contains_contract_and_ticket() -> None:
    prompt = build_helpdesk_triage_prompt(
        HelpdeskTriageRequest(
            title="Laptop battery swelling",
            body="The case is bulging and the laptop gets hot.",
            requester_department="Engineering",
            business_impact="Developer cannot safely use workstation.",
        )
    )

    assert "Return exactly one JSON object" in prompt
    assert "Allowed category values" in prompt
    assert "Laptop battery swelling" in prompt
    assert "P1:" in prompt
    assert prompt.endswith("<|im_start|>assistant\n")


def test_extract_first_json_object_ignores_markdown_wrapper() -> None:
    payload = {"category": "network", "confidence": 0.8}
    text = "```json\n" + json.dumps(payload) + "\n```"

    assert extract_first_json_object(text) == payload


def test_parse_helpdesk_triage_output_validates_schema() -> None:
    decision = parse_helpdesk_triage_output(
        json.dumps(
            {
                "category": "network",
                "priority": "P3",
                "routing_queue": "network_operations",
                "summary": "VPN connects but internal services time out.",
                "recommended_action": "Check VPN profile and collect traceroute details.",
                "confidence": 0.76,
                "requires_human": True,
                "safety_flags": ["none"],
            }
        )
    )

    assert decision.category == "network"
    assert decision.priority == "P3"


def test_parse_helpdesk_triage_output_rejects_unknown_category() -> None:
    with pytest.raises(HelpdeskOutputParseError):
        parse_helpdesk_triage_output(
            json.dumps(
                {
                    "category": "made_up",
                    "priority": "P3",
                    "routing_queue": "service_desk_l1",
                    "summary": "Unclear issue.",
                    "recommended_action": "Ask a clarifying question.",
                    "confidence": 0.2,
                    "requires_human": True,
                    "safety_flags": ["none"],
                }
            )
        )


def test_parse_helpdesk_triage_output_repairs_category_routing_queue() -> None:
    decision, repairs = parse_helpdesk_triage_output_with_repairs(
        json.dumps(
            {
                "category": "hardware",
                "priority": "P2",
                "routing_queue": "hardware",
                "summary": "Laptop battery is swelling.",
                "recommended_action": "Replace the laptop and inspect the battery.",
                "confidence": 0.9,
                "requires_human": True,
                "safety_flags": ["none"],
            }
        )
    )

    assert decision.routing_queue == "endpoint_support"
    assert ("routing_queue", "category_default") in repairs


def test_apply_helpdesk_decision_policy_corrects_payroll_access_priority() -> None:
    decision, repairs = apply_helpdesk_decision_policy(
        HelpdeskTriageRequest(
            title="Cannot access payroll portal after MFA reset",
            body="Payroll closes today and I cannot submit approvals.",
            requester_department="Finance",
        ),
        HelpdeskTriageDecision(
            category="security",
            priority="P1",
            routing_queue="security_operations",
            summary="Payroll portal access issue.",
            recommended_action="Investigate MFA reset.",
            confidence=0.95,
            requires_human=True,
            safety_flags=["none"],
        ),
    )

    assert decision.priority == "P2"
    assert decision.confidence == 0.79
    assert ("priority", "policy_override") in repairs


def test_apply_helpdesk_decision_policy_corrects_low_impact_question() -> None:
    decision, repairs = apply_helpdesk_decision_policy(
        HelpdeskTriageRequest(
            title="Need help choosing the right form",
            body="Which form should I use to request a new shared mailbox?",
        ),
        HelpdeskTriageDecision(
            category="security",
            priority="P1",
            routing_queue="security_operations",
            summary="User needs help choosing a form.",
            recommended_action="Route to service desk.",
            confidence=0.95,
            requires_human=True,
            safety_flags=["none"],
        ),
    )

    assert decision.priority == "P4"
    assert decision.confidence == 0.79
    assert ("priority", "policy_override") in repairs
