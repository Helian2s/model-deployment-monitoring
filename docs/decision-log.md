# Decision And Change Log

This file tracks project decisions and implementation changes. Add new entries at the top.

## 2026-07-17 UTC - EC2 Single-Node Triton Slice Deployed

- Added repeatable EC2 lifecycle scripts:
  - `tools/ec2_single_node_up.sh`.
  - `tools/ec2_single_node_validate.sh`.
  - `tools/ec2_single_node_down.sh`.
- Launched the first persistent production-style slice:
  - Instance `i-00020ad61c45f16a9`.
  - Instance type `g6.2xlarge`.
  - AMI `ami-0f855e2020ff55dbc`.
  - Region `us-west-2`, Availability Zone `us-west-2a`.
  - Security group `sg-05594cf6dd1c8cc20` with no inbound rules.
  - Reusable encrypted 150 GiB gp3 cache EBS volume `vol-03314a16bd7c78706`.
- Deployed `Qwen/Qwen2.5-1.5B-Instruct` through Triton `26.05-vllm-python-py3`.
- Bound service ports to `127.0.0.1` on the EC2 host and used SSM for access.
- Deployed ECR-mirrored containers for Triton, DCGM exporter, Prometheus, Alertmanager, Grafana, node exporter, and cAdvisor.
- Fixed EC2 redeploy idempotency:
  - Accept an already-mounted cache EBS volume.
  - Write local state to `.ncp-genl/ec2-single-node.env`.
  - Poll SSM commands with a custom timeout instead of the short AWS CLI waiter.
- Fixed Prometheus startup by setting ownership on the persistent Prometheus data directory.
- Tightened validation to print container restart counts, fail on live restart loops, and fail if any Prometheus target is not `up`.
- Validation passed:
  - Triton health and inference succeeded.
  - Triton `nv_inference_*` and `vllm:*` metrics were exposed.
  - DCGM GPU metrics were exposed.
  - Prometheus targets were all `up`.
  - Alertmanager and Grafana health checks passed.
- Prometheus retained `RestartCount=14` from the initial permission issue, but stayed running after `2026-07-17T02:17:39Z`.
- Documented the slice in `docs/ec2-single-node-slice-2026-07-17.md`.

## 2026-07-16 - Mirrored All Pinned Project Images To ECR

- Added repeatable mirror script `tools/mirror_container_images_to_ecr.sh`.
- Mirrored all active and planned pinned project images to ECR under account `037678282394`, region `us-west-2`.
- Created additional ECR repositories:
  - `ncp-genl/api-gateway` with no image yet.
  - `ncp-genl/k8s-device-plugin`.
  - `ncp-genl/nemo-guardrails`.
  - `ncp-genl/garak`.
  - `ncp-genl/prometheus`.
  - `ncp-genl/grafana`.
  - `ncp-genl/alertmanager`.
  - `ncp-genl/node-exporter`.
  - `ncp-genl/cadvisor`.
- Pushed additional NVIDIA/NVCR images:
  - `ncp-genl/cuda:13.2.1-base-ubuntu24.04`.
  - `ncp-genl/tritonserver:26.06-vllm-python-py3`.
  - `ncp-genl/tritonserver-sdk:26.06-py3-sdk`.
  - `ncp-genl/tritonserver:26.05-trtllm-python-py3`.
  - `ncp-genl/tritonserver:26.06-trtllm-python-py3`.
  - `ncp-genl/k8s-device-plugin:v0.19.3`.
  - `ncp-genl/nemo-guardrails:25.12`.
  - `ncp-genl/garak:26.03`.
  - `ncp-genl/mistral-7b-instruct-v0.3-nim:1.12.0`.
- Pushed observability images:
  - `ncp-genl/prometheus:v3.13.1`.
  - `ncp-genl/grafana:13.0.3`.
  - `ncp-genl/alertmanager:v0.33.1`.
  - `ncp-genl/node-exporter:v1.12.1`.
  - `ncp-genl/cadvisor:v0.55.1`.
- Verified ECR reports about `85.953 GB` of `ncp-genl/*` image storage after the mirror run.
- All `ncp-genl/*` repositories use scan-on-push, AES256 encryption, and a lifecycle policy that keeps the last 10 images.
- Local Docker image cache grew from about `180.6 GB` to about `272.3 GB` during the mirror run.
- This supersedes the earlier "do not mirror Triton 26.06 yet" cache decision. Triton `26.06` is now mirrored, but still should not be used for serving until a refreshed AMI/driver stack is validated.

## 2026-07-16 - Container Version Pinning Baseline

- Confirmed the current AWS AMI pin is `ami-0f855e2020ff55dbc`, named `Deep Learning Base AMI with Single CUDA (Ubuntu 24.04) 20260714`.
- Confirmed this is the newest matching Single CUDA Ubuntu 24.04 DLAMI visible in `us-west-2` during the check.
- Kept Triton `26.05` as the active Triton family because it was validated on the smoke-test host driver `595.71.05`.
- Observed Triton `26.05-vllm-python-py3` container metadata: CUDA `13.2.1.009`, CUDA driver baseline `595.58.03`, Triton Server `2.69.0`, NVIDIA Triton Server `26.05`, and vLLM `0.20.1+7124b12a`.
- Decided not to pull or mirror Triton `26.06` images yet. The tags exist, but they should wait until a refreshed AMI/driver stack is validated.
- Selected `nvcr.io/nvidia/cuda:13.2.1-base-ubuntu24.04` as the preferred future CUDA debug image because it aligns with the current AMI and Triton CUDA `13.2` baseline.
- Updated planned image pins:
  - `nvcr.io/nvidia/k8s-device-plugin:v0.19.3`.
  - `nvcr.io/nvidia/nemo-microservices/guardrails:25.12`.
  - `nvcr.io/nvidia/eval-factory/garak:26.03`.
  - `prom/prometheus:v3.13.1`.
  - `grafana/grafana:13.0.3`.
  - `prom/alertmanager:v0.33.1`.
  - `prom/node-exporter:v1.12.1`.
  - `gcr.io/cadvisor/cadvisor:v0.55.1`.
- Verified candidate manifests without pulling the large future images, to avoid unnecessary local and ECR downloads.

## 2026-07-16 - ECR Mirror And Model Cache Policy

- Decided to mirror every active lab container image into Amazon ECR after pulling from the upstream registry.
- Kept `nvcr.io` as the source of truth for NVIDIA images, but repeated EC2 and EKS runs should use ECR tags when available.
- Confirmed ECR pull-through cache is not being used for `nvcr.io`; use the manual pull, tag, push mirror process.
- Created ECR repositories in account `037678282394`, region `us-west-2`, with scan-on-push enabled and AES256 encryption:
  - `ncp-genl/tritonserver`.
  - `ncp-genl/tritonserver-sdk`.
  - `ncp-genl/cuda`.
  - `ncp-genl/dcgm-exporter`.
  - `ncp-genl/mistral-7b-instruct-v0.3-nim`.
- Pushed active images to ECR:
  - `ncp-genl/tritonserver:26.05-vllm-python-py3`, digest `sha256:9ffac478000d307bbf459c3e838b4999f2dfb8bf6facaabfef8b8b6e7388eff8`.
  - `ncp-genl/tritonserver-sdk:26.05-py3-sdk`, digest `sha256:2d86bafe93293cf15d5fb584346f17d45451d69aaa53dbab613bea89da447d92`.
  - `ncp-genl/cuda:12.4.1-base-ubuntu22.04`, digest `sha256:937d4f9267751b09b744c48cdde3c6eae1b067f8ab91227442ae7001bab597ed`.
  - `ncp-genl/dcgm-exporter:4.6.0-4.8.3-distroless`, digest `sha256:1cbae6d22389a1c8a98771bc6f1184f3f9f94d92a5164e69a2a5673504c6f074`.
- Created `ncp-genl/mistral-7b-instruct-v0.3-nim` only as a future repository. The Mistral NIM image was not pushed because NIM is outside the current Triton-only path.
- Confirmed `/finetuning/huggingface/token` exists as an SSM `SecureString`; use it at runtime for Hugging Face authentication, gated model access, or rate-limit protection without printing the value.
- Agreed to keep a reusable EBS volume for `/root/.cache/huggingface` during EC2 experiments. S3, EFS, or FSx can be evaluated later for shared or higher-performance model artifact storage.
- Added `docs/container-image-cache.md` to track image mirror policy, repositories, ECR tags, digests, secrets, and model cache decisions.

## 2026-07-16 - Qwen 1.5B Triton Smoke Test

- Selected `Qwen/Qwen2.5-1.5B-Instruct` as the next practical model after `facebook/opt-125m`.
- Launched fresh `g6.2xlarge` smoke-test instance `i-0535fe0af9a63c55f` in `us-west-2a`.
- Used AWS Deep Learning AMI `ami-0f855e2020ff55dbc`.
- Reused the SSM-only smoke-test support resources:
  - IAM role `ncp-genl-smoke-ec2-role`.
  - Instance profile `ncp-genl-smoke-instance-profile`.
  - Security group `sg-05cb80535bd97fc5e`.
- Confirmed NVIDIA L4 GPU with driver `595.71.05`.
- Used Triton image `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3`.
- Used vLLM model config with `gpu_memory_utilization=0.70` and `max_model_len=2048`.
- Successfully loaded `Qwen/Qwen2.5-1.5B-Instruct` with Triton vLLM backend.
- Triton became ready after readiness poll attempt `23`, about `124` seconds after container start.
- Qwen weights download took about `27.5` seconds; checkpoint size was about `2.88 GiB`.
- vLLM reported model loading took about `2.89 GiB` model memory and about `29.5` seconds.
- Observed GPU memory after serving startup and one request: about `16.4 GiB` used out of about `23.0 GiB`.
- Confirmed `/v2/health/live`, `/v2/health/ready`, `/v2/models/vllm_model/generate`, and `/metrics`.
- Confirmed one inference request generated `96` output tokens with `13` prompt tokens.
- Observed TTFT about `0.238` seconds and e2e request latency about `1.483` seconds for the single smoke-test request.
- Terminated smoke-test instance `i-0535fe0af9a63c55f` after capturing results to avoid ongoing GPU compute charges.

## 2026-07-16 - Triton Smoke Test

- Launched fresh `g6.2xlarge` smoke-test instance `i-0422b54d03896ccc5` in `us-west-2a`.
- Used AWS Deep Learning AMI `ami-0f855e2020ff55dbc`.
- Created fresh SSM-only support resources:
  - IAM role `ncp-genl-smoke-ec2-role`.
  - Instance profile `ncp-genl-smoke-instance-profile`.
  - Security group `sg-05cb80535bd97fc5e`.
- Confirmed instance GPU: NVIDIA L4 with driver `595.71.05`, CUDA `13.2`, and about 23 GiB GPU memory.
- Confirmed Docker GPU runtime with `nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04`.
- Confirmed NVCR login from EC2 using SSM SecureString `/finetuning/ngc/api-key`.
- Pulled `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3`.
- Switched smoke-test Triton image from `26.06` to `26.05` because the DLAMI driver is `595.71.05`.
- Found and fixed two Triton vLLM config issues:
  - Removed explicit `model_transaction_policy { decoupled: false }`; vLLM backend auto-complete sets transaction policy.
  - Removed `disable_log_requests`; Triton `26.05` vLLM backend rejects it as an unsupported `AsyncEngineArgs` argument.
- Successfully loaded `facebook/opt-125m` with Triton vLLM backend.
- Confirmed `/v2/health/live`, `/v2/health/ready`, `/v2/models/vllm_model/generate`, and `/metrics`.
- Confirmed vLLM custom metrics after inference, including prompt token count, generation token count, time-to-first-token histogram, per-output-token histogram, and e2e request latency histogram.
- Terminated smoke-test instance `i-0422b54d03896ccc5` after capturing results to avoid ongoing GPU compute charges.

## 2026-07-16

- Created project agreement document in `docs/project-agreements.md`.
- Created this decision/change log.
- Chose Triton-only model serving path for the first implementation.
- Deferred NVIDIA NIM deployment. NIM may be revisited later as a comparison, but it is not part of the current serving path.
- Retained NeMo Guardrails Microservice as the preferred NVIDIA safety layer.
- Agreed to prefer NVIDIA/NVCR images where they fit the project.
- Agreed to start with `g6.2xlarge` and move to `g6e.2xlarge` only if smaller models or 7B tests hit GPU memory/performance limits.
- Agreed not to rely on existing AWS launch templates. New infrastructure should be created from scratch.
- Agreed on staged model progression: tiny smoke-test model, then 1B/3B validation model, then 7B stretch.
- Confirmed `us-west-2` as the working AWS region.
- Confirmed `finetuning-local` as the working AWS profile.
- Confirmed NGC API key metadata exists in SSM at `/finetuning/ngc/api-key` as a `SecureString`; the value was not read for documentation.
- Confirmed local Docker access to key NVIDIA registry manifests for Triton, Triton SDK, TensorRT-LLM Triton image, DCGM exporter, CUDA, and NVIDIA device plugin.
