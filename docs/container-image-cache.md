# Container Image Cache And ECR Mirror

Last updated: 2026-07-16

## Decision

Mirror every container image that becomes part of the active lab path into Amazon ECR.

The source of truth remains the upstream registry, especially `nvcr.io` for NVIDIA images. The project workflow is:

1. Pull the pinned upstream image from `nvcr.io`.
2. Tag it under the project ECR repository.
3. Push it to ECR.
4. Use the ECR tag for repeated EC2 and EKS experiments.

This keeps startup faster and more reliable for repeated experiments, reduces repeated external downloads, and makes node runtime permissions simpler. ECR pull-through cache is not used for `nvcr.io`; use the manual pull, tag, push mirror process.

## AWS Target

Use:

```bash
AWS_PROFILE=finetuning-local
AWS_REGION=us-west-2
AWS_ACCOUNT_ID=037678282394
```

ECR repository prefix:

```text
037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/
```

## Compatibility Baseline

Use this baseline until we intentionally refresh the AMI/driver stack.

| Component | Current pin or observed value | Notes |
| --- | --- | --- |
| AWS region | `us-west-2` | Working region for smoke tests and ECR. |
| AMI | `ami-0f855e2020ff55dbc` | `Deep Learning Base AMI with Single CUDA (Ubuntu 24.04) 20260714`. |
| AMI architecture | `x86_64` | Use `linux/amd64` image variants. |
| Smoke-test GPU instance | `g6.2xlarge` | NVIDIA L4. |
| Optional larger GPU instance | `g6e.2xlarge` | NVIDIA L40S, only if needed. |
| Host NVIDIA driver | `595.71.05` | Observed during EC2 smoke tests. |
| Host CUDA shown by `nvidia-smi` | `13.2` | Observed during EC2 smoke tests. |
| Current Triton family | `26.05` | Validated with the current DLAMI and driver. |
| Triton container CUDA | `13.2.1.009` | Observed from `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3`. |
| Triton container driver baseline | `595.58.03` | Observed from the Triton `26.05` container metadata. |

Triton `26.06` tags are mirrored for cache readiness, but the current working runtime path remains Triton `26.05`. Do not switch serving or load-test workloads to `26.06` until it is validated against a refreshed AMI/driver stack.

Repository defaults:

- Scan on push: enabled.
- Encryption: AES256.
- Lifecycle policy: keep the last 10 pushed images per repository.

## Current ECR Repositories

| Repository | Status |
| --- | --- |
| `ncp-genl/tritonserver` | Active |
| `ncp-genl/tritonserver-sdk` | Active |
| `ncp-genl/cuda` | Active |
| `ncp-genl/dcgm-exporter` | Active |
| `ncp-genl/k8s-device-plugin` | Mirrored for later EKS phase |
| `ncp-genl/nemo-guardrails` | Mirrored for later safety/compliance phase |
| `ncp-genl/garak` | Mirrored for later safety/evaluation phase |
| `ncp-genl/mistral-7b-instruct-v0.3-nim` | Mirrored for later NIM comparison only |
| `ncp-genl/prometheus` | Mirrored for observability stack |
| `ncp-genl/grafana` | Mirrored for observability stack |
| `ncp-genl/alertmanager` | Mirrored for alerting stack |
| `ncp-genl/node-exporter` | Mirrored for observability stack |
| `ncp-genl/cadvisor` | Mirrored for container metrics |
| `ncp-genl/api-gateway` | Repository created; image not built yet |

## Mirrored Images

| Role | Upstream image | ECR image | ECR digest | Compressed size |
| --- | --- | --- | --- | --- |
| Triton vLLM server | `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver:26.05-vllm-python-py3` | `sha256:9ffac478000d307bbf459c3e838b4999f2dfb8bf6facaabfef8b8b6e7388eff8` | 9.99 GB |
| Triton SDK / Perf Analyzer / GenAI-Perf base | `nvcr.io/nvidia/tritonserver:26.05-py3-sdk` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver-sdk:26.05-py3-sdk` | `sha256:2d86bafe93293cf15d5fb584346f17d45451d69aaa53dbab613bea89da447d92` | 7.43 GB |
| CUDA smoke/debug utility | `nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/cuda:12.4.1-base-ubuntu22.04` | `sha256:937d4f9267751b09b744c48cdde3c6eae1b067f8ab91227442ae7001bab597ed` | 92.7 MB |
| GPU metrics exporter | `nvcr.io/nvidia/k8s/dcgm-exporter:4.6.0-4.8.3-distroless` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/dcgm-exporter:4.6.0-4.8.3-distroless` | `sha256:1cbae6d22389a1c8a98771bc6f1184f3f9f94d92a5164e69a2a5673504c6f074` | 58.0 MB |
| CUDA debug utility aligned to current AMI | `nvcr.io/nvidia/cuda:13.2.1-base-ubuntu24.04` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/cuda:13.2.1-base-ubuntu24.04` | `sha256:ae6a3c27c4bc5b5264447a07fbd3829495d722402fc66fc7e47de2afddcd0ae5` | 185 MB |
| Triton vLLM after future driver refresh | `nvcr.io/nvidia/tritonserver:26.06-vllm-python-py3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver:26.06-vllm-python-py3` | `sha256:f36974e6923d04c726feae9c1b8eba399b375993ecfa5734c2e48693c56d7ac2` | 10.97 GB |
| Triton SDK after future driver refresh | `nvcr.io/nvidia/tritonserver:26.06-py3-sdk` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver-sdk:26.06-py3-sdk` | `sha256:9524e2c0399c451cf3515d11c2b94c0945e79023406d8e21c7c5995f13fd800e` | 7.64 GB |
| TensorRT-LLM stretch on current baseline | `nvcr.io/nvidia/tritonserver:26.05-trtllm-python-py3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver:26.05-trtllm-python-py3` | `sha256:b820149c7818b56ef8320ec6f955aba79e273b9acc1e4b30290d0ee39c02ee96` | 15.27 GB |
| TensorRT-LLM stretch after future driver refresh | `nvcr.io/nvidia/tritonserver:26.06-trtllm-python-py3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver:26.06-trtllm-python-py3` | `sha256:9882caef7253324b993cc9c4b955f264f1971745209718f55a2dc9807f8dd734` | 15.29 GB |
| EKS GPU device plugin | `nvcr.io/nvidia/k8s-device-plugin:v0.19.3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/k8s-device-plugin:v0.19.3` | `sha256:12ccd1e70f232ceacfbec9869a9811e40677616a57de635b765c9ea83db80ec7` | 54.5 MB |
| NeMo Guardrails microservice | `nvcr.io/nvidia/nemo-microservices/guardrails:25.12` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/nemo-guardrails:25.12` | `sha256:e57dde84262301eb1e6caf76cb5f453f0aceade859e7eca826701af71bfad305` | 252 MB |
| NVIDIA Garak evaluator | `nvcr.io/nvidia/eval-factory/garak:26.03` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/garak:26.03` | `sha256:8769a586bdbdd5a637245b3fb54683a015999ea02930cacdb65b06dd8b50f35d` | 5.29 GB |
| Mistral NIM comparison | `nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3:1.12.0` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/mistral-7b-instruct-v0.3-nim:1.12.0` | `sha256:c0cfa76dc16b06f84de311a05ded6f5409d9c87106b9f1df998db164e4e1cc63` | 12.89 GB |
| Prometheus | `prom/prometheus:v3.13.1` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/prometheus:v3.13.1` | `sha256:bd2dcadfb0d1096e2a4c21817ac7af918e2f19ff628e4bf25fd67a924c13dd80` | 107 MB |
| Grafana | `grafana/grafana:13.0.3` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/grafana:13.0.3` | `sha256:65f8af7bd56f4010036ca45ef301deae30bd102880926bfd48f8c19be85b6fd8` | 352 MB |
| Alertmanager | `prom/alertmanager:v0.33.1` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/alertmanager:v0.33.1` | `sha256:a89f8d4520954079275441eecdb71444328bd90633dd4eddfc33b9ed657f349b` | 39.8 MB |
| Node exporter | `prom/node-exporter:v1.12.1` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/node-exporter:v1.12.1` | `sha256:da83fae85603c4e47e6c68369a7d746e2dda683dc35ea2e234b4f171e0d92798` | 13.4 MB |
| cAdvisor | `gcr.io/cadvisor/cadvisor:v0.55.1` | `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/cadvisor:v0.55.1` | `sha256:8c2a7908e0fa112277c5e30c2345ef02c0789b2042082e544e5a6daeab150f69` | 30.8 MB |

Total current `ncp-genl/*` image storage reported by ECR is about 85.95 GB.

The mirrored CUDA `12.4.1-base-ubuntu22.04` image was used successfully for initial Docker GPU smoke checks. For new debug utilities, prefer the matching CUDA `13.2.1-base-ubuntu24.04` tag.

## Mirror Command Pattern

Preferred repeatable command:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 \
  tools/mirror_container_images_to_ecr.sh
```

Use the normal Docker config for `nvcr.io` login. Use a temporary Docker config for ECR login to avoid changing the workstation's default Docker credential helper.

```bash
export AWS_PROFILE=finetuning-local
export AWS_REGION=us-west-2
export ECR_REGISTRY=037678282394.dkr.ecr.us-west-2.amazonaws.com

aws ssm get-parameter \
  --region "$AWS_REGION" \
  --name /finetuning/ngc/api-key \
  --with-decryption \
  --query Parameter.Value \
  --output text \
| docker login nvcr.io -u '$oauthtoken' --password-stdin

tmp_docker_config="$(mktemp -d)"

aws ecr get-login-password --region "$AWS_REGION" \
| docker --config "$tmp_docker_config" login \
    --username AWS \
    --password-stdin "$ECR_REGISTRY"

source_image="nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3"
target_image="$ECR_REGISTRY/ncp-genl/tritonserver:26.05-vllm-python-py3"

docker pull "$source_image"
docker tag "$source_image" "$target_image"
docker --config "$tmp_docker_config" push "$target_image"

rm -rf "$tmp_docker_config"
```

## Repositories Without Images

These repositories exist, but no image has been built or pushed yet.

| Repository | Reason |
| --- | --- |
| `ncp-genl/api-gateway` | Custom application image will be built after the gateway code exists. |

## Runtime Secrets

The following parameters exist in SSM Parameter Store as `SecureString` values. Their values must not be printed, committed, or written to logs.

| Purpose | SSM parameter |
| --- | --- |
| NGC / NVCR authentication | `/finetuning/ngc/api-key` |
| Hugging Face model access | `/finetuning/huggingface/token` |

Use the Hugging Face token at runtime when the model download path needs authentication, gated model access, or rate-limit protection. For the Triton/vLLM container, pass it as the standard Hugging Face token environment variable used by the runtime, preferably `HF_TOKEN`.

## Model Artifact Cache

Keep a reusable EBS volume for:

```text
/root/.cache/huggingface
```

This reduces repeated model downloads during EC2 smoke tests. Later phases may move model artifacts to S3, EFS, or FSx, depending on whether the learning objective is simple persistence, shared multi-node access, or higher-performance model loading.
