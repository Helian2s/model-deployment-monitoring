# model-deployment-monitoring

Hands-on NCP-GENL preparation project for deploying and operating a production-style LLM API with NVIDIA Triton Inference Server on AWS.

Current live path: API gateway -> NeMo Guardrails microservice -> API gateway internal model endpoint -> Triton vLLM -> Qwen2.5-1.5B-Instruct.

## Project Notes

- [Project agreements](docs/project-agreements.md)
- [Decision and change log](docs/decision-log.md)
- [Container image cache and ECR mirror](docs/container-image-cache.md)
- [Initial Triton smoke test](docs/smoke-test-2026-07-16.md)
- [Qwen 1.5B Triton smoke test](docs/smoke-test-qwen-1.5b-2026-07-16.md)
- [EC2 single-node Triton slice](docs/ec2-single-node-slice-2026-07-17.md)
- [API gateway](docs/api-gateway.md)
- [IT Helpdesk Triage Assistant scenario](docs/helpdesk-triage-scenario.md)
- [Monitoring baseline](docs/monitoring-baseline-2026-07-17.md)
- [API gateway down reliability drill](docs/reliability-drill-api-gateway-down-2026-07-17.md)

## Current EC2 Slice

Deploy or redeploy:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_up.sh
```

Validate:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_validate.sh
```

Pause the GPU instance without terminating it:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_stop.sh
```

When the instance is started again from EC2, `ncp-genl-stack.service` runs `docker compose up -d` automatically. Containers should appear quickly, but Triton/model readiness can take several minutes while the LLM loads. Use validation after start to confirm the stack is healthy.

Forward the API gateway locally:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8088"],"localPortNumber":["8088"]}'
```

Forward NeMo Guardrails locally:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7331"],"localPortNumber":["7331"]}'
```

Terminate the GPU instance while preserving the reusable model-cache EBS volume:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_down.sh
```

## API Gateway

Run local gateway tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r services/api-gateway/requirements-dev.txt
.venv/bin/python -m pytest tests/api_gateway
```

Build the gateway image:

```bash
docker build -t ncp-genl/api-gateway:local services/api-gateway
```

Push a new gateway image to ECR:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/build_push_api_gateway.sh
```

## IT Helpdesk Triage Scenario

Create the normalized sample dataset:

```bash
./tools/helpdesk_dataset_ingest.py sample \
  --output data/helpdesk/normalized/helpdesk_triage_sample.jsonl
```

Evaluate the deployed scenario endpoint through an SSM port forward:

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

See [IT Helpdesk Triage Assistant scenario](docs/helpdesk-triage-scenario.md).

## Guardrails And Performance Tools

Check NeMo Guardrails through an SSM port forward:

```bash
curl -fsS http://127.0.0.1:7331/v1/health
curl -fsS http://127.0.0.1:7331/v1/guardrail/configs
```

Run NVIDIA SDK tools from the deployed toolbox container:

```bash
docker exec -it ncp-genl-tritonserver-sdk bash
```

## Monitoring And Load Test

Run the baseline gateway load test:

```bash
REQUESTS=20 CONCURRENCY=2 MAX_TOKENS=64 \
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/gateway_baseline_load_test.sh
```

Run the API gateway down reliability drill:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/reliability_drill_api_gateway_down.sh
```

Forward Grafana locally:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

Dashboard URL:

```text
http://127.0.0.1:3000/d/ncp-genl-llm-api/ncp-genl-llm-api
```
