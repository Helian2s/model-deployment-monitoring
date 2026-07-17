# Monitoring Baseline

Date: 2026-07-17 UTC

This document records the first production-monitoring slice for the single-node Triton LLM API lab.

## Scope

Implemented:

- Grafana datasource provisioning for Prometheus.
- Grafana dashboard provisioning for the LLM API stack.
- Expanded Prometheus alert rules.
- Gateway baseline load-test helper.
- Validation checks for Prometheus rules and Grafana provisioning.
- Scenario-quality panels for IT helpdesk triage.
- Guardrails, safety-flag, low-confidence, and output-repair metrics.

## Grafana Dashboard

Dashboard:

```text
NCP-GENL / NCP-GENL LLM API
```

Dashboard UID:

```text
ncp-genl-llm-api
```

Provisioned panels:

- API gateway request rate by path and status class.
- Gateway chat completion p50/p95/p99 latency.
- Gateway and Triton request outcomes.
- Gateway and vLLM token throughput.
- GPU utilization and framebuffer memory usage.
- Prometheus target health.
- Helpdesk triage latency.
- Helpdesk triage outcomes.
- Helpdesk category and priority distribution.
- Guardrails requests and interventions.
- Helpdesk confidence.
- Safety flags, low-confidence decisions, and deterministic output repairs.

Access through SSM port forwarding:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["3000"],"localPortNumber":["3000"]}'
```

Then open:

```text
http://127.0.0.1:3000/d/ncp-genl-llm-api/ncp-genl-llm-api
```

Current lab credentials are `admin` / `admin`.

## Prometheus Alerts

The deployed rule group is `llm-api-single-node`.

Rules:

- `TritonMetricsDown`
- `GpuMetricsDown`
- `ApiGatewayDown`
- `ApiGatewayTritonFailures`
- `ApiGateway5xxResponses`
- `ApiGatewayP95LatencyHigh`
- `HelpdeskTriageP95LatencyHigh`
- `HelpdeskTriageInvalidOutput`
- `HelpdeskGuardrailsFailures`
- `HelpdeskGuardrailsBlockedInput`
- `HelpdeskLowConfidenceTriage`
- `HelpdeskTriageOutputRepaired`
- `TritonInferenceFailures`
- `NoSuccessfulInference`
- `GpuMemoryHigh`
- `HostMetricsDown`

Validation confirmed the rules were loaded through:

```text
http://127.0.0.1:9090/api/v1/rules
```

No alerts were firing immediately after the baseline load test. Scenario validation intentionally sends one blocked prompt-injection ticket, so `HelpdeskGuardrailsBlockedInput` can briefly become pending or firing after validation runs. Helpdesk evaluation can also fire `HelpdeskTriageOutputRepaired` when the deterministic priority policy overrides model output; this is expected while the policy backstop is being measured.

## Reliability Drill

The first alert-fire drill is documented in `docs/reliability-drill-api-gateway-down-2026-07-17.md`.

Command:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/reliability_drill_api_gateway_down.sh
```

Result summary:

- Stopping `ncp-genl-api-gateway` moved `ApiGatewayDown` to `pending`, then `firing`.
- Stop to firing time: about `70` seconds.
- Gateway restart to readiness: about `5` seconds.
- Gateway restart to alert clear: about `15` seconds.
- Post-drill active alerts: none.
- Full stack validation passed after recovery.

Report artifacts:

- `reports/api-gateway-down-drill-20260717T180925Z.json`
- `reports/api-gateway-down-drill-20260717T180925Z.md`

## Baseline Load Test

Command:

```bash
REQUESTS=20 CONCURRENCY=2 MAX_TOKENS=64 \
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/gateway_baseline_load_test.sh
```

Result:

```json
{
  "concurrency": 2,
  "elapsed_seconds": 9.46,
  "failed": 0,
  "latency_seconds": {
    "max": 1.077,
    "mean": 0.944,
    "min": 0.913,
    "p50": 0.936,
    "p95": 1.064,
    "p99": 1.077
  },
  "requests": 20,
  "requests_per_second": 2.114,
  "status_counts": {
    "200": 20
  },
  "succeeded": 20
}
```

Prometheus snapshot after the run:

```json
{
  "gateway_failures_10m": [],
  "gateway_p95_latency_10m": [1.75],
  "gateway_requests_10m": [20.6154],
  "gateway_success_10m": [20.6154],
  "gpu_memory_pct": [72.6745, 72.6745]
}
```

The load-test client runs on the EC2 host through SSM, fetches the API gateway key from SSM, and does not print the key.

## Validation Commands

Full stack validation:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/ec2_single_node_validate.sh
```

Baseline load test:

```bash
REQUESTS=20 CONCURRENCY=2 MAX_TOKENS=64 \
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/gateway_baseline_load_test.sh
```

## Next Monitoring Work

Next useful steps:

- Add Alertmanager notification receivers and repeat the API gateway outage drill.
- Capture an incident timeline from Prometheus, Grafana, Docker logs, and Alertmanager.
- Add a longer step-load test and compare p95 latency, throughput, GPU utilization, and token rate.
- Add dashboard panels for container restarts and API 4xx/rate-limit behavior.
- Add dataset-backed quality reports as dashboard annotations or static release artifacts.
- Add drift checks for category, priority, routing queue, safety flags, and repair rate.
- Move dashboard JSON out of the shell script into a source-controlled asset if it grows further.
