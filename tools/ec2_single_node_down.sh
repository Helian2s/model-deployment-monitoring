#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
STATE_FILE="${STATE_FILE:-.ncp-genl/ec2-single-node.env}"
INSTANCE_ID="${INSTANCE_ID:-}"
DELETE_CACHE_VOLUME="${DELETE_CACHE_VOLUME:-false}"
CACHE_VOLUME_ID="${CACHE_VOLUME_ID:-}"

if [[ -f "$STATE_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"
fi

if [[ -z "${INSTANCE_ID:-}" ]]; then
  echo "INSTANCE_ID is required or ${STATE_FILE} must exist" >&2
  exit 1
fi

aws_cli() {
  AWS_PROFILE="$AWS_PROFILE" aws "$@"
}

echo "TERMINATE_INSTANCE ${INSTANCE_ID}"
aws_cli ec2 terminate-instances --region "$AWS_REGION" --instance-ids "$INSTANCE_ID" >/dev/null
aws_cli ec2 wait instance-terminated --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"

if [[ "${DELETE_CACHE_VOLUME}" == "true" ]]; then
  if [[ -z "${CACHE_VOLUME_ID:-}" ]]; then
    echo "CACHE_VOLUME_ID is required when DELETE_CACHE_VOLUME=true" >&2
    exit 1
  fi
  echo "WAIT_CACHE_VOLUME_AVAILABLE ${CACHE_VOLUME_ID}"
  aws_cli ec2 wait volume-available --region "$AWS_REGION" --volume-ids "$CACHE_VOLUME_ID"
  echo "DELETE_CACHE_VOLUME ${CACHE_VOLUME_ID}"
  aws_cli ec2 delete-volume --region "$AWS_REGION" --volume-id "$CACHE_VOLUME_ID"
else
  echo "KEEP_CACHE_VOLUME ${CACHE_VOLUME_ID:-unknown}"
fi
