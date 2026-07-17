# IT Helpdesk Triage Assistant

Date: 2026-07-17 UTC

This is the first scenario-specific layer on top of the Triton/Qwen serving stack.

## Goal

Build a production-style internal IT helpdesk assistant that receives a ticket and returns a strict triage decision for a human service desk workflow.

The assistant does not resolve tickets autonomously. It classifies, routes, summarizes, recommends the next support action, and flags safety/compliance concerns.

## API Contract

Endpoint:

```text
POST /v1/helpdesk/triage
```

Input fields:

- `title`
- `body`
- `requester_department`
- `requester_role`
- `product_or_service`
- `business_impact`
- `history`

Output fields:

- `category`: one of `access`, `hardware`, `software`, `network`, `email`, `security`, `business_application`, `other`
- `priority`: one of `P1`, `P2`, `P3`, `P4`
- `routing_queue`: one of `service_desk_l1`, `identity_access`, `endpoint_support`, `network_operations`, `messaging_collaboration`, `security_operations`, `business_apps`
- `summary`
- `recommended_action`
- `confidence`
- `requires_human`
- `safety_flags`

The gateway applies deterministic input policy checks, routes the request through NeMo Guardrails, validates model output with Pydantic, and records scenario-quality metrics. If the model does not produce a valid contract response after narrow deterministic repairs, the endpoint returns `502` and increments the `invalid_model_output` helpdesk metric.

## Live Safety Path

The deployed EC2 slice uses this request path:

```text
client -> API gateway /v1/helpdesk/triage
       -> gateway deterministic input checks
       -> NeMo Guardrails /v1/guardrail/chat/completions
       -> API gateway /internal/v1/chat/completions
       -> Triton vLLM
       -> Qwen/Qwen2.5-1.5B-Instruct
```

The gateway blocks prompt-injection attempts and possible secrets before any model call. It flags possible PII and security-sensitive content and merges those flags into the final `safety_flags` field.

Current live NeMo config: `helpdesk-triage`.

Important finding: the bundled `self-check` config, and the first custom LLM self-check prompt, were too broad for this helpdesk scenario and blocked a normal payroll-access ticket during validation. The current production-style slice therefore uses a source-controlled NeMo `helpdesk-triage` proxy config plus deterministic gateway policy checks. The next safety step is calibrating an LLM-based NeMo self-check on a labeled helpdesk safety set before enabling it.

## Dataset Plan

Best-fit datasets selected for this scenario:

- Zenodo `Classification of IT Support Tickets`, record `7384758`.
- Hugging Face `Tobi-Bueck/customer-support-tickets`.
- Mendeley help desk tickets as a later candidate.

Raw downloads stay local under ignored paths:

```text
data/helpdesk/raw/
data/helpdesk/normalized/
```

Checked-in files:

- `data/helpdesk/samples/helpdesk_triage_sample.jsonl`
- `schemas/helpdesk-ticket.schema.json`
- `tools/helpdesk_dataset_ingest.py`

Create the normalized sample file:

```bash
./tools/helpdesk_dataset_ingest.py sample \
  --output data/helpdesk/normalized/helpdesk_triage_sample.jsonl
```

Convert a local CSV:

```bash
./tools/helpdesk_dataset_ingest.py csv \
  --input data/helpdesk/raw/tickets.csv \
  --output data/helpdesk/normalized/tickets.jsonl \
  --source company-helpdesk \
  --title-column subject \
  --body-column body \
  --category-column category \
  --priority-column priority
```

Convert a Hugging Face dataset with the optional `datasets` package:

```bash
python -m pip install datasets
./tools/helpdesk_dataset_ingest.py huggingface \
  --dataset Tobi-Bueck/customer-support-tickets \
  --split train \
  --limit 1000 \
  --output data/helpdesk/normalized/tobi_customer_support.jsonl
```

## Evaluation

Run through an SSM port forward:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8088"],"localPortNumber":["18088"]}'
```

In another terminal:

```bash
export API_GATEWAY_API_KEY="$(
  AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
  aws ssm get-parameter \
    --name /ncp-genl/api-gateway/api-key \
    --with-decryption \
    --query Parameter.Value \
    --output text
)"

./tools/helpdesk_triage_eval.py \
  --dataset data/helpdesk/samples/helpdesk_triage_sample.jsonl \
  --url http://127.0.0.1:18088/v1/helpdesk/triage \
  --concurrency 1
```

## First Baseline

Report:

- `reports/helpdesk-triage-eval-20260717T200831Z.json`
- `reports/helpdesk-triage-eval-20260717T200831Z.md`

Results on the 8-ticket sample set:

- Requests: `8`
- Succeeded: `8`
- Failed: `0`
- p95 latency: `1.404` seconds
- Category accuracy: `62.50%`
- Priority accuracy: `25.00%`
- Routing queue accuracy: `62.50%`

Interpretation:

- The endpoint and schema validation are working.
- The small Qwen model is overconfident on the sample set.
- Priority classification needs the most prompt/rules work.
- Category mistakes are useful inputs for the next guardrails and quality-metrics phase.

## Post-Guardrails Baseline

Report:

- `reports/helpdesk-triage-eval-20260717T205427Z.json`
- `reports/helpdesk-triage-eval-20260717T205427Z.md`

Results on the same 8-ticket sample set after wiring NeMo Guardrails into the live path and adding deterministic output repair:

- Requests: `8`
- Succeeded: `8`
- Failed: `0`
- p95 latency: `1.400` seconds
- Category accuracy: `62.50%`
- Priority accuracy: `25.00%`
- Routing queue accuracy: `62.50%`
- Mean confidence: `0.95`

Interpretation:

- Availability and schema behavior are clean on the sample set.
- The previous single invalid-output failure was removed by deterministic repair of a narrow routing-queue shape issue.
- The model-quality gap remains: priority classification is still weak and confidence is too high for the observed accuracy.
- The scenario dashboard should make this visible through confidence, low-confidence, repair, safety-flag, and category/priority distribution panels.

## Priority Policy Backstop

The gateway now applies a deterministic priority policy after model-output validation. This is intentionally production-shaped: the model still drafts the decision, but business priority is corrected when ticket text clearly maps to P1/P2/P3/P4 policy.

Examples:

- widespread outage, active compromise, data breach, or physical danger -> `P1`
- single-user business-critical access block, contained phishing report, unsafe contained hardware issue -> `P2`
- degraded service or error with a workaround -> `P3`
- routine question, informational request, or low-impact request with a clear workaround -> `P4`

Priority overrides increment `api_gateway_helpdesk_triage_repairs_total{field="priority",reason="policy_override"}` and cap reported confidence at `0.79`.

## Post-Priority-Policy Baseline

Report:

- `reports/helpdesk-triage-eval-20260717T211023Z.json`
- `reports/helpdesk-triage-eval-20260717T211023Z.md`

Results on the same 8-ticket sample set after deploying the priority policy:

- Requests: `8`
- Succeeded: `8`
- Failed: `0`
- p95 latency: `1.292` seconds
- Category accuracy: `62.50%`
- Priority accuracy: `100.00%`
- Routing queue accuracy: `62.50%`
- Mean confidence: `0.83`

Interpretation:

- Priority quality improved from `25.00%` to `100.00%` on the smoke set.
- The confidence cap reduced mean confidence from `0.95` to `0.83` when policy overrides were applied.
- Category and routing remain the main quality gaps.
- The next quality pass should focus on deterministic category/routing policy, prompt examples, or a larger labeled dataset.

## Metrics

New Prometheus metrics:

- `api_gateway_helpdesk_triage_total`
- `api_gateway_helpdesk_triage_decisions_total`
- `api_gateway_helpdesk_triage_confidence`
- `api_gateway_helpdesk_triage_safety_flags_total`
- `api_gateway_helpdesk_triage_low_confidence_total`
- `api_gateway_helpdesk_triage_repairs_total`
- `api_gateway_guardrails_requests_total`
- `api_gateway_guardrails_duration_seconds`
- `api_gateway_guardrails_interventions_total`

The Grafana dashboard now includes scenario panels for helpdesk latency, outcomes, category/priority distribution, guardrails requests and interventions, confidence, safety flags, low-confidence decisions, and deterministic repairs.

Prometheus now includes scenario alerts for helpdesk p95 latency, invalid model output, NeMo Guardrails failures, blocked inputs, low-confidence triage, and output repair events.

## Next Work

- Pull and normalize the Zenodo and Hugging Face datasets.
- Evaluate the priority policy against normalized real helpdesk datasets.
- Build a labeled helpdesk safety set before enabling any LLM-based NeMo self-check rail.
- Add a redacted audit-event sink for safety and quality decisions.
- Run load tests with ticket-shaped requests.
- Run garak or equivalent adversarial checks against the helpdesk path.
