# API Gateway Down Reliability Drill

Date: 2026-07-17 UTC

This drill verifies that the single-node monitoring stack detects an API gateway outage, raises the expected Prometheus alert, and clears the alert after recovery.

## Scenario

The `ncp-genl-api-gateway` container was intentionally stopped on the EC2 host. Prometheus was polled until `ApiGatewayDown` moved to `firing`, then the gateway container was restarted and readiness plus alert clearing were verified.

## Command

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/reliability_drill_api_gateway_down.sh
```

The drill runs through SSM against the instance recorded in `.ncp-genl/ec2-single-node.env`. It does not expose the API gateway key.

## Result

Report artifacts:

- JSON: `reports/api-gateway-down-drill-20260717T180925Z.json`
- Markdown: `reports/api-gateway-down-drill-20260717T180925Z.md`

Measured timeline:

| Event | Time |
| --- | --- |
| Drill started | `2026-07-17T18:07:48Z` |
| Gateway stopped | `2026-07-17T18:07:58Z` |
| Alert pending | `2026-07-17T18:08:09Z` |
| Alert firing | `2026-07-17T18:09:09Z` |
| Gateway restarted | `2026-07-17T18:09:09Z` |
| Gateway ready | `2026-07-17T18:09:14Z` |
| Alert cleared | `2026-07-17T18:09:24Z` |

Measured durations:

| Metric | Seconds |
| --- | ---: |
| Gateway stop to alert firing | `70` |
| Gateway restart to ready | `5` |
| Gateway restart to alert clear | `15` |

Final checks:

- `ApiGatewayDown` fired: `true`
- Gateway recovered: `true`
- Alert cleared: `true`
- Final Prometheus target health for `api-gateway`: `up`
- Post-drill active alerts: none
- Full stack validation passed after recovery

## Educational Notes

This drill turns monitoring from a static dashboard into an operational exercise. It covers:

- Failure injection against a real service container.
- Alert state transitions: inactive, pending, firing, inactive.
- Detection time and recovery time measurement.
- Post-incident validation with health checks, Prometheus targets, and one gateway inference request.
- Evidence capture in source-controlled reports.

## Follow-Ups

Next reliability work:

- Add Alertmanager notification receivers and repeat the drill to confirm delivery.
- Add a Triton container outage drill.
- Add step and spike load tests to observe latency, saturation, and token throughput.
- Capture an incident-style report that combines metrics, logs, and operator timeline.
