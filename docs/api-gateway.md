# API Gateway

Date: 2026-07-17 UTC

This service is the application-facing layer for the Triton LLM API lab. It exposes a small OpenAI-compatible API surface and forwards requests to Triton's vLLM `generate` endpoint.

## Current Scope

Implemented:

- `POST /v1/chat/completions`
- `POST /internal/v1/chat/completions` when explicitly enabled for trusted in-stack calls
- `POST /v1/helpdesk/triage`
- `GET /health/live`
- `GET /health/ready`
- `GET /metrics`
- API-key enforcement when configured
- in-memory per-principal rate limiting
- request IDs with `x-request-id`
- JSON metadata logs without prompt or response content
- Prometheus metrics for gateway requests, Triton requests, chat completions, and token counts
- Prometheus quality metrics for helpdesk triage decisions
- Prometheus guardrail request/intervention metrics
- timeout and upstream error mapping for Triton
- Qwen2.5 ChatML-style prompt formatting
- helpdesk triage prompt contract and Pydantic output validation
- deterministic repairs for narrow model-output shape errors
- deterministic priority policy backstop for helpdesk triage
- deterministic helpdesk input policy checks for prompt injection, possible secrets, PII markers, and security-sensitive tickets
- NeMo Guardrails microservice calls in the live helpdesk path
- Docker image build
- ECR image push
- EC2 Docker Compose deployment
- Prometheus scrape target
- unit tests for prompt formatting, OpenAI-compatible response shape, API-key enforcement, internal endpoint behavior, Guardrails integration, safety blocks, output repair, and helpdesk triage validation

Not implemented yet:

- streaming responses
- calibrated LLM-based NeMo self-check rail for helpdesk tickets
- persistent audit sink
- distributed rate limiting

## Deployed Image

The gateway image is pushed to ECR and deployed in the EC2 single-node slice:

```text
037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.3.4
```

Digest:

```text
sha256:81d5c5aebaac7114b54c7a89bfa1eefede03df7fc82cfddaef50c1145c1e3db2
```

The EC2 host binds the gateway to `127.0.0.1:8088`, because cAdvisor already uses host port `8080`.

## Local Test Commands

Create or refresh the local virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r services/api-gateway/requirements-dev.txt
```

Run tests:

```bash
.venv/bin/python -m pytest tests/api_gateway
```

Build the image:

```bash
docker build -t ncp-genl/api-gateway:local services/api-gateway
```

Run the image without Triton, for live endpoint testing only:

```bash
docker run --rm -p 18080:8080 \
  -e API_GATEWAY_REQUIRE_API_KEY=false \
  ncp-genl/api-gateway:local
```

Then:

```bash
curl -fsS http://127.0.0.1:18080/health/live
```

## Runtime Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `TRITON_BASE_URL` | `http://triton:8000` | Triton HTTP endpoint from the gateway container. |
| `TRITON_MODEL_NAME` | `vllm_model` | Triton model to call. |
| `TRITON_TIMEOUT_SECONDS` | `90` | Upstream request timeout. |
| `API_GATEWAY_REQUIRE_API_KEY` | `false` | Enable API-key enforcement. |
| `API_GATEWAY_API_KEY` | unset | Single accepted API key. |
| `API_GATEWAY_API_KEYS` | unset | Comma-separated accepted API keys. |
| `API_GATEWAY_RATE_LIMIT_PER_MINUTE` | `60` | Per-principal in-memory request limit. Use `0` to disable. |
| `MAX_PROMPT_CHARS` | `12000` | Prompt size guardrail. |
| `DEFAULT_MAX_TOKENS` | `256` | Default completion length. |
| `MAX_TOKENS_LIMIT` | `1024` | Maximum accepted `max_tokens`. |
| `DEFAULT_TEMPERATURE` | `0.2` | Default sampling temperature. |
| `DEFAULT_TOP_P` | `0.95` | Default nucleus sampling value. |
| `HELPDESK_DEFAULT_MAX_TOKENS` | `384` | Default completion length for `/v1/helpdesk/triage`. |
| `HELPDESK_DEFAULT_TEMPERATURE` | `0.0` | Default helpdesk sampling temperature. |
| `HELPDESK_DEFAULT_TOP_P` | `0.9` | Default helpdesk nucleus sampling value. |
| `HELPDESK_LOW_CONFIDENCE_THRESHOLD` | `0.7` | Threshold for the low-confidence scenario metric. |
| `HELPDESK_GUARDRAILS_ENABLED` | `false` | Route helpdesk triage through NeMo Guardrails before the model call. |
| `HELPDESK_GUARDRAILS_CONFIG_ID` | `self-check` | NeMo Guardrails config ID used for helpdesk triage. The EC2 slice currently sets `helpdesk-triage`. |
| `NEMO_GUARDRAILS_BASE_URL` | `http://nemo-guardrails:7331` | NeMo Guardrails service URL from the gateway container. |
| `NEMO_GUARDRAILS_TIMEOUT_SECONDS` | `120` | NeMo Guardrails request timeout. |
| `GUARDRAILS_FAIL_CLOSED` | `true` | Return an error instead of bypassing Guardrails when NeMo fails. |
| `ENABLE_INTERNAL_MODEL_ENDPOINT` | `false` | Enables `/internal/v1/chat/completions` for in-stack NeMo calls. |

For production-like runs, set `API_GATEWAY_REQUIRE_API_KEY=true` and source the key from SSM or Secrets Manager rather than committing it.

## ECR Push

Build and push the custom image:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/build_push_api_gateway.sh
```

Optional custom tag:

```bash
TAG=api-gateway-001 \
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/build_push_api_gateway.sh
```

The target repository is:

```text
037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway
```

## Example Request

```bash
curl -fsS http://127.0.0.1:8088/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: replace-me' \
  -d '{
    "messages": [
      {"role": "system", "content": "You are concise."},
      {"role": "user", "content": "Why does monitoring matter for an LLM API?"}
    ],
    "max_tokens": 128,
    "temperature": 0.2
  }'
```

## Helpdesk Triage Request

```bash
curl -fsS http://127.0.0.1:8088/v1/helpdesk/triage \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: replace-me' \
  -d '{
    "title": "Cannot access payroll portal after MFA reset",
    "body": "I reset MFA this morning and now the payroll portal rejects every code.",
    "requester_department": "Finance",
    "product_or_service": "Payroll",
    "business_impact": "Manager cannot approve payroll before deadline."
  }'
```

## EC2 Integration

The EC2 Docker Compose stack:

- binds the gateway to `127.0.0.1:8088`;
- sets `TRITON_BASE_URL=http://triton:8000`;
- enables API-key enforcement from `/ncp-genl/api-gateway/api-key`;
- enables `HELPDESK_GUARDRAILS_ENABLED=true`;
- registers the `helpdesk-triage` NeMo Guardrails config;
- points the gateway at `http://nemo-guardrails:7331`;
- enables `/internal/v1/chat/completions` so NeMo can call the gateway as an OpenAI-compatible model endpoint;
- requires the normal gateway API key on the internal model endpoint when API-key enforcement is enabled;
- points NeMo at `http://api-gateway:8080/internal/v1`;
- passes the gateway API key to NeMo through `NIM_API_KEY` and `NIM_ENDPOINT_API_KEY`;
- adds the gateway `/metrics` endpoint as a Prometheus scrape target;
- validates `/v1/chat/completions`, `/v1/helpdesk/triage`, prompt-injection blocking, NeMo readiness, Prometheus rules, and Grafana provisioning through `tools/ec2_single_node_validate.sh`.

Next integration work:

- tune a scenario-specific NeMo Guardrails config instead of relying on the bundled `default` proxy config;
- calibrate an LLM-based NeMo self-check before enabling it, because both the bundled and first custom self-check prompts false-positive on normal helpdesk tickets;
- add a persistent audit/event sink with redaction controls;
- run load tests against both `/v1/chat/completions` and `/v1/helpdesk/triage`;
- add distributed rate limiting before moving beyond a single host.
