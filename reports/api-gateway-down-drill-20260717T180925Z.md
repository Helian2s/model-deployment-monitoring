# API Gateway Down Reliability Drill

Date: 2026-07-17T18:07:48Z

## Scenario

The ncp-genl-api-gateway container was stopped to verify that Prometheus detects the outage and fires ApiGatewayDown. The gateway was then restarted and recovery was validated.

## Result

| Check | Result |
| --- | --- |
| Alert fired | `true` |
| Gateway recovered | `true` |
| Alert cleared | `true` |
| Final Prometheus target health | `up` |

## Timeline

| Event | Time |
| --- | --- |
| Drill started | 2026-07-17T18:07:48Z |
| Gateway stopped | 2026-07-17T18:07:58Z |
| Alert firing | 2026-07-17T18:09:09Z |
| Gateway ready after restart | 2026-07-17T18:09:14Z |
| Alert cleared | 2026-07-17T18:09:24Z |

## Durations

| Metric | Seconds |
| --- | ---: |
| Stop to alert firing | 70 |
| Restart to gateway ready | 5 |
| Restart to alert clear | 15 |

## Follow-Ups

- Repeat the drill after adding notification receivers to Alertmanager.
- Capture screenshots from Grafana and Alertmanager during the firing window.
- Add a similar drill for Triton container failure.
