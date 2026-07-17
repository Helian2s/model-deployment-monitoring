#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


ALLOWED_CATEGORIES = {
    "access",
    "hardware",
    "software",
    "network",
    "email",
    "security",
    "business_application",
    "other",
}

ALLOWED_PRIORITIES = {"P1", "P2", "P3", "P4"}

DEFAULT_SAMPLE = Path("data/helpdesk/samples/helpdesk_triage_sample.jsonl")

TITLE_CANDIDATES = ("title", "subject", "ticket_subject", "summary")
BODY_CANDIDATES = ("body", "description", "ticket_body", "message", "text", "content")
CATEGORY_CANDIDATES = ("category", "type", "queue", "label", "intent")
PRIORITY_CANDIDATES = ("priority", "urgency", "severity")


def clean_text(value: Any, max_length: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_length is not None:
        return text[:max_length]
    return text


def first_present(row: dict[str, Any], columns: Iterable[str]) -> str | None:
    lower_to_key = {key.lower(): key for key in row}
    for column in columns:
        key = lower_to_key.get(column.lower())
        if key is None:
            continue
        value = clean_text(row.get(key))
        if value:
            return value
    return None


def normalize_category(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    lower = text.lower()
    if lower in ALLOWED_CATEGORIES:
        return lower
    if any(token in lower for token in ("password", "login", "access", "account", "mfa")):
        return "access"
    if any(token in lower for token in ("hardware", "laptop", "desktop", "printer", "device")):
        return "hardware"
    if any(token in lower for token in ("network", "vpn", "wifi", "wi-fi", "dns")):
        return "network"
    if any(token in lower for token in ("email", "mail", "calendar", "outlook")):
        return "email"
    if any(token in lower for token in ("security", "phishing", "malware", "virus")):
        return "security"
    if any(token in lower for token in ("crm", "erp", "hris", "payroll", "business")):
        return "business_application"
    if any(token in lower for token in ("software", "application", "install", "update")):
        return "software"
    return "other"


def normalize_priority(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    upper = text.upper()
    if upper in ALLOWED_PRIORITIES:
        return upper
    lower = text.lower()
    if any(token in lower for token in ("critical", "urgent", "sev1", "severity 1", "high")):
        return "P1"
    if any(token in lower for token in ("medium", "sev2", "severity 2")):
        return "P2"
    if any(token in lower for token in ("low", "minor", "sev3", "severity 3")):
        return "P3"
    if lower in {"0", "1"}:
        return "P1"
    if lower == "2":
        return "P2"
    if lower == "3":
        return "P3"
    if lower in {"4", "5"}:
        return "P4"
    return None


def routing_queue_for_category(category: str | None) -> str | None:
    return {
        "access": "identity_access",
        "hardware": "endpoint_support",
        "software": "endpoint_support",
        "network": "network_operations",
        "email": "messaging_collaboration",
        "security": "security_operations",
        "business_application": "business_apps",
        "other": "service_desk_l1",
    }.get(category or "")


def normalized_record(
    *,
    row_id: str,
    source: str,
    row: dict[str, Any],
    title_column: str | None,
    body_column: str | None,
    category_column: str | None,
    priority_column: str | None,
) -> dict[str, Any] | None:
    title = clean_text(row.get(title_column)) if title_column else None
    body = clean_text(row.get(body_column)) if body_column else None
    title = title or first_present(row, TITLE_CANDIDATES)
    body = body or first_present(row, BODY_CANDIDATES)
    if not title and body:
        title = body[:120]
    if not body and title:
        body = title
    if not title or not body:
        return None

    source_label = clean_text(row.get(category_column)) if category_column else None
    source_priority = clean_text(row.get(priority_column)) if priority_column else None
    category = normalize_category(source_label or first_present(row, CATEGORY_CANDIDATES))
    priority = normalize_priority(source_priority or first_present(row, PRIORITY_CANDIDATES))
    expected: dict[str, Any] = {}
    if category:
        expected["category"] = category
        expected["routing_queue"] = routing_queue_for_category(category)
    if priority:
        expected["priority"] = priority
    if source_label:
        expected["source_label"] = source_label
    if source_priority:
        expected["source_priority"] = source_priority

    record: dict[str, Any] = {
        "id": row_id,
        "source": source,
        "title": title[:300],
        "body": body[:8000],
    }
    if expected:
        record["expected"] = expected
    return record


def write_jsonl(records: Iterable[dict[str, Any]], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
            count += 1
    return count


def iter_csv_records(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    with Path(args.input).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            record = normalized_record(
                row_id=f"{args.source}-{index}",
                source=args.source,
                row=row,
                title_column=args.title_column,
                body_column=args.body_column,
                category_column=args.category_column,
                priority_column=args.priority_column,
            )
            if record:
                yield record


def iter_huggingface_records(args: argparse.Namespace) -> Iterable[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "The 'datasets' package is required for Hugging Face ingestion. "
            "Install it with: python -m pip install datasets"
        ) from exc

    dataset = load_dataset(args.dataset, split=args.split, token=args.token)
    source = args.source or args.dataset.replace("/", "__")
    limit = args.limit or len(dataset)
    for index, row in enumerate(dataset.select(range(min(limit, len(dataset)))), start=1):
        record = normalized_record(
            row_id=f"{source}-{index}",
            source=source,
            row=dict(row),
            title_column=args.title_column,
            body_column=args.body_column,
            category_column=args.category_column,
            priority_column=args.priority_column,
        )
        if record:
            yield record


def copy_sample(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(DEFAULT_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return sum(1 for line in output.read_text(encoding="utf-8").splitlines() if line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize helpdesk datasets into the NCP-GENL JSONL format."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("sample", help="Copy the checked-in sample set.")
    sample.add_argument(
        "--output",
        default="data/helpdesk/normalized/helpdesk_triage_sample.jsonl",
        help="Output JSONL path.",
    )

    csv_parser = subparsers.add_parser("csv", help="Convert a local CSV file.")
    csv_parser.add_argument("--input", required=True, help="Input CSV path.")
    csv_parser.add_argument("--output", required=True, help="Output JSONL path.")
    csv_parser.add_argument("--source", default="csv", help="Source name for records.")
    csv_parser.add_argument("--title-column", default=None)
    csv_parser.add_argument("--body-column", default=None)
    csv_parser.add_argument("--category-column", default=None)
    csv_parser.add_argument("--priority-column", default=None)

    hf = subparsers.add_parser("huggingface", help="Convert a Hugging Face dataset.")
    hf.add_argument("--dataset", required=True, help="Dataset id, for example owner/name.")
    hf.add_argument("--split", default="train")
    hf.add_argument("--output", required=True, help="Output JSONL path.")
    hf.add_argument("--source", default=None, help="Override source name.")
    hf.add_argument("--limit", type=int, default=1000)
    hf.add_argument("--token", default=None, help="Optional Hugging Face token.")
    hf.add_argument("--title-column", default=None)
    hf.add_argument("--body-column", default=None)
    hf.add_argument("--category-column", default=None)
    hf.add_argument("--priority-column", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "sample":
        count = copy_sample(args)
    elif args.command == "csv":
        count = write_jsonl(iter_csv_records(args), Path(args.output))
    elif args.command == "huggingface":
        count = write_jsonl(iter_huggingface_records(args), Path(args.output))
    else:
        raise AssertionError(args.command)

    print(json.dumps({"output": args.output, "records": count}, sort_keys=True))
    return 0 if count else 1


if __name__ == "__main__":
    sys.exit(main())
