#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-037678282394}"
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
PLATFORM="${PLATFORM:-linux/amd64}"

LIFECYCLE_POLICY='{"rules":[{"rulePriority":1,"description":"Keep last 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'

images=(
  "nvcr.io/nvidia/tritonserver:26.05-vllm-python-py3|ncp-genl/tritonserver|26.05-vllm-python-py3"
  "nvcr.io/nvidia/tritonserver:26.05-py3-sdk|ncp-genl/tritonserver-sdk|26.05-py3-sdk"
  "nvcr.io/nvidia/cuda:12.4.1-base-ubuntu22.04|ncp-genl/cuda|12.4.1-base-ubuntu22.04"
  "nvcr.io/nvidia/k8s/dcgm-exporter:4.6.0-4.8.3-distroless|ncp-genl/dcgm-exporter|4.6.0-4.8.3-distroless"
  "nvcr.io/nvidia/cuda:13.2.1-base-ubuntu24.04|ncp-genl/cuda|13.2.1-base-ubuntu24.04"
  "nvcr.io/nvidia/tritonserver:26.06-vllm-python-py3|ncp-genl/tritonserver|26.06-vllm-python-py3"
  "nvcr.io/nvidia/tritonserver:26.06-py3-sdk|ncp-genl/tritonserver-sdk|26.06-py3-sdk"
  "nvcr.io/nvidia/tritonserver:26.05-trtllm-python-py3|ncp-genl/tritonserver|26.05-trtllm-python-py3"
  "nvcr.io/nvidia/tritonserver:26.06-trtllm-python-py3|ncp-genl/tritonserver|26.06-trtllm-python-py3"
  "nvcr.io/nvidia/k8s-device-plugin:v0.19.3|ncp-genl/k8s-device-plugin|v0.19.3"
  "nvcr.io/nvidia/nemo-microservices/guardrails:25.12|ncp-genl/nemo-guardrails|25.12"
  "nvcr.io/nvidia/eval-factory/garak:26.03|ncp-genl/garak|26.03"
  "nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3:1.12.0|ncp-genl/mistral-7b-instruct-v0.3-nim|1.12.0"
  "prom/prometheus:v3.13.1|ncp-genl/prometheus|v3.13.1"
  "grafana/grafana:13.0.3|ncp-genl/grafana|13.0.3"
  "prom/alertmanager:v0.33.1|ncp-genl/alertmanager|v0.33.1"
  "prom/node-exporter:v1.12.1|ncp-genl/node-exporter|v1.12.1"
  "gcr.io/cadvisor/cadvisor:v0.55.1|ncp-genl/cadvisor|v0.55.1"
)

extra_repos=(
  "ncp-genl/api-gateway"
)

source_docker_config="$(mktemp -d)"
ecr_docker_config="$(mktemp -d)"
cleanup() {
  rm -rf "$source_docker_config" "$ecr_docker_config"
}
trap cleanup EXIT

aws_cli() {
  AWS_PROFILE="$AWS_PROFILE" aws "$@"
}

ensure_repo() {
  local repo="$1"

  if ! aws_cli ecr describe-repositories \
    --region "$AWS_REGION" \
    --repository-names "$repo" >/dev/null 2>&1; then
    echo "CREATE_REPO $repo"
    aws_cli ecr create-repository \
      --region "$AWS_REGION" \
      --repository-name "$repo" \
      --image-scanning-configuration scanOnPush=true \
      --encryption-configuration encryptionType=AES256 >/dev/null
  else
    echo "REPO_EXISTS $repo"
  fi

  aws_cli ecr put-lifecycle-policy \
    --region "$AWS_REGION" \
    --repository-name "$repo" \
    --lifecycle-policy-text "$LIFECYCLE_POLICY" >/dev/null
}

image_tag_exists() {
  local repo="$1"
  local tag="$2"

  aws_cli ecr describe-images \
    --region "$AWS_REGION" \
    --repository-name "$repo" \
    --image-ids "imageTag=$tag" >/dev/null 2>&1
}

ecr_digest() {
  local repo="$1"
  local tag="$2"

  aws_cli ecr describe-images \
    --region "$AWS_REGION" \
    --repository-name "$repo" \
    --image-ids "imageTag=$tag" \
    --query 'imageDetails[0].imageDigest' \
    --output text
}

echo "AWS_PROFILE=$AWS_PROFILE"
echo "AWS_REGION=$AWS_REGION"
echo "ECR_REGISTRY=$ECR_REGISTRY"
echo "PLATFORM=$PLATFORM"

echo "LOGIN nvcr.io"
aws_cli ssm get-parameter \
  --region "$AWS_REGION" \
  --name /finetuning/ngc/api-key \
  --with-decryption \
  --query Parameter.Value \
  --output text \
| docker --config "$source_docker_config" login nvcr.io -u '$oauthtoken' --password-stdin >/dev/null

echo "LOGIN ECR"
aws_cli ecr get-login-password --region "$AWS_REGION" \
| docker --config "$ecr_docker_config" login \
    --username AWS \
    --password-stdin "$ECR_REGISTRY" >/dev/null

for repo in "${extra_repos[@]}"; do
  ensure_repo "$repo"
done

for row in "${images[@]}"; do
  IFS='|' read -r source_image target_repo target_tag <<< "$row"
  target_image="${ECR_REGISTRY}/${target_repo}:${target_tag}"

  echo "==== MIRROR ${source_image} -> ${target_image} ===="
  ensure_repo "$target_repo"

  if image_tag_exists "$target_repo" "$target_tag"; then
    echo "SKIP_EXISTS ${target_image} $(ecr_digest "$target_repo" "$target_tag")"
    continue
  fi

  docker --config "$source_docker_config" pull --platform "$PLATFORM" "$source_image"
  docker tag "$source_image" "$target_image"
  docker --config "$ecr_docker_config" push "$target_image"

  echo "PUSHED ${target_image} $(ecr_digest "$target_repo" "$target_tag")"
done

echo "DONE"
