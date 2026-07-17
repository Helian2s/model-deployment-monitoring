#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TRIAGE_FIELDS = (
    "category",
    "priority",
    "routing_queue",
    "summary",
    "recommended_action",
    "confidence",
    "requires_human",
    "safety_flags",
)


def load_jsonl(path: Path, limit: int | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record["_line_number"] = line_number
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
    return records


def percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def request_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": record["title"],
        "body": record["body"],
    }
    for field in (
        "requester_department",
        "requester_role",
        "product_or_service",
        "business_impact",
        "history",
    ):
        value = record.get(field)
        if value:
            payload[field] = value
    return payload


def call_triage(
    *,
    index: int,
    record: dict[str, Any],
    url: str,
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(request_payload(record)).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-request-id": f"helpdesk-eval-{index}",
            **({"x-api-key": api_key} if api_key else {}),
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
            latency = time.perf_counter() - started
            data = json.loads(response_body)
            decision = data.get("decision") or {}
            missing_fields = [field for field in TRIAGE_FIELDS if field not in decision]
            return {
                "ok": response.status == 200 and not missing_fields,
                "id": record.get("id"),
                "status": response.status,
                "latency_seconds": latency,
                "decision": decision,
                "missing_fields": missing_fields,
                "expected": record.get("expected") or {},
            }
    except urllib.error.HTTPError as exc:
        latency = time.perf_counter() - started
        return {
            "ok": False,
            "id": record.get("id"),
            "status": exc.code,
            "latency_seconds": latency,
            "error": exc.read().decode("utf-8", errors="replace")[:500],
            "expected": record.get("expected") or {},
        }
    except Exception as exc:
        latency = time.perf_counter() - started
        return {
            "ok": False,
            "id": record.get("id"),
            "status": 0,
            "latency_seconds": latency,
            "error": repr(exc)[:500],
            "expected": record.get("expected") or {},
        }


def accuracy(results: list[dict[str, Any]], field: str) -> dict[str, Any]:
    comparable = [
        result
        for result in results
        if result.get("ok")
        and field in result.get("expected", {})
        and field in result.get("decision", {})
    ]
    correct = [
        result
        for result in comparable
        if result["expected"][field] == result["decision"][field]
    ]
    return {
        "field": field,
        "comparable": len(comparable),
        "correct": len(correct),
        "accuracy": round(len(correct) / len(comparable), 4) if comparable else None,
    }


def summarize(
    *,
    dataset: Path,
    url: str,
    concurrency: int,
    results: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    latencies = [float(result["latency_seconds"]) for result in results]
    successes = [result for result in results if result.get("ok")]
    failures = [result for result in results if not result.get("ok")]
    status_counts = Counter(str(result.get("status")) for result in results)
    category_counts = Counter(
        result["decision"].get("category") for result in successes if result.get("decision")
    )
    priority_counts = Counter(
        result["decision"].get("priority") for result in successes if result.get("decision")
    )
    safety_flags = Counter(
        flag
        for result in successes
        for flag in result.get("decision", {}).get("safety_flags", [])
    )
    confidences = [
        float(result["decision"]["confidence"])
        for result in successes
        if isinstance(result.get("decision", {}).get("confidence"), (int, float))
    ]
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": str(dataset),
        "url": url,
        "requests": len(results),
        "concurrency": concurrency,
        "succeeded": len(successes),
        "failed": len(failures),
        "status_counts": dict(sorted(status_counts.items())),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "requests_per_second": round(len(results) / elapsed_seconds, 3)
        if elapsed_seconds
        else None,
        "latency_seconds": {
            "min": round(min(latencies), 3) if latencies else None,
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "p50": round(percentile(latencies, 50), 3) if latencies else None,
            "p95": round(percentile(latencies, 95), 3) if latencies else None,
            "p99": round(percentile(latencies, 99), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
        },
        "confidence": {
            "mean": round(statistics.fmean(confidences), 3) if confidences else None,
            "min": round(min(confidences), 3) if confidences else None,
            "max": round(max(confidences), 3) if confidences else None,
        },
        "accuracy": {
            "category": accuracy(results, "category"),
            "priority": accuracy(results, "priority"),
            "routing_queue": accuracy(results, "routing_queue"),
        },
        "decision_distribution": {
            "category": dict(sorted(category_counts.items())),
            "priority": dict(sorted(priority_counts.items())),
            "safety_flags": dict(sorted(safety_flags.items())),
        },
        "failures": failures[:10],
    }


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    accuracy_rows = []
    for field, item in summary["accuracy"].items():
        accuracy_value = item["accuracy"]
        accuracy_text = "n/a" if accuracy_value is None else f"{accuracy_value:.2%}"
        accuracy_rows.append(
            f"| {field} | {item['correct']} | {item['comparable']} | {accuracy_text} |"
        )

    lines = [
        "# Helpdesk Triage Evaluation",
        "",
        f"- Created: `{summary['created_at']}`",
        f"- Dataset: `{summary['dataset']}`",
        f"- Requests: `{summary['requests']}`",
        f"- Success / failed: `{summary['succeeded']}` / `{summary['failed']}`",
        f"- Throughput: `{summary['requests_per_second']}` req/s",
        f"- p95 latency: `{summary['latency_seconds']['p95']}` seconds",
        f"- Mean confidence: `{summary['confidence']['mean']}`",
        "",
        "| Field | Correct | Comparable | Accuracy |",
        "| --- | ---: | ---: | ---: |",
        *accuracy_rows,
        "",
        "## Decision Distribution",
        "",
        "```json",
        json.dumps(summary["decision_distribution"], indent=2, sort_keys=True),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate the deployed helpdesk triage endpoint."
    )
    parser.add_argument(
        "--dataset",
        default="data/helpdesk/samples/helpdesk_triage_sample.jsonl",
        help="Normalized helpdesk JSONL path.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8088/v1/helpdesk/triage",
        help="Helpdesk triage endpoint URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("API_GATEWAY_API_KEY"),
        help="API key. Defaults to API_GATEWAY_API_KEY.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory for JSON and Markdown evaluation reports.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    dataset = Path(args.dataset)
    records = load_jsonl(dataset, args.limit)
    if not records:
        print(f"No records loaded from {dataset}", file=sys.stderr)
        return 1

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(
                call_triage,
                index=index,
                record=record,
                url=args.url,
                api_key=args.api_key,
                timeout=args.timeout,
            )
            for index, record in enumerate(records, start=1)
        ]
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started

    summary = summarize(
        dataset=dataset,
        url=args.url,
        concurrency=args.concurrency,
        results=results,
        elapsed_seconds=elapsed,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"helpdesk-triage-eval-{stamp}.json"
    markdown_path = output_dir / f"helpdesk-triage-eval-{stamp}.md"
    json_path.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(summary, markdown_path)

    print(
        json.dumps(
            {
                "summary": summary,
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
