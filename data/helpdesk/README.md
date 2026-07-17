# Helpdesk Scenario Data

This directory defines the normalized ticket format for the IT Helpdesk Triage Assistant scenario.

Checked in:

- `samples/helpdesk_triage_sample.jsonl`: small synthetic smoke-test set.
- `../../schemas/helpdesk-ticket.schema.json`: normalized JSONL record schema.

Ignored locally:

- `raw/`: downloaded external datasets.
- `normalized/`: converted external datasets ready for evaluation.

The normalized JSONL format keeps one ticket per line:

```json
{"id":"sample-001","source":"sample","title":"Cannot access payroll","body":"MFA reset broke payroll login.","expected":{"category":"access","priority":"P2","routing_queue":"identity_access"}}
```

Use `tools/helpdesk_dataset_ingest.py` to create sample data or convert CSV/Hugging Face datasets into this format.
