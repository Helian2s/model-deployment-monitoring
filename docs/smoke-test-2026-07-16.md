# Triton Smoke Test - 2026-07-16

## Result

Status: success.

The smoke test validated the first Triton-only deployment path on AWS `g6.2xlarge`.

Confirmed:

- AWS profile `finetuning-local` can provision and control the test instance.
- `g6.2xlarge` can run NVIDIA L4 GPU workloads.
- Docker GPU runtime works.
- NVCR login works from EC2 using SSM SecureString `/finetuning/ngc/api-key`.
- Triton vLLM image can be pulled from `nvcr.io`.
- Triton can load a minimal vLLM model repository.
- Triton health endpoints work.
- Triton `/generate` works.
- Triton, vLLM, and GPU metrics are exposed from `/metrics`.

## AWS Resources

- Region: `us-west-2`.
- Availability Zone: `us-west-2a`.
- Instance ID: `i-0422b54d03896ccc5`.
- Instance type: `g6.2xlarge`.
- Final instance state after cleanup: `terminated`.
- AMI: `ami-0f855e2020ff55dbc`.
- Security group: `sg-05cb80535bd97fc5e`.
- IAM role: `ncp-genl-smoke-ec2-role`.
- Instance profile: `ncp-genl-smoke-instance-profile`.

All smoke-test resources were tagged:

- `Project=NCP-GENL`
- `Purpose=triton-smoke-test`
- `ManagedBy=codex`

## Hardware And Driver

Observed on the instance:

- GPU: NVIDIA L4.
- Driver: `595.71.05`.
- CUDA reported by driver: `13.2`.
- GPU memory: about 23 GiB.

The driver generation is compatible with Triton `26.05`. Triton `26.06` should be used only after selecting an AMI or driver stack that satisfies its newer driver requirement.

## Images Validated

- `nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04`
- `nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3`

The Triton image pull completed successfully:

```text
Digest: sha256:abf5043755e335fcb7b825d38caa18ea478179c5894e9b080d91143a5df37e67
Status: Downloaded newer image for nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3
```

## Model

Smoke-test model:

```text
facebook/opt-125m
```

Purpose:

- Validate Triton vLLM mechanics before moving to 1B/3B models.
- Keep model download and startup time small.
- Prove the model repository shape and `/generate` endpoint.

## Working Model Repository

`config.pbtxt`:

```protobuf
backend: "vllm"
max_batch_size: 0
parameters: {
  key: "REPORT_CUSTOM_METRICS"
  value: {
    string_value: "true"
  }
}
```

`1/model.json`:

```json
{
  "model": "facebook/opt-125m",
  "gpu_memory_utilization": 0.40,
  "max_model_len": 512
}
```

Important findings:

- Do not explicitly set `model_transaction_policy.decoupled` for this Triton vLLM backend path.
- Do not include `disable_log_requests` with Triton `26.05`; the backend rejects it as an unsupported `AsyncEngineArgs` argument.

## Working Triton Command

```bash
docker run -d \
  --gpus all \
  --net=host \
  --name triton-smoke \
  --shm-size=1g \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v /opt/ncp-genl-smoke:/work \
  -w /work \
  nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3 \
  tritonserver --model-repository /work/model_repository
```

## Health And Inference

Triton became ready after readiness poll attempt `13`.

Validated endpoints:

```text
GET  /v2/health/live
GET  /v2/health/ready
GET  /metrics
POST /v2/models/vllm_model/generate
```

Inference request:

```json
{
  "text_input": "What is Triton Inference Server?",
  "parameters": {
    "stream": false,
    "temperature": 0,
    "max_tokens": 32
  }
}
```

Inference response:

```json
{
  "model_name": "vllm_model",
  "model_version": "1",
  "text_output": "What is Triton Inference Server?\n\nTriton Inference Server is a server that is used by many different applications. It is a server that is used by many different applications. It"
}
```

## Metrics Observed

After one inference:

- `vllm:prompt_tokens_total`: `10`
- `vllm:generation_tokens_total`: `32`
- `vllm:time_to_first_token_seconds_sum`: about `0.234`
- `vllm:e2e_request_latency_seconds_sum`: about `0.284`
- `nv_gpu_memory_total_bytes`: `24152899584`
- `nv_gpu_memory_used_bytes`: about `9933160448`
- `nv_gpu_power_usage`: about `28.463`

This is not a benchmark. It only proves that the metrics path works.

## Failed Attempts And Fixes

1. SSM defaulted to `/bin/sh`, which rejected `set -o pipefail`.
   - Fix: pass the script through `bash`.

2. Installing `awscli` from apt failed on Ubuntu 24.04.
   - Fix: use the AWS CLI already present in the DLAMI.

3. Installing Ubuntu `docker.io` conflicted with Docker CE packages already present on the AMI.
   - Fix: use the AMI Docker installation.

4. Triton vLLM rejected explicit `decoupled: false`.
   - Fix: remove `model_transaction_policy` from `config.pbtxt`.

5. Triton vLLM rejected `disable_log_requests`.
   - Fix: keep `model.json` minimal.

## Next Smoke-Test Step

Use the same infrastructure to test a 1B/3B model, likely:

- `Qwen/Qwen2.5-1.5B-Instruct`, or
- `Qwen/Qwen2.5-3B-Instruct`.

Then add Prometheus and DCGM exporter around the working Triton container.

## Cleanup

The smoke-test instance `i-0422b54d03896ccc5` was terminated after the successful test to avoid ongoing GPU compute charges.

The reusable IAM role, instance profile, and security group were left in place for later smoke tests:

- `ncp-genl-smoke-ec2-role`
- `ncp-genl-smoke-instance-profile`
- `sg-05cb80535bd97fc5e`
