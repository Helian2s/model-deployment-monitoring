# EC2 Single-Node Triton Slice

Date: 2026-07-17 UTC

This is the first persistent production-style slice of the NCP-GENL project. It runs the API gateway, Triton, NeMo Guardrails, Triton SDK tooling, GPU metrics, host/container metrics, Prometheus, Alertmanager, and Grafana on one GPU EC2 instance.

## Status

Deployed and validated.

The instance is currently running:

- Instance ID: `i-0762eca19198f5272`
- Instance type: `g6.2xlarge`
- AMI: `ami-0f855e2020ff55dbc`
- Region: `us-west-2`
- Availability Zone: `us-west-2c`
- Subnet: `subnet-0e52a0c3ae6a086e8`
- Security group: `sg-05594cf6dd1c8cc20`
- Cache EBS volume: `vol-0040803576e31c710`, 150 GiB gp3, encrypted
- Model: `Qwen/Qwen2.5-1.5B-Instruct`
- Triton model name: `vllm_model`
- API gateway image: `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.3.4`
- API gateway key parameter: `/ncp-genl/api-gateway/api-key`
- NeMo Guardrails image: `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/nemo-guardrails:25.12`
- Triton SDK image: `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver-sdk:26.05-py3-sdk`

Local state is stored in `.ncp-genl/ec2-single-node.env`. That file is ignored by Git.

The original `us-west-2a` instance `i-00020ad61c45f16a9` is stopped. It could not be restarted because EC2 returned `InsufficientInstanceCapacity`, so the active slice was moved to `us-west-2c`. An empty 2b cache volume created during a failed fallback attempt was deleted.

## Access Model

The security group has no inbound rules. Service ports are bound to `127.0.0.1` on the EC2 host and should be reached through SSM port forwarding.

Useful port forwards:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-0762eca19198f5272 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8088"],"localPortNumber":["8088"]}'
```

Use the same pattern for:

| Service | Remote port | Local port |
| --- | ---: | ---: |
| API gateway | `8088` | `8088` |
| NeMo Guardrails | `7331` | `7331` |
| Triton HTTP | `8000` | `8000` |
| Triton metrics | `8002` | `8002` |
| Prometheus | `9090` | `9090` |
| Alertmanager | `9093` | `9093` |
| Grafana | `3000` | `3000` |

## Deployed Containers

All runtime images are pulled from the project ECR mirror:

| Container | Image |
| --- | --- |
| `ncp-genl-api-gateway` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.3.4` |
| `ncp-genl-nemo-guardrails` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/nemo-guardrails:25.12` |
| `ncp-genl-tritonserver-sdk` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver-sdk:26.05-py3-sdk` |
| `ncp-genl-triton` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver:26.05-vllm-python-py3` |
| `ncp-genl-dcgm-exporter` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/dcgm-exporter:4.6.0-4.8.3-distroless` |
| `ncp-genl-prometheus` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/prometheus:v3.13.1` |
| `ncp-genl-alertmanager` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/alertmanager:v0.33.1` |
| `ncp-genl-grafana` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/grafana:13.0.3` |
| `ncp-genl-node-exporter` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/node-exporter:v1.12.1` |
| `ncp-genl-cadvisor` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/cadvisor:v0.55.1` |

## Commands

Deploy or redeploy the slice:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/ec2_single_node_up.sh
```

Run validation:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/ec2_single_node_validate.sh
```

Stop spending on the GPU instance:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/ec2_single_node_stop.sh
```

This stops the EC2 instance without terminating it. The attached encrypted cache EBS volume and local instance disk state are preserved. On the next EC2 start, `ncp-genl-stack.service` runs `docker compose up -d` automatically, and all Compose services also have `restart: unless-stopped`. The containers start quickly, but full API readiness waits on Triton loading the model; the reboot test measured `nv_model_load_duration_secs` around `163` seconds.

Terminate and rebuild later:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
./tools/ec2_single_node_down.sh
```

The down script terminates the active EC2 instance from `.ncp-genl/ec2-single-node.env` and leaves the cache EBS volume in place for future model cache reuse.

## Validation Result

The stricter validation passed after adding the API gateway and correcting the EBS cache mount.

Confirmed:

- API gateway live and ready endpoints are healthy.
- API gateway `/v1/chat/completions` succeeds with the API key from SSM.
- API gateway Prometheus metrics are exposed.
- NeMo Guardrails live and ready endpoints are healthy.
- NeMo Guardrails lists the bundled configs plus the project config: `abc`, `self-check`, `default`, and `helpdesk-triage`.
- Triton SDK toolbox exposes `perf_analyzer`, `genai-perf`, `tritonclient`, and `genai_perf`.
- Triton health endpoints are ready.
- Triton vLLM model repository exposes `vllm_model`.
- One inference request succeeded against `Qwen/Qwen2.5-1.5B-Instruct`.
- Triton Prometheus metrics include `nv_inference_*` and `vllm:*` metrics.
- DCGM exporter exposes GPU memory, utilization, temperature, and power metrics.
- Prometheus reports all scrape targets as `up`: API gateway, Triton, DCGM exporter, node exporter, cAdvisor, and Prometheus.
- Prometheus alert rules include gateway latency, gateway 5xx, Triton inference failures, GPU memory, target-down rules, and helpdesk scenario quality rules.
- Alertmanager ready endpoint returns `OK`.
- Grafana health endpoint returns database `ok`.
- Grafana has provisioned Prometheus datasource `prometheus` and dashboard `NCP-GENL LLM API`, including scenario-quality panels for helpdesk triage.
- Cache mount is real EBS storage: `/mnt/ncp-genl-cache` is `/dev/nvme2n1` ext4 with about 147 GiB usable space.
- Helpdesk triage succeeds through the live NeMo Guardrails path.
- Helpdesk priority policy corrected the validation payroll-access ticket from model `P1` to final `P2` with confidence capped at `0.79`.
- Prompt-injection payloads are blocked by the gateway with HTTP `403` before reaching the model.
- Direct unauthenticated calls to `/internal/v1/chat/completions` are rejected with HTTP `401`.
- Boot persistence is configured through `ncp-genl-stack.service`, enabled in systemd.
- Reboot validation confirmed that `ncp-genl-stack.service` started all 10 project containers automatically and the full validation passed after Triton completed cold model loading.

Observed GPU state during validation:

- GPU: NVIDIA L4
- Driver: `595.71.05`
- GPU memory used: about `16.4 GiB` of `23.0 GiB`

All active containers had `RestartCount=0` during validation after the Guardrails and SDK deployment.

Current Guardrails integration:

- `ncp-genl-nemo-guardrails` is deployed and healthy.
- It uses a persistent SQLite DB at `/opt/ncp-genl/data/nemo-guardrails/nemo-guardrails.sqlite`.
- It is in the live `/v1/helpdesk/triage` request path.
- The gateway calls NeMo Guardrails at `http://nemo-guardrails:7331/v1/guardrail/chat/completions`.
- NeMo calls the gateway internal OpenAI-compatible endpoint at `http://api-gateway:8080/internal/v1`.
- The internal endpoint then calls Triton/vLLM.
- The internal endpoint requires the gateway API key when API-key enforcement is enabled.
- NeMo receives that key through `NIM_API_KEY` and `NIM_ENDPOINT_API_KEY`.
- The deployed helpdesk Guardrails config is `helpdesk-triage`.
- The config is registered during EC2 deployment from `services/nemo-guardrails/configs/helpdesk-triage.json`.
- The source-controlled config now enables a narrow NeMo `self check input` rail for scope, prompt-injection, secrets, and authorization-bypass checks.
- Known safety gap: the earlier broad LLM self-check produced false positives on a normal payroll-access ticket. The narrow rail must be evaluated against a labeled helpdesk safety set after the next live deploy.

Baseline load test through the gateway:

- Requests: `20`
- Concurrency: `2`
- Success: `20`
- Failures: `0`
- p95 latency from client: about `1.064` seconds
- Throughput from client: about `2.114` requests/sec
- Prometheus p95 latency snapshot: about `1.75` seconds
- GPU framebuffer memory usage: about `72.7%`

API gateway down reliability drill:

- Stopping `ncp-genl-api-gateway` caused `ApiGatewayDown` to fire after about `70` seconds.
- Restarting the gateway restored readiness after about `5` seconds.
- The alert cleared after about `15` seconds from restart.
- A post-drill alert check returned no active alerts.
- Full validation passed after recovery.

## Next Project Steps

The next useful slice is production monitoring depth:

- add Alertmanager notification receivers and repeat the gateway outage drill;
- calibrate a scenario-specific NeMo self-check rail against labeled safety examples;
- pull and normalize larger helpdesk datasets;
- use the scenario-quality metrics to improve priority/category/routing behavior;
- run NVIDIA SDK performance tests with `ncp-genl-tritonserver-sdk`;
- add a Triton outage drill;
- run step and spike load tests through the gateway and helpdesk path;
- capture an incident-style report from metrics and logs.

After that, move the same components to EKS for autoscaling and failover behavior.
