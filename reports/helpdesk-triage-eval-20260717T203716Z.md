# Helpdesk Triage Evaluation

- Created: `2026-07-17T20:37:16.185223+00:00`
- Dataset: `data/helpdesk/samples/helpdesk_triage_sample.jsonl`
- Requests: `8`
- Success / failed: `7` / `1`
- Throughput: `0.82` req/s
- p95 latency: `1.385` seconds
- Mean confidence: `0.95`

| Field | Correct | Comparable | Accuracy |
| --- | ---: | ---: | ---: |
| category | 4 | 7 | 57.14% |
| priority | 2 | 7 | 28.57% |
| routing_queue | 4 | 7 | 57.14% |

## Decision Distribution

```json
{
  "category": {
    "business_application": 2,
    "network": 2,
    "security": 2,
    "software": 1
  },
  "priority": {
    "P1": 2,
    "P3": 5
  },
  "safety_flags": {
    "none": 6,
    "security_sensitive": 1
  }
}
```
