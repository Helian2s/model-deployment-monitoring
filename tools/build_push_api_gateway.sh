#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-037678282394}"
REPOSITORY="${REPOSITORY:-ncp-genl/api-gateway}"
TAG="${TAG:-dev-$(date -u +'%Y%m%d%H%M%S')}"
PUSH_LATEST="${PUSH_LATEST:-1}"
PLATFORM="${PLATFORM:-linux/amd64}"
SERVICE_DIR="${SERVICE_DIR:-services/api-gateway}"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${ECR_REGISTRY}/${REPOSITORY}:${TAG}"
LATEST_IMAGE="${ECR_REGISTRY}/${REPOSITORY}:latest"

aws_cli() {
  AWS_PROFILE="$AWS_PROFILE" aws "$@"
}

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

ensure_repository() {
  if aws_cli ecr describe-repositories \
    --region "$AWS_REGION" \
    --repository-names "$REPOSITORY" >/dev/null 2>&1; then
    log "ECR_REPOSITORY_EXISTS ${REPOSITORY}"
    return
  fi

  log "CREATE_ECR_REPOSITORY ${REPOSITORY}"
  aws_cli ecr create-repository \
    --region "$AWS_REGION" \
    --repository-name "$REPOSITORY" \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256 >/dev/null

  local lifecycle_policy
  lifecycle_policy="$(mktemp)"
  cat > "$lifecycle_policy" <<'JSON'
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep the last 10 images",
      "selection": {
        "tagStatus": "any",
        "countType": "imageCountMoreThan",
        "countNumber": 10
      },
      "action": {"type": "expire"}
    }
  ]
}
JSON
  aws_cli ecr put-lifecycle-policy \
    --region "$AWS_REGION" \
    --repository-name "$REPOSITORY" \
    --lifecycle-policy-text "file://${lifecycle_policy}" >/dev/null
  rm -f "$lifecycle_policy"
}

main() {
  ensure_repository

  local tmp_docker_config
  tmp_docker_config="$(mktemp -d)"
  trap "rm -rf '$tmp_docker_config'" EXIT

  log "ECR_LOGIN ${ECR_REGISTRY}"
  aws_cli ecr get-login-password --region "$AWS_REGION" \
    | docker --config "$tmp_docker_config" login \
      --username AWS \
      --password-stdin "$ECR_REGISTRY" >/dev/null

  log "BUILD_IMAGE ${IMAGE}"
  docker build --platform "$PLATFORM" -t "$IMAGE" "$SERVICE_DIR"

  if [[ "$PUSH_LATEST" == "1" ]]; then
    docker tag "$IMAGE" "$LATEST_IMAGE"
  fi

  log "PUSH_IMAGE ${IMAGE}"
  docker --config "$tmp_docker_config" push "$IMAGE"

  if [[ "$PUSH_LATEST" == "1" ]]; then
    log "PUSH_IMAGE ${LATEST_IMAGE}"
    docker --config "$tmp_docker_config" push "$LATEST_IMAGE"
  fi

  log "DONE ${IMAGE}"
}

main "$@"
