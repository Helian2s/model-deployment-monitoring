#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
STATE_FILE="${STATE_FILE:-.ncp-genl/ec2-single-node.env}"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "missing state file: ${STATE_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$STATE_FILE"

if [[ -z "${INSTANCE_ID:-}" ]]; then
  echo "INSTANCE_ID is missing from ${STATE_FILE}" >&2
  exit 1
fi

AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" \
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" >/dev/null

AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" \
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"

state="$(AWS_PROFILE="$AWS_PROFILE" AWS_REGION="$AWS_REGION" \
  aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].State.Name' \
    --output text)"

printf 'INSTANCE_ID=%s STATE=%s\n' "$INSTANCE_ID" "$state"
