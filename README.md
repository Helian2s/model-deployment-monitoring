# model-deployment-monitoring

Hands-on NCP-GENL preparation project for deploying and operating a production-style LLM API with NVIDIA Triton Inference Server on AWS.

## Project Notes

- [Project agreements](docs/project-agreements.md)
- [Decision and change log](docs/decision-log.md)
- [Container image cache and ECR mirror](docs/container-image-cache.md)
- [Initial Triton smoke test](docs/smoke-test-2026-07-16.md)
- [Qwen 1.5B Triton smoke test](docs/smoke-test-qwen-1.5b-2026-07-16.md)
- [EC2 single-node Triton slice](docs/ec2-single-node-slice-2026-07-17.md)

## Current EC2 Slice

Deploy or redeploy:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_up.sh
```

Validate:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_validate.sh
```

Terminate the GPU instance while preserving the reusable model-cache EBS volume:

```bash
AWS_PROFILE=finetuning-local AWS_REGION=us-west-2 ./tools/ec2_single_node_down.sh
```
