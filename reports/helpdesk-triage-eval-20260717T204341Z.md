# Helpdesk Triage Evaluation

- Created: `2026-07-17T20:43:41.681047+00:00`
- Dataset: `data/helpdesk/samples/helpdesk_triage_sample.jsonl`
- Requests: `8`
- Success / failed: `8` / `0`
- Throughput: `0.806` req/s
- p95 latency: `1.401` seconds
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
    "business_application": 2,
    "hardware": 1,
    "network": 2,
    "security": 2,
    "software": 1
  },
  "priority": {
    "P1": 3,
    "P3": 5
  },
  "safety_flags": {
    "none": 7,
    "security_sensitive": 1
  }
}
```
