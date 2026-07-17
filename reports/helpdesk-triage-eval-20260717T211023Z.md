# Helpdesk Triage Evaluation

- Created: `2026-07-17T21:10:23.091639+00:00`
- Dataset: `data/helpdesk/samples/helpdesk_triage_sample.jsonl`
- Requests: `8`
- Success / failed: `8` / `0`
- Throughput: `0.868` req/s
- p95 latency: `1.292` seconds
- Mean confidence: `0.83`

| Field | Correct | Comparable | Accuracy |
| --- | ---: | ---: | ---: |
| category | 5 | 8 | 62.50% |
| priority | 8 | 8 | 100.00% |
| routing_queue | 5 | 8 | 62.50% |

## Decision Distribution

```json
{
  "category": {
    "business_application": 2,
    "hardware": 1,
    "network": 1,
    "security": 2,
    "software": 2
  },
  "priority": {
    "P2": 4,
    "P3": 2,
    "P4": 2
  },
  "safety_flags": {
    "none": 7,
    "security_sensitive": 1
  }
}
```
