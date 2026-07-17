# NCP-GENL Triton LLM API Project Agreements

Last updated: 2026-07-17 UTC

## Goal

Build a hands-on production-style LLM API lab for NCP-GENL preparation.

The project must emphasize:

- Model deployment with NVIDIA Triton Inference Server.
- Production monitoring and reliability.
- Safety, ethics, and compliance.
- AWS deployment practice.
- NVIDIA tooling wherever it materially fits the learning objective.

## Current Scope

The project will use the Triton path only for model serving.

NVIDIA NIM is intentionally out of the first implementation path. NIM remains useful as a comparison topic, but the current build should expose Triton internals directly: model repository layout, backend configuration, health checks, metrics, request behavior, load testing, and failure modes.

## Product Positioning

Triton and NIM have different operating models.

Triton Inference Server is a general-purpose inference server. In this project, we manage the model repository, backend selection, model configuration, health endpoints, metrics, and performance behavior.

NIM is a production-packaged model microservice. It hides more of the serving internals and gives an easier production API surface. It is valuable, but it is not the current serving path because the project explicitly needs Triton learning value.

The API gateway is not an alternative to Triton or NIM. It is the application-facing service that adds request IDs, auth/rate limiting, safety hooks, audit metadata, and an OpenAI-like API wrapper.

## AWS Region And Account Assumptions

Use `us-west-2`.

Use AWS profile:

```bash
AWS_PROFILE=finetuning-local
```

Observed relevant quota in `us-west-2`:

- Running On-Demand G and VT instances: 96 vCPUs.
- Running On-Demand P instances: 0 vCPUs.
- All G and VT Spot Instance Requests: 0 vCPUs.

This means the project should use On-Demand G-family instances. Do not plan on P-family instances or Spot capacity unless quota is changed later.

Existing launch templates are not part of the design. Build project infrastructure from scratch.

## Instance Plan

Start with `g6.2xlarge`.

Rationale:

- 1 NVIDIA L4 GPU.
- About 24 GB class GPU memory.
- 8 vCPUs.
- 32 GiB host memory.
- Lower cost than `g6e.2xlarge`.
- Sufficient for full-stack validation with small models and potentially a constrained 7B experiment.

Escalate to `g6e.2xlarge` only if needed.

Rationale for `g6e.2xlarge`:

- 1 NVIDIA L40S GPU.
- About 48 GB class GPU memory.
- Better for reliable 7B/8B serving, longer context, and more concurrency.

G5 is acceptable as a fallback, but not preferred. G5 uses the older A10G GPU. G7/G7e exist in `us-west-2`, but are not needed for the core project and are likely unnecessary cost for the first implementation.

## Model Plan

Use a staged model progression.

Stage 1 smoke test:

- `facebook/opt-125m`
- Purpose: validate Triton vLLM backend, model repository layout, health checks, metrics, and basic inference.
- Working Triton vLLM `model.json` should start minimal. Do not set `model_transaction_policy.decoupled` in `config.pbtxt`; the vLLM backend auto-completes this. Do not pass unsupported vLLM engine arguments such as `disable_log_requests` to Triton `26.05`.

Stage 2 full-stack validation on `g6.2xlarge`:

- Selected: `Qwen/Qwen2.5-1.5B-Instruct`
- Deferred alternative: `Qwen/Qwen2.5-3B-Instruct`
- Purpose: realistic enough for API, monitoring, alerting, safety probes, and load tests without forcing a larger instance.
- Initial validation succeeded on `g6.2xlarge` with `max_model_len=2048` and `gpu_memory_utilization=0.70`.

Stage 3 7B stretch on `g6.2xlarge`:

- `mistralai/Mistral-7B-Instruct-v0.3`
- Purpose: higher-value production-style LLM test. The NGC NIM image was pulled successfully, proving account access to that model family, but the Triton path should use the model through Triton/vLLM rather than deploying the NIM container.

Alternative 7B:

- `Qwen/Qwen2.5-7B-Instruct`

If 7B inference is memory-bound or too slow on `g6.2xlarge`, move to `g6e.2xlarge`.

## Container Plan

Prefer NVIDIA/NVCR images when they fit the task.

Core containers:

| Role | Image |
| --- | --- |
| Triton LLM server | `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3` for current DLAMI driver, or `26.06-vllm-python-py3` after driver update |
| Triton SDK and load testing | `nvcr.io/nvidia/tritonserver:26.05-py3-sdk` for current DLAMI driver, or `26.06-py3-sdk` after driver update |
| Optional TensorRT-LLM stretch | `nvcr.io/nvidia/tritonserver:26.05-trtllm-python-py3` for current DLAMI driver, or `26.06-trtllm-python-py3` after driver update |
| GPU metrics | `nvcr.io/nvidia/k8s/dcgm-exporter:4.6.0-4.8.3-distroless` |
| GPU debug/test utility | `nvcr.io/nvidia/cuda:13.2.1-base-ubuntu24.04` for new tests; `12.4.1-base-ubuntu22.04` remains mirrored from the first smoke test |
| EKS GPU plugin later | `nvcr.io/nvidia/k8s-device-plugin:v0.19.3`, rechecked against the selected EKS/Kubernetes version |
| API gateway | custom ECR image |
| NeMo Guardrails | `nvcr.io/nvidia/nemo-microservices/guardrails:25.12` |
| garak evaluator | `nvcr.io/nvidia/eval-factory/garak:26.03`; custom ECR runner only if wrapping is needed |
| Prometheus | `prom/prometheus:v3.13.1` |
| Grafana | `grafana/grafana:13.0.3` |
| Alertmanager | `prom/alertmanager:v0.33.1` |
| Node exporter | `prom/node-exporter:v1.12.1` |
| cAdvisor | `gcr.io/cadvisor/cadvisor:v0.55.1` |

The exact image pins and mirror status are tracked in `docs/container-image-cache.md`.

All active lab images should be mirrored into ECR after they are pulled from the upstream registry. NVCR remains the upstream source for NVIDIA images, but repeated EC2 and EKS experiments should use the mirrored ECR tags when available. See `docs/container-image-cache.md` for the current ECR repositories, pushed tags, and digests.

The first GPU smoke test used AWS Deep Learning AMI `ami-0f855e2020ff55dbc`, which provides NVIDIA driver `595.71.05` and CUDA `13.2`. Triton `26.05-vllm-python-py3` was selected for the smoke test because it aligns better with that driver generation than Triton `26.06`, which expects a newer driver stack.

## NVIDIA Registry And Secrets

NVIDIA images should be pulled from `nvcr.io`, tagged, and pushed to project ECR repositories when they become part of the active lab. Do not copy image tarballs between machines as the normal path.

For repeated runs, EC2 instances and EKS nodes should pull from ECR. Use direct `nvcr.io` pulls only when validating a new upstream image or refreshing the mirror.

Created ECR repositories use the `ncp-genl/` prefix in account `037678282394`, region `us-west-2`, with scan-on-push enabled and AES256 encryption.

The NGC API key exists in AWS SSM Parameter Store as:

```text
/finetuning/ngc/api-key
```

It is a `SecureString`.

Use this key only at runtime for Docker login or Kubernetes image pull secrets. Do not commit it to Git, Docker Compose files, logs, or generated reports.

The Hugging Face token also exists in AWS SSM Parameter Store as:

```text
/finetuning/huggingface/token
```

It is a `SecureString`. Use it at runtime for Hugging Face model downloads when authentication, gated model access, or rate-limit protection is needed. Do not read it into documentation or logs.

For EC2 Docker login:

```bash
aws ssm get-parameter \
  --name /finetuning/ngc/api-key \
  --with-decryption \
  --query Parameter.Value \
  --output text \
| docker login nvcr.io -u '$oauthtoken' --password-stdin
```

For EKS:

- Create an `imagePullSecret` for `nvcr.io`.
- If a runtime container needs `NGC_API_KEY`, use a separate Kubernetes secret.

For Triton/vLLM model downloads from Hugging Face, inject the Hugging Face token into the runtime container as the standard token environment variable accepted by the runtime, preferably `HF_TOKEN`.

## Deployment Progression

Use a two-step implementation path.

First, run a small single-node Docker smoke test on a GPU EC2 instance. This validates:

- EC2 GPU driver readiness.
- NGC auth.
- Triton image pull.
- Triton startup.
- GPU visibility.
- Basic model load.
- `/v2/health/live`.
- `/v2/health/ready`.
- `/metrics`.
- One inference request.

Then move the main project to EKS/Kubernetes for:

- autoscaling;
- failover;
- rolling updates;
- GPU scheduling;
- readiness/liveness behavior;
- Prometheus-based observability;
- load-test jobs.

Docker Compose is acceptable only for same-host learning and fast iteration. It is not the production/failover orchestration layer.

The first persistent single-node slice is implemented with `tools/ec2_single_node_up.sh`, `tools/ec2_single_node_validate.sh`, and `tools/ec2_single_node_down.sh`. It runs Triton, DCGM exporter, Prometheus, Alertmanager, Grafana, node exporter, and cAdvisor on one `g6.2xlarge` instance. See `docs/ec2-single-node-slice-2026-07-17.md`.

## Observability

Expose and monitor:

- Triton health endpoints.
- Triton Prometheus metrics.
- GPU metrics from DCGM exporter.
- API gateway request metrics.
- Host/container metrics.
- Kubernetes pod/node metrics in the EKS phase.

Dashboards should cover:

- request rate;
- request success and error rate;
- p50/p95/p99 latency;
- time to first token where available;
- tokens per second;
- GPU utilization;
- GPU memory;
- GPU temperature and power;
- Triton model load state;
- readiness failures;
- pod restarts;
- guardrail block counts;
- safety test outcomes.

## Alerting

Initial alert rules should include:

- Triton down or not ready.
- Model unavailable.
- High 5xx/error rate.
- p95 latency above SLO.
- GPU memory above threshold.
- GPU utilization near zero while requests are arriving.
- No successful inference for a configured window.
- Guardrail bypass or safety test failure.

## Load Testing

The load will be emulated against the server.

Use NVIDIA GenAI-Perf or Triton Perf Analyzer from the Triton SDK container where possible.

The load generator should run outside the Triton GPU container. For realistic testing, run it from:

- a separate CPU EC2 instance; or
- a Kubernetes Job on a CPU node in the EKS phase.

Test patterns:

- baseline;
- step load;
- spike load;
- short soak;
- overload until SLO violation;
- failover during active requests.

## Reliability Experiments

Planned experiments:

- kill Triton container/pod;
- stop or drain a GPU node;
- force model load failure;
- overload the server;
- test readiness behavior while model is loading;
- test rolling restart;
- compare behavior before and after autoscaling;
- write an incident report from metrics and logs.

## Safety, Ethics, And Compliance

Retain a safety/compliance track even though the serving path is Triton.

Use:

- NeMo Guardrails Microservice from NVIDIA registry.
- garak for adversarial/vulnerability-style tests.
- metadata-first logging.
- optional full prompt/response logging only in controlled development mode.
- SSM or Secrets Manager for secrets.
- KMS encryption where applicable.
- a model/service card.
- a risk register.

Topics to cover:

- prompt injection;
- data leakage;
- unsafe outputs;
- PII handling;
- hallucination and over-reliance;
- auditability;
- retention policy;
- accepted and prohibited use cases.

## Open Questions

- Whether the 7B stretch should use Mistral or Qwen first in the Triton/vLLM path.
- Whether to build EKS with managed node groups, Karpenter, or both for educational comparison.
- Whether to use AWS Managed Prometheus/Grafana or self-hosted Prometheus/Grafana first.
