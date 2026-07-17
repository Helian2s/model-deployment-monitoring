# Helpdesk Triage Evaluation

- Created: `2026-07-17T20:08:31.451415+00:00`
- Dataset: `data/helpdesk/samples/helpdesk_triage_sample.jsonl`
- Requests: `8`
- Success / failed: `8` / `0`
- Throughput: `0.8` req/s
- p95 latency: `1.404` seconds
- Mean confidence: `0.95`

| Field | Correct | Comparable | Accuracy |
| --- | ---: | ---: | ---: |
| category | 5 | 8 | 62.50% |
| priority | 2 | 8 | 25.00% |
| routing_queue | 5 | 8 | 62.50% |

## Decision Distribution

```json
{
  "category": {
    "hardware": 1,
    "network": 2,
    "other": 1,
    "security": 2,
    "software": 2
  },
  "priority": {
    "P1": 3,
    "P3": 5
  },
  "safety_flags": {
    "none": 8
  }
}
```
