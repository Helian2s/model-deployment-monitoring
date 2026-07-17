# Triton Smoke Test - Qwen 2.5 1.5B - 2026-07-16

## Result

Status: success.

This smoke test validated `Qwen/Qwen2.5-1.5B-Instruct` on the cheaper `g6.2xlarge` path using Triton vLLM.

Confirmed:

- `Qwen/Qwen2.5-1.5B-Instruct` loads successfully on NVIDIA L4.
- The model fits on `g6.2xlarge` with `max_model_len=2048`.
- Triton health endpoints work.
- Triton `/generate` works.
- Triton, vLLM, and GPU metrics are exposed from `/metrics`.
- GPU memory headroom remains, but the model already uses enough memory that `g6.2xlarge` should be treated carefully for concurrency/load tests.

## AWS Resources

- Region: `us-west-2`.
- Availability Zone: `us-west-2a`.
- Instance ID: `i-0535fe0af9a63c55f`.
- Instance type: `g6.2xlarge`.
- AMI: `ami-0f855e2020ff55dbc`.
- Security group: `sg-05cb80535bd97fc5e`.
- IAM role: `ncp-genl-smoke-ec2-role`.
- Instance profile: `ncp-genl-smoke-instance-profile`.
- Final instance state after cleanup: `terminated`.

All smoke-test resources were tagged:

- `Project=NCP-GENL`
- `Purpose=triton-smoke-test`
- `Model=Qwen2.5-1.5B-Instruct`
- `ManagedBy=codex`

## Hardware And Driver

Observed on the instance:

- GPU: NVIDIA L4.
- Driver: `595.71.05`.
- CUDA reported by driver: `13.2`.
- GPU memory: about 23 GiB.

## Image

Triton image:

```text
nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3
```

Triton pull digest:

```text
sha256:abf5043755e335fcb7b825d38caa18ea478179c5894e9b080d91143a5df37e67
```

CUDA GPU runtime check image:

```text
nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04
```

## Model

```text
Qwen/Qwen2.5-1.5B-Instruct
```

Model observations from vLLM logs:

- Weight download time: about `27.5` seconds.
- Checkpoint size: about `2.88 GiB`.
- Model loading memory: about `2.89 GiB`.
- Model loading time: about `29.5` seconds.
- Available KV cache memory: about `11.4 GiB`.
- Reported KV cache size: `427,104` tokens.
- Reported maximum concurrency for 2,048 tokens per request: `208.55x`.

That concurrency number is a vLLM capacity estimate, not a production SLO. Real load testing is still required.

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
  "model": "Qwen/Qwen2.5-1.5B-Instruct",
  "gpu_memory_utilization": 0.70,
  "max_model_len": 2048
}
```

## Health And Inference

Triton became ready after readiness poll attempt `23`.

Measured from container start:

```text
triton_ready_seconds=124
```

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
  "text_input": "Briefly explain why production monitoring matters for an LLM API.",
  "parameters": {
    "stream": false,
    "temperature": 0,
    "max_tokens": 96
  }
}
```

The model returned a coherent answer about monitoring, performance, reliability, security issues, downtime prevention, and user experience.

## Metrics Observed

After one inference:

- `vllm:prompt_tokens_total`: `13`
- `vllm:generation_tokens_total`: `96`
- `vllm:time_to_first_token_seconds_sum`: about `0.238`
- `vllm:e2e_request_latency_seconds_sum`: about `1.483`
- `vllm:time_per_output_token_seconds_sum`: about `1.245` over `95` output-token timing samples.
- `nv_gpu_memory_total_bytes`: `24152899584`
- `nv_gpu_memory_used_bytes`: `17195597824`
- `nv_gpu_power_usage`: about `30 W` from metrics, with `nvidia-smi` briefly showing full `72 W` during active inference.

`nvidia-smi` after inference:

```text
GPU memory used: 16400 MiB / 23034 MiB
GPU utilization: 100%
Processes:
- tritonserver: 250 MiB
- VLLM::EngineCore: 16136 MiB
```

This is still a smoke test, not a load benchmark. It proves the model is viable on `g6.2xlarge`.

## Notes

- The command emitted a Hugging Face warning about unauthenticated requests. The model still downloaded successfully. For repeatable production-style runs, use a Hugging Face token through SSM or Secrets Manager if rate limits become a problem.
- The model used substantially more GPU memory than `facebook/opt-125m`, but it fits comfortably enough for the next monitoring and light load-test phase.
- Keep `max_model_len=2048` for now. Increase only after baseline monitoring is in place.

## Cleanup

The smoke-test instance `i-0535fe0af9a63c55f` was terminated after the successful test to avoid ongoing GPU compute charges.

No persistent smoke-test volume is expected because the root EBS volume was configured with `DeleteOnTermination=true`.
