# Decision And Change Log

This file tracks project decisions and implementation changes. Add new entries at the top.

## 2026-07-17 UTC - EC2 Pause And Boot Resume

- Added systemd service `ncp-genl-stack.service` during EC2 deployment.
- The service runs `docker compose -f /opt/ncp-genl/docker-compose.yml up -d` on boot after Docker, network-online, and the model-cache mount are available.
- All Compose services already use `restart: unless-stopped`.
- Added validation for the boot service in `tools/ec2_single_node_validate.sh`.
- Added `tools/ec2_single_node_stop.sh` to stop the EC2 instance without terminating it.
- Reboot-tested instance `i-0762eca19198f5272`; systemd started all 10 project containers automatically.
- Full validation passed after the cold model load completed. Triton reported `nv_model_load_duration_secs` around `163` seconds for `Qwen/Qwen2.5-1.5B-Instruct`, so operators should wait several minutes after EC2 start before expecting full API readiness.
- Paused the project by running `tools/ec2_single_node_stop.sh`; AWS confirmed instance `i-0762eca19198f5272` is `stopped`.
- Volume state after pause:
  - root EBS volume `vol-09ce946a85fe86d2f`, 200 GiB, attached, delete-on-termination `true`;
  - reusable model-cache EBS volume `vol-0040803576e31c710`, 150 GiB, attached, delete-on-termination `false`.
- Intended pause workflow:
  - stop with `tools/ec2_single_node_stop.sh`;
  - later start the EC2 instance;
  - wait for SSM;
  - run `tools/ec2_single_node_validate.sh`.

## 2026-07-17 UTC - Helpdesk Guardrails Config And Priority Policy

- Added source-controlled NeMo Guardrails config:
  - `services/nemo-guardrails/configs/helpdesk-triage.json`.
  - Config ID: `helpdesk-triage`.
  - Registered idempotently during EC2 deployment through the NeMo config API.
- Switched the live gateway config from `default` to `helpdesk-triage`.
- Tested an LLM-based NeMo `self_check_input` prompt for the helpdesk scenario. It still false-positive blocked a normal payroll-access ticket, so it is not enabled.
- Kept deterministic gateway safety checks as the enforced input safety layer.
- Added deterministic helpdesk priority policy after model validation:
  - corrects clear P1/P2/P3/P4 mistakes from ticket text;
  - emits `api_gateway_helpdesk_triage_repairs_total{field="priority",reason="policy_override"}`;
  - caps confidence at `0.79` when priority is overridden.
- Built and pushed gateway image:
  - `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.3.4`.
  - Digest: `sha256:81d5c5aebaac7114b54c7a89bfa1eefede03df7fc82cfddaef50c1145c1e3db2`.
- Deployed `api-gateway:0.3.4` to EC2 instance `i-0762eca19198f5272`.
- Validation passed:
  - all 10 containers running with restart count `0`;
  - NeMo config list includes `helpdesk-triage`;
  - `helpdesk-triage` input flows are empty, so the false-positive LLM self-check remains disabled;
  - helpdesk payroll validation ticket returned final `P2` with confidence `0.79`;
  - prompt-injection test returned HTTP `403`;
  - unauthenticated direct call to `/internal/v1/chat/completions` returned HTTP `401`;
  - Prometheus targets were all `up`.
- Ran post-priority-policy sample-set evaluation:
  - Report: `reports/helpdesk-triage-eval-20260717T211023Z.md`.
  - Requests: `8`.
  - Succeeded: `8`.
  - Failed: `0`.
  - p95 latency: `1.292` seconds.
  - Category accuracy: `62.50%`.
  - Priority accuracy: `100.00%`.
  - Routing queue accuracy: `62.50%`.
- Current quality finding: priority is fixed on the smoke set, while category and routing still need a larger dataset and policy/prompt work.

## 2026-07-17 UTC - Live NeMo Guardrails And Scenario Quality Monitoring

- Wired NeMo Guardrails into the live `/v1/helpdesk/triage` request path:
  - Public request: API gateway `/v1/helpdesk/triage`.
  - Guardrails call: NeMo `/v1/guardrail/chat/completions`.
  - Model call from NeMo: API gateway `/internal/v1/chat/completions`.
  - Backend inference: Triton vLLM `vllm_model`.
- Added a guarded internal OpenAI-compatible endpoint, disabled by default and enabled only in the EC2 stack.
- Hardened the internal endpoint so it still requires the gateway API key when API-key enforcement is enabled.
- Passed the gateway API key to NeMo through `NIM_API_KEY` and `NIM_ENDPOINT_API_KEY`.
- Added deterministic gateway input checks:
  - prompt injection and possible secrets are blocked with HTTP `403`;
  - possible PII and security-sensitive content are flagged and merged into output `safety_flags`.
- Added deterministic output repair for narrow schema-shape errors:
  - single-item arrays for scalar fields;
  - string or empty `safety_flags`;
  - invalid `routing_queue` repaired from a valid category default.
- Added guardrails and scenario-quality metrics:
  - `api_gateway_guardrails_requests_total`.
  - `api_gateway_guardrails_duration_seconds`.
  - `api_gateway_guardrails_interventions_total`.
  - `api_gateway_helpdesk_triage_low_confidence_total`.
  - `api_gateway_helpdesk_triage_repairs_total`.
- Added Prometheus helpdesk scenario alerts for p95 latency, invalid output, Guardrails failures, blocked inputs, low confidence, and output repairs.
- Expanded the Grafana dashboard with panels for helpdesk latency, outcomes, category/priority distribution, Guardrails requests/interventions, confidence, safety flags, low-confidence decisions, and output repairs.
- Built and pushed gateway image:
  - `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.3.3`.
  - Digest: `sha256:3bf2eb677ff3ce3adceea3ca0e3f978c142d1d4d83f2110774ea6ec5176c7aa5`.
- Deployed `api-gateway:0.3.3` to EC2 instance `i-0762eca19198f5272`.
- Validation passed:
  - all 10 containers running with restart count `0`;
  - chat completion succeeded;
  - helpdesk triage succeeded through the live NeMo path;
  - prompt-injection test returned HTTP `403`;
  - unauthenticated direct call to `/internal/v1/chat/completions` returned HTTP `401`;
  - Prometheus targets were all `up`;
  - scenario alert rules and Grafana panels were provisioned.
- Ran post-Guardrails sample-set evaluation:
  - Report: `reports/helpdesk-triage-eval-20260717T205427Z.md`.
  - Requests: `8`.
  - Succeeded: `8`.
  - Failed: `0`.
  - p95 latency: `1.400` seconds.
  - Category accuracy: `62.50%`.
  - Priority accuracy: `25.00%`.
  - Routing queue accuracy: `62.50%`.
- Important finding: the bundled NeMo `self-check` config was too broad for this scenario and blocked a normal payroll-access ticket. The live path uses NeMo `default` plus deterministic gateway checks until a scenario-specific NeMo config is created.

## 2026-07-17 UTC - IT Helpdesk Triage Scenario Slice

- Selected the IT Helpdesk Triage Assistant as the first business scenario.
- Added `POST /v1/helpdesk/triage` to the API gateway.
- Added a strict triage response contract:
  - `category`.
  - `priority`.
  - `routing_queue`.
  - `summary`.
  - `recommended_action`.
  - `confidence`.
  - `requires_human`.
  - `safety_flags`.
- Added Pydantic validation for model output. Invalid model JSON or schema mismatches return `502` and increment the helpdesk invalid-output metric.
- Added helpdesk quality metrics:
  - `api_gateway_helpdesk_triage_total`.
  - `api_gateway_helpdesk_triage_decisions_total`.
  - `api_gateway_helpdesk_triage_confidence`.
  - `api_gateway_helpdesk_triage_safety_flags_total`.
- Added normalized dataset scaffolding:
  - `schemas/helpdesk-ticket.schema.json`.
  - `data/helpdesk/samples/helpdesk_triage_sample.jsonl`.
  - `tools/helpdesk_dataset_ingest.py`.
- Added evaluation tooling:
  - `tools/helpdesk_triage_eval.py`.
  - Reports saved under `reports/`.
- Built and pushed gateway images:
  - `ncp-genl/api-gateway:0.2.0`, digest `sha256:dfb314aa123b1a6bab73af60970b761d1b58e828e9feff660f51d5a35d5f234a`.
  - `ncp-genl/api-gateway:0.2.1`, digest `sha256:45e503437df67d4082fb5efede9ec53f00fff910edc86a72549080e17dd2f26b`.
- Deployed `api-gateway:0.2.1` to EC2 instance `i-0762eca19198f5272`.
- Updated EC2 validation to call `/v1/helpdesk/triage`.
- Validation passed with all 10 containers running and all Prometheus targets up.
- Ran first sample-set evaluation:
  - Report: `reports/helpdesk-triage-eval-20260717T200831Z.md`.
  - Requests: `8`.
  - Succeeded: `8`.
  - Failed: `0`.
  - p95 latency: `1.404` seconds.
  - Category accuracy: `62.50%`.
  - Priority accuracy: `25.00%`.
  - Routing queue accuracy: `62.50%`.
- The first baseline confirms endpoint reliability and exposes model-quality gaps, especially priority assignment and overconfidence.
- Documented the scenario in `docs/helpdesk-triage-scenario.md`.

## 2026-07-17 UTC - Deployed NeMo Guardrails And Triton SDK Toolbox

- Added `ncp-genl-nemo-guardrails` to the EC2 Docker Compose stack:
  - Image: `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/nemo-guardrails:25.12`.
  - Host binding: `127.0.0.1:7331`.
  - Persistent SQLite storage: `/opt/ncp-genl/data/nemo-guardrails`.
  - Health endpoints validated: `/v1/health` and `/v1/health/ready`.
  - Bundled configs validated through `/v1/guardrail/configs`: `abc`, `self-check`, and `default`.
- Added `ncp-genl-tritonserver-sdk` to the EC2 Docker Compose stack:
  - Image: `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/tritonserver-sdk:26.05-py3-sdk`.
  - Runs as a long-lived toolbox container with `sleep infinity`.
  - Validated `perf_analyzer`, `genai-perf`, Python `tritonclient`, and Python `genai_perf`.
- Updated `.ncp-genl/ec2-single-node.env` with the Guardrails and SDK image pins.
- Updated validation to include the two new containers.
- Redeployed the active instance `i-0762eca19198f5272` successfully.
- Full validation passed after redeploy:
  - All 10 containers running.
  - All active containers had `RestartCount=0`.
  - Triton inference and API gateway chat completion succeeded.
  - Prometheus targets were all `up`.
  - Prometheus active-alert query returned no active alerts.
- Guardrails is intentionally not yet in the live gateway request path. The next safety step is gateway-to-Guardrails integration and guardrail quality metrics.

## 2026-07-17 UTC - API Gateway Down Reliability Drill

- Added `tools/reliability_drill_api_gateway_down.sh`.
- The drill:
  - Verifies gateway readiness before fault injection.
  - Stops `ncp-genl-api-gateway`.
  - Polls Prometheus until `ApiGatewayDown` becomes `firing`.
  - Restarts the gateway.
  - Waits for gateway readiness and alert clearing.
  - Saves JSON and Markdown reports under `reports/`.
- Ran the drill successfully:
  - Gateway stopped at `2026-07-17T18:07:58Z`.
  - `ApiGatewayDown` became `pending` at `2026-07-17T18:08:09Z`.
  - `ApiGatewayDown` became `firing` at `2026-07-17T18:09:09Z`.
  - Gateway readiness recovered at `2026-07-17T18:09:14Z`.
  - Alert cleared at `2026-07-17T18:09:24Z`.
- Measured timings:
  - Stop to alert firing: `70` seconds.
  - Restart to gateway ready: `5` seconds.
  - Restart to alert clear: `15` seconds.
- Confirmed post-drill recovery:
  - Full EC2 stack validation passed.
  - Prometheus active-alert query returned no active alerts.
  - Final `api-gateway` target health was `up`.
- Documented the drill in `docs/reliability-drill-api-gateway-down-2026-07-17.md`.

## 2026-07-17 UTC - Monitoring Dashboard, Alerts, And Baseline Load Test

- Added Grafana provisioning to the EC2 stack:
  - Prometheus datasource UID `prometheus`.
  - Dashboard folder `NCP-GENL`.
  - Dashboard UID `ncp-genl-llm-api`.
- Added the `NCP-GENL LLM API` dashboard with panels for:
  - API gateway request rate.
  - Gateway p50/p95/p99 latency.
  - Gateway and Triton request outcomes.
  - Token throughput.
  - GPU utilization and memory.
  - Prometheus target health.
- Expanded Prometheus alert rules:
  - `ApiGateway5xxResponses`.
  - `ApiGatewayP95LatencyHigh`.
  - `TritonInferenceFailures`.
  - `NoSuccessfulInference`.
  - `GpuMemoryHigh`.
- Updated validation to confirm:
  - Prometheus alert rules are loaded.
  - Grafana Prometheus datasource is provisioned.
  - Grafana dashboard `ncp-genl-llm-api` is provisioned.
- Added `tools/gateway_baseline_load_test.sh`.
- Ran baseline gateway load:
  - `20` requests.
  - concurrency `2`.
  - `20` succeeded, `0` failed.
  - client p95 latency about `1.064` seconds.
  - client throughput about `2.114` requests/sec.
- Prometheus snapshot after the baseline run:
  - gateway requests in 10m: about `20.615`.
  - gateway successes in 10m: about `20.615`.
  - gateway failures: no failed series.
  - gateway p95 latency by histogram query: about `1.75` seconds.
  - GPU framebuffer memory usage: about `72.7%`.
- Checked active alerts after the baseline run; no alerts were firing.
- Documented the monitoring baseline in `docs/monitoring-baseline-2026-07-17.md`.

## 2026-07-17 UTC - API Gateway Deployed Into EC2 Slice

- Pushed `ncp-genl/api-gateway:0.1.0` to ECR:
  - `037678282394.dkr.ecr.us-west-2.amazonaws.com/ncp-genl/api-gateway:0.1.0`.
  - Digest `sha256:e5b0232e924223088ca48f614dfa04dc0de4e4e634e9f7dd1086e408921d54c2`.
  - Compressed size about 56.8 MB.
- Created SSM SecureString `/ncp-genl/api-gateway/api-key`.
- Updated the EC2 instance role inline policy so the host can read the gateway API key.
- Added `ncp-genl-api-gateway` to the EC2 Docker Compose stack.
- Bound the gateway on the EC2 host as `127.0.0.1:8088` because cAdvisor already uses host port `8080`.
- Added `api-gateway:8080/metrics` as a Prometheus scrape target.
- Added starter Prometheus alerts:
  - `ApiGatewayDown`.
  - `ApiGatewayTritonFailures`.
- Updated validation to call `/v1/chat/completions` through the gateway with the API key fetched from SSM.
- Encountered `InsufficientInstanceCapacity` starting the stopped `us-west-2a` `g6.2xlarge`.
- Moved the active slice to `us-west-2c`:
  - Active instance `i-0762eca19198f5272`.
  - Active cache volume `vol-0040803576e31c710`.
  - Stopped old 2a instance remains `i-00020ad61c45f16a9`.
- Fixed an EBS cache mount bug: `/mnt/ncp-genl-cache` must be checked with `mountpoint`, not `findmnt --target`, because the latter matched the root filesystem.
- Verified the corrected cache mount:
  - `/mnt/ncp-genl-cache` mounted from `/dev/nvme2n1`.
  - ext4 filesystem.
  - UUID `39839e7f-6def-4ff5-b1fb-a5a259af2d87`.
- Deleted the empty 2b cache volume created during the failed fallback attempt.
- Validation passed:
  - Gateway health and chat completion succeeded.
  - Gateway metrics were exposed.
  - Prometheus target `api-gateway` was `up`.
  - Triton, DCGM exporter, node exporter, cAdvisor, Prometheus, Alertmanager, and Grafana remained healthy.

## 2026-07-17 UTC - API Gateway Baseline Added

- Added a FastAPI-based API gateway under `services/api-gateway`.
- Implemented:
  - `POST /v1/chat/completions`.
  - `GET /health/live`.
  - `GET /health/ready`.
  - `GET /metrics`.
  - Qwen2.5 ChatML prompt formatting.
  - Triton `/v2/models/vllm_model/generate` forwarding.
  - API-key enforcement when configured.
  - in-memory per-principal rate limiting.
  - request IDs via `x-request-id`.
  - metadata-only JSON request logs.
  - Prometheus gateway metrics.
  - Triton timeout and upstream error mapping.
- Added `services/api-gateway/Dockerfile` and built `ncp-genl/api-gateway:local` successfully.
- The container runs as a non-root `app` user.
- Added tests for prompt formatting, OpenAI-compatible response shape, and API-key enforcement.
- Added `tools/build_push_api_gateway.sh` to build and push the custom image to ECR after AWS authentication is refreshed.
- Did not push the gateway image to ECR yet because the local AWS session had expired and requires `aws login`.
- Documented the gateway in `docs/api-gateway.md`.

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
