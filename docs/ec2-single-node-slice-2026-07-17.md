# EC2 Single-Node Triton Slice

Date: 2026-07-17 UTC

This is the first persistent production-style slice of the NCP-GENL project. It runs Triton, GPU metrics, host/container metrics, Prometheus, Alertmanager, and Grafana on one GPU EC2 instance.

## Status

Deployed and validated.

The instance is currently running:

- Instance ID: `i-00020ad61c45f16a9`
- Instance type: `g6.2xlarge`
- AMI: `ami-0f855e2020ff55dbc`
- Region: `us-west-2`
- Availability Zone: `us-west-2a`
- Subnet: `subnet-0c7c33d276fe5f654`
- Security group: `sg-05594cf6dd1c8cc20`
- Cache EBS volume: `vol-03314a16bd7c78706`, 150 GiB gp3, encrypted
- Model: `Qwen/Qwen2.5-1.5B-Instruct`
- Triton model name: `vllm_model`

Local state is stored in `.ncp-genl/ec2-single-node.env`. That file is ignored by Git.

## Access Model

The security group has no inbound rules. Service ports are bound to `127.0.0.1` on the EC2 host and should be reached through SSM port forwarding.

Useful port forwards:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
aws ssm start-session \
  --target i-00020ad61c45f16a9 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
```

Use the same pattern for:

| Service | Remote port | Local port |
| --- | ---: | ---: |
| Triton HTTP | `8000` | `8000` |
| Triton metrics | `8002` | `8002` |
| Prometheus | `9090` | `9090` |
| Alertmanager | `9093` | `9093` |
| Grafana | `3000` | `3000` |

## Deployed Containers

All runtime images are pulled from the project ECR mirror:

| Container | Image |
| --- | --- |
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
./tools/ec2_single_node_down.sh
```

The down script terminates the EC2 instance and leaves the cache EBS volume in place for future model cache reuse.

## Validation Result

The stricter validation passed after the Prometheus data directory ownership fix.

Confirmed:

- Triton health endpoints are ready.
- Triton vLLM model repository exposes `vllm_model`.
- One inference request succeeded against `Qwen/Qwen2.5-1.5B-Instruct`.
- Triton Prometheus metrics include `nv_inference_*` and `vllm:*` metrics.
- DCGM exporter exposes GPU memory, utilization, temperature, and power metrics.
- Prometheus reports all scrape targets as `up`: Triton, DCGM exporter, node exporter, cAdvisor, and Prometheus.
- Alertmanager ready endpoint returns `OK`.
- Grafana health endpoint returns database `ok`.

Observed GPU state during validation:

- GPU: NVIDIA L4
- Driver: `595.71.05`
- GPU memory used: about `16.4 GiB` of `23.0 GiB`

Prometheus has `RestartCount=14` from the initial `/prometheus/queries.active` permission issue before the ownership fix. After the fix, it remained running from `2026-07-17T02:17:39Z` and all targets stayed healthy.

## Next Project Steps

The next useful slice is to add the application-facing API layer:

- OpenAI-style `/v1/chat/completions` wrapper over Triton.
- Request IDs and structured logs.
- Basic auth or API key enforcement.
- Request and response metadata metrics.
- Safety hook points for NeMo Guardrails.
- Load generation from a separate client process or host.

After that, move the same components to EKS for autoscaling and failover behavior.
