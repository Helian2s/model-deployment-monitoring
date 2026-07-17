#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-037678282394}"
PROJECT="${PROJECT:-ncp-genl}"
NAME_PREFIX="${NAME_PREFIX:-ncp-genl-ec2-slice}"

AMI_ID="${AMI_ID:-ami-0f855e2020ff55dbc}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g6.2xlarge}"
AZ="${AZ:-us-west-2a}"
CACHE_VOLUME_SIZE_GB="${CACHE_VOLUME_SIZE_GB:-150}"
CACHE_MOUNT="${CACHE_MOUNT:-/mnt/ncp-genl-cache}"
MODEL_ID="${MODEL_ID:-Qwen/Qwen2.5-1.5B-Instruct}"
MODEL_MAX_LEN="${MODEL_MAX_LEN:-2048}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.70}"

ROLE_NAME="${ROLE_NAME:-${NAME_PREFIX}-role}"
INSTANCE_PROFILE_NAME="${INSTANCE_PROFILE_NAME:-${NAME_PREFIX}-instance-profile}"
SSM_POLICY_ARN="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
ECR_POLICY_ARN="arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
INLINE_POLICY_NAME="${NAME_PREFIX}-ssm-secrets"
SG_NAME="${SG_NAME:-${NAME_PREFIX}-sg}"
CACHE_VOLUME_NAME="${CACHE_VOLUME_NAME:-ncp-genl-hf-cache}"
INSTANCE_NAME="${INSTANCE_NAME:-${NAME_PREFIX}}"
LOCAL_STATE_DIR="${LOCAL_STATE_DIR:-.ncp-genl}"
STATE_FILE="${STATE_FILE:-${LOCAL_STATE_DIR}/ec2-single-node.env}"

ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
TRITON_IMAGE="${TRITON_IMAGE:-${ECR_REGISTRY}/ncp-genl/tritonserver:26.05-vllm-python-py3}"
DCGM_IMAGE="${DCGM_IMAGE:-${ECR_REGISTRY}/ncp-genl/dcgm-exporter:4.6.0-4.8.3-distroless}"
PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-${ECR_REGISTRY}/ncp-genl/prometheus:v3.13.1}"
GRAFANA_IMAGE="${GRAFANA_IMAGE:-${ECR_REGISTRY}/ncp-genl/grafana:13.0.3}"
ALERTMANAGER_IMAGE="${ALERTMANAGER_IMAGE:-${ECR_REGISTRY}/ncp-genl/alertmanager:v0.33.1}"
NODE_EXPORTER_IMAGE="${NODE_EXPORTER_IMAGE:-${ECR_REGISTRY}/ncp-genl/node-exporter:v1.12.1}"
CADVISOR_IMAGE="${CADVISOR_IMAGE:-${ECR_REGISTRY}/ncp-genl/cadvisor:v0.55.1}"

aws_cli() {
  AWS_PROFILE="$AWS_PROFILE" aws "$@"
}

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

json_string() {
  jq -Rn --arg v "$1" '$v'
}

ensure_local_state_dir() {
  mkdir -p "$LOCAL_STATE_DIR"
}

default_vpc_id() {
  aws_cli ec2 describe-vpcs \
    --region "$AWS_REGION" \
    --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' \
    --output text
}

subnet_for_az() {
  local vpc_id="$1"
  aws_cli ec2 describe-subnets \
    --region "$AWS_REGION" \
    --filters "Name=vpc-id,Values=${vpc_id}" "Name=availability-zone,Values=${AZ}" "Name=default-for-az,Values=true" \
    --query 'Subnets[0].SubnetId' \
    --output text
}

ensure_iam() {
  local trust policy_doc
  trust="$(mktemp)"
  policy_doc="$(mktemp)"

  cat > "$trust" <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }
  ]
}
JSON

  if ! aws_cli iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    log "CREATE_ROLE ${ROLE_NAME}"
    aws_cli iam create-role \
      --role-name "$ROLE_NAME" \
      --assume-role-policy-document "file://${trust}" >/dev/null
  else
    log "ROLE_EXISTS ${ROLE_NAME}"
  fi

  aws_cli iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$SSM_POLICY_ARN" >/dev/null
  aws_cli iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$ECR_POLICY_ARN" >/dev/null

  cat > "$policy_doc" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": [
        "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/finetuning/huggingface/token",
        "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/finetuning/ngc/api-key"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "*"
    }
  ]
}
JSON

  aws_cli iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "$INLINE_POLICY_NAME" \
    --policy-document "file://${policy_doc}" >/dev/null

  if ! aws_cli iam get-instance-profile --instance-profile-name "$INSTANCE_PROFILE_NAME" >/dev/null 2>&1; then
    log "CREATE_INSTANCE_PROFILE ${INSTANCE_PROFILE_NAME}"
    aws_cli iam create-instance-profile --instance-profile-name "$INSTANCE_PROFILE_NAME" >/dev/null
  else
    log "INSTANCE_PROFILE_EXISTS ${INSTANCE_PROFILE_NAME}"
  fi

  if ! aws_cli iam get-instance-profile \
    --instance-profile-name "$INSTANCE_PROFILE_NAME" \
    --query "InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'].RoleName" \
    --output text | rg -q "^${ROLE_NAME}$"; then
    aws_cli iam add-role-to-instance-profile \
      --instance-profile-name "$INSTANCE_PROFILE_NAME" \
      --role-name "$ROLE_NAME" >/dev/null
    log "WAIT_INSTANCE_PROFILE_PROPAGATION"
    sleep 12
  fi

  rm -f "$trust" "$policy_doc"
}

ensure_security_group() {
  local vpc_id="$1"
  local sg_id

  sg_id="$(aws_cli ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --filters "Name=vpc-id,Values=${vpc_id}" "Name=group-name,Values=${SG_NAME}" \
    --query 'SecurityGroups[0].GroupId' \
    --output text)"

  if [[ "$sg_id" == "None" || -z "$sg_id" ]]; then
    log "CREATE_SECURITY_GROUP ${SG_NAME}"
    sg_id="$(aws_cli ec2 create-security-group \
      --region "$AWS_REGION" \
      --group-name "$SG_NAME" \
      --description "NCP-GENL EC2 single-node slice; SSM only, no inbound" \
      --vpc-id "$vpc_id" \
      --query 'GroupId' \
      --output text)"
    aws_cli ec2 create-tags \
      --region "$AWS_REGION" \
      --resources "$sg_id" \
      --tags "Key=Name,Value=${SG_NAME}" "Key=Project,Value=${PROJECT}" "Key=ManagedBy,Value=codex" >/dev/null
  else
    log "SECURITY_GROUP_EXISTS ${sg_id}"
  fi

  # Remove any existing inbound permissions. The slice is accessed by SSM only.
  local ingress_json
  ingress_json="$(aws_cli ec2 describe-security-groups \
    --region "$AWS_REGION" \
    --group-ids "$sg_id" \
    --query 'SecurityGroups[0].IpPermissions' \
    --output json)"
  if [[ "$ingress_json" != "[]" ]]; then
    local tmp_ingress
    tmp_ingress="$(mktemp)"
    printf '%s' "$ingress_json" > "$tmp_ingress"
    aws_cli ec2 revoke-security-group-ingress \
      --region "$AWS_REGION" \
      --group-id "$sg_id" \
      --ip-permissions "file://${tmp_ingress}" >/dev/null || true
    rm -f "$tmp_ingress"
  fi

  printf '%s\n' "$sg_id"
}

ensure_cache_volume() {
  local volume_id
  volume_id="$(aws_cli ec2 describe-volumes \
    --region "$AWS_REGION" \
    --filters "Name=tag:Name,Values=${CACHE_VOLUME_NAME}" "Name=tag:Project,Values=${PROJECT}" "Name=availability-zone,Values=${AZ}" \
    --query "Volumes[?State!='deleted'] | [0].VolumeId" \
    --output text)"

  if [[ "$volume_id" == "None" || -z "$volume_id" ]]; then
    log "CREATE_CACHE_VOLUME ${CACHE_VOLUME_NAME} ${CACHE_VOLUME_SIZE_GB}GiB ${AZ}"
    volume_id="$(aws_cli ec2 create-volume \
      --region "$AWS_REGION" \
      --availability-zone "$AZ" \
      --size "$CACHE_VOLUME_SIZE_GB" \
      --volume-type gp3 \
      --encrypted \
      --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=${CACHE_VOLUME_NAME}},{Key=Project,Value=${PROJECT}},{Key=Role,Value=hf-cache},{Key=ManagedBy,Value=codex}]" \
      --query 'VolumeId' \
      --output text)"
    aws_cli ec2 wait volume-available --region "$AWS_REGION" --volume-ids "$volume_id"
  else
    log "CACHE_VOLUME_EXISTS ${volume_id}"
  fi

  local state
  state="$(aws_cli ec2 describe-volumes --region "$AWS_REGION" --volume-ids "$volume_id" --query 'Volumes[0].State' --output text)"
  if [[ "$state" != "available" && "$state" != "in-use" ]]; then
    log "CACHE_VOLUME_NOT_AVAILABLE ${volume_id} state=${state}"
    exit 1
  fi

  printf '%s\n' "$volume_id"
}

existing_instance_id() {
  aws_cli ec2 describe-instances \
    --region "$AWS_REGION" \
    --filters "Name=tag:Name,Values=${INSTANCE_NAME}" "Name=tag:Project,Values=${PROJECT}" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[0].InstanceId | [0]' \
    --output text
}

launch_instance() {
  local subnet_id="$1"
  local sg_id="$2"
  local instance_id

  instance_id="$(existing_instance_id)"
  if [[ "$instance_id" != "None" && -n "$instance_id" ]]; then
    local state
    state="$(aws_cli ec2 describe-instances --region "$AWS_REGION" --instance-ids "$instance_id" --query 'Reservations[0].Instances[0].State.Name' --output text)"
    log "INSTANCE_EXISTS ${instance_id} state=${state}"
    if [[ "$state" == "stopped" ]]; then
      aws_cli ec2 start-instances --region "$AWS_REGION" --instance-ids "$instance_id" >/dev/null
    fi
    printf '%s\n' "$instance_id"
    return
  fi

  log "RUN_INSTANCE ${AMI_ID} ${INSTANCE_TYPE} ${subnet_id}"
  instance_id="$(aws_cli ec2 run-instances \
    --region "$AWS_REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --iam-instance-profile "Name=${INSTANCE_PROFILE_NAME}" \
    --network-interfaces "DeviceIndex=0,SubnetId=${subnet_id},Groups=[${sg_id}],AssociatePublicIpAddress=true" \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=200,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${INSTANCE_NAME}},{Key=Project,Value=${PROJECT}},{Key=Role,Value=ec2-single-node},{Key=ManagedBy,Value=codex}]" \
    --query 'Instances[0].InstanceId' \
    --output text)"

  printf '%s\n' "$instance_id"
}

attach_cache_volume() {
  local instance_id="$1"
  local volume_id="$2"
  local attached

  attached="$(aws_cli ec2 describe-volumes \
    --region "$AWS_REGION" \
    --volume-ids "$volume_id" \
    --query 'Volumes[0].Attachments[0].InstanceId' \
    --output text)"

  if [[ "$attached" == "$instance_id" ]]; then
    log "CACHE_VOLUME_ALREADY_ATTACHED ${volume_id}"
    return
  fi
  if [[ "$attached" != "None" && -n "$attached" ]]; then
    log "CACHE_VOLUME_ATTACHED_ELSEWHERE ${volume_id} ${attached}"
    exit 1
  fi

  log "ATTACH_CACHE_VOLUME ${volume_id} -> ${instance_id}"
  aws_cli ec2 attach-volume \
    --region "$AWS_REGION" \
    --volume-id "$volume_id" \
    --instance-id "$instance_id" \
    --device /dev/sdf >/dev/null
  aws_cli ec2 wait volume-in-use --region "$AWS_REGION" --volume-ids "$volume_id"
}

wait_for_instance_and_ssm() {
  local instance_id="$1"
  log "WAIT_INSTANCE_RUNNING ${instance_id}"
  aws_cli ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$instance_id"
  aws_cli ec2 wait instance-status-ok --region "$AWS_REGION" --instance-ids "$instance_id"

  log "WAIT_SSM_ONLINE ${instance_id}"
  for _ in $(seq 1 80); do
    local status
    status="$(aws_cli ssm describe-instance-information \
      --region "$AWS_REGION" \
      --filters "Key=InstanceIds,Values=${instance_id}" \
      --query 'InstanceInformationList[0].PingStatus' \
      --output text 2>/dev/null || true)"
    if [[ "$status" == "Online" ]]; then
      return
    fi
    sleep 10
  done

  log "SSM_NOT_ONLINE ${instance_id}"
  exit 1
}

send_ssm_script() {
  local instance_id="$1"
  local script_file="$2"
  local comment="$3"
  local timeout_seconds="${4:-7200}"
  local params_file command_id
  params_file="$(mktemp)"

  jq -n \
    --rawfile script "$script_file" \
    --arg timeout "$timeout_seconds" \
    '{
      commands: [
        "cat > /tmp/ncp-genl-remote-script.sh <<'\''REMOTE_SCRIPT'\''\n\($script)\nREMOTE_SCRIPT",
        "chmod +x /tmp/ncp-genl-remote-script.sh",
        "sudo /tmp/ncp-genl-remote-script.sh"
      ],
      executionTimeout: [$timeout]
    }' > "$params_file"

  command_id="$(aws_cli ssm send-command \
    --region "$AWS_REGION" \
    --document-name AWS-RunShellScript \
    --instance-ids "$instance_id" \
    --comment "$comment" \
    --parameters "file://${params_file}" \
    --query 'Command.CommandId' \
    --output text)"

  rm -f "$params_file"

  log "SSM_COMMAND ${command_id} ${comment}"
  local deadline status
  deadline=$((SECONDS + timeout_seconds + 300))
  while true; do
    status="$(aws_cli ssm get-command-invocation \
      --region "$AWS_REGION" \
      --command-id "$command_id" \
      --instance-id "$instance_id" \
      --query 'Status' \
      --output text 2>/dev/null || true)"
    case "$status" in
      Success|Cancelled|Failed|TimedOut|Cancelling)
        break
        ;;
    esac
    if (( SECONDS > deadline )); then
      log "SSM_COMMAND_WAIT_TIMEOUT ${command_id} status=${status}"
      break
    fi
    sleep 15
  done

  aws_cli ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --query '{Status:Status,ResponseCode:ResponseCode,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' \
    --output json
}

write_remote_deploy_script() {
  local path="$1"

  cat > "$path" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="__AWS_REGION__"
ECR_REGISTRY="__ECR_REGISTRY__"
CACHE_VOLUME_ID="__CACHE_VOLUME_ID__"
CACHE_MOUNT="__CACHE_MOUNT__"
MODEL_ID="__MODEL_ID__"
MODEL_MAX_LEN="__MODEL_MAX_LEN__"
GPU_MEMORY_UTILIZATION="__GPU_MEMORY_UTILIZATION__"
TRITON_IMAGE="__TRITON_IMAGE__"
DCGM_IMAGE="__DCGM_IMAGE__"
PROMETHEUS_IMAGE="__PROMETHEUS_IMAGE__"
GRAFANA_IMAGE="__GRAFANA_IMAGE__"
ALERTMANAGER_IMAGE="__ALERTMANAGER_IMAGE__"
NODE_EXPORTER_IMAGE="__NODE_EXPORTER_IMAGE__"
CADVISOR_IMAGE="__CADVISOR_IMAGE__"
export AWS_REGION ECR_REGISTRY CACHE_VOLUME_ID CACHE_MOUNT MODEL_ID MODEL_MAX_LEN
export GPU_MEMORY_UTILIZATION TRITON_IMAGE DCGM_IMAGE PROMETHEUS_IMAGE
export GRAFANA_IMAGE ALERTMANAGER_IMAGE NODE_EXPORTER_IMAGE CADVISOR_IMAGE

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

required_env=(
  AWS_REGION
  ECR_REGISTRY
  CACHE_VOLUME_ID
  CACHE_MOUNT
  MODEL_ID
  MODEL_MAX_LEN
  GPU_MEMORY_UTILIZATION
  TRITON_IMAGE
  DCGM_IMAGE
  PROMETHEUS_IMAGE
  GRAFANA_IMAGE
  ALERTMANAGER_IMAGE
  NODE_EXPORTER_IMAGE
  CADVISOR_IMAGE
)

for name in "${required_env[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "missing environment: ${name}" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive

log "ENABLE_DOCKER"
systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  log "INSTALL_DOCKER_COMPOSE_PLUGIN"
  apt-get update
  apt-get install -y docker-compose-plugin
fi

if ! command -v jq >/dev/null 2>&1; then
  log "INSTALL_JQ"
  apt-get update
  apt-get install -y jq
fi

find_cache_device() {
  local wanted_no_dash="${CACHE_VOLUME_ID//-/}"
  for dev in /dev/nvme*n1; do
    [[ -b "$dev" ]] || continue
    if command -v ebsnvme-id >/dev/null 2>&1; then
      local info
      info="$(ebsnvme-id "$dev" 2>/dev/null || true)"
      if printf '%s\n' "$info" | grep -qE "${CACHE_VOLUME_ID}|${wanted_no_dash}"; then
        printf '%s\n' "$dev"
        return
      fi
    fi
  done

  for dev in /dev/xvdf /dev/sdf; do
    [[ -b "$dev" ]] && { printf '%s\n' "$dev"; return; }
  done

  # Fallback for single attached data volume. Exclude root-mounted devices.
  for dev in /dev/nvme*n1; do
    [[ -b "$dev" ]] || continue
    if ! lsblk -no MOUNTPOINT "$dev" | grep -q '/'; then
      printf '%s\n' "$dev"
      return
    fi
  done
}

mkdir -p "$CACHE_MOUNT"
if findmnt -rn --target "$CACHE_MOUNT" >/dev/null 2>&1; then
  CACHE_DEVICE="$(findmnt -rn --target "$CACHE_MOUNT" -o SOURCE | head -n1)"
  log "CACHE_MOUNT_ALREADY_ACTIVE ${CACHE_MOUNT} source=${CACHE_DEVICE}"
else
  CACHE_DEVICE="$(find_cache_device)"
  if [[ -z "$CACHE_DEVICE" ]]; then
    echo "Could not find cache volume device for ${CACHE_VOLUME_ID}" >&2
    lsblk >&2
    exit 1
  fi

  log "CACHE_DEVICE ${CACHE_DEVICE}"
  if ! blkid "$CACHE_DEVICE" >/dev/null 2>&1; then
    log "FORMAT_CACHE_DEVICE ${CACHE_DEVICE}"
    mkfs.ext4 -F "$CACHE_DEVICE"
  fi
fi

if [[ -b "$CACHE_DEVICE" ]]; then
  UUID="$(blkid -s UUID -o value "$CACHE_DEVICE" || true)"
  if [[ -n "$UUID" ]] && ! grep -q "$UUID" /etc/fstab; then
    printf 'UUID=%s %s ext4 defaults,nofail 0 2\n' "$UUID" "$CACHE_MOUNT" >> /etc/fstab
  fi
fi

if ! findmnt -rn --target "$CACHE_MOUNT" >/dev/null 2>&1; then
  mount "$CACHE_MOUNT" || mount -a
fi

mkdir -p \
  "$CACHE_MOUNT/huggingface" \
  /opt/ncp-genl/model_repository/vllm_model/1 \
  /opt/ncp-genl/prometheus \
  /opt/ncp-genl/alertmanager \
  /opt/ncp-genl/grafana \
  /opt/ncp-genl/data/prometheus \
  /opt/ncp-genl/data/alertmanager \
  /opt/ncp-genl/data/grafana

chmod 700 "$CACHE_MOUNT/huggingface"
chown -R 65534:65534 /opt/ncp-genl/data/prometheus /opt/ncp-genl/data/alertmanager
chown -R 472:472 /opt/ncp-genl/data/grafana

cat > /opt/ncp-genl/model_repository/vllm_model/config.pbtxt <<'EOF'
backend: "vllm"
max_batch_size: 0
parameters: {
  key: "REPORT_CUSTOM_METRICS"
  value: { string_value: "true" }
}
EOF

jq -n \
  --arg model "$MODEL_ID" \
  --argjson gpu "$GPU_MEMORY_UTILIZATION" \
  --argjson max_len "$MODEL_MAX_LEN" \
  '{model:$model,gpu_memory_utilization:$gpu,max_model_len:$max_len}' \
  > /opt/ncp-genl/model_repository/vllm_model/1/model.json

log "FETCH_HF_TOKEN_METADATA"
HF_TOKEN_VALUE="$(aws ssm get-parameter \
  --region "$AWS_REGION" \
  --name /finetuning/huggingface/token \
  --with-decryption \
  --query Parameter.Value \
  --output text)"

cat > /opt/ncp-genl/.hf.env <<EOF
HF_TOKEN=${HF_TOKEN_VALUE}
HUGGING_FACE_HUB_TOKEN=${HF_TOKEN_VALUE}
HF_HOME=/root/.cache/huggingface
TRANSFORMERS_CACHE=/root/.cache/huggingface
EOF
chmod 600 /opt/ncp-genl/.hf.env

cat > /opt/ncp-genl/prometheus/prometheus.yml <<'EOF'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/alerts.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["prometheus:9090"]

  - job_name: triton
    metrics_path: /metrics
    static_configs:
      - targets: ["triton:8002"]

  - job_name: dcgm-exporter
    static_configs:
      - targets: ["dcgm-exporter:9400"]

  - job_name: node-exporter
    static_configs:
      - targets: ["node-exporter:9100"]

  - job_name: cadvisor
    static_configs:
      - targets: ["cadvisor:8080"]
EOF

cat > /opt/ncp-genl/prometheus/alerts.yml <<'EOF'
groups:
  - name: llm-api-single-node
    rules:
      - alert: TritonMetricsDown
        expr: up{job="triton"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Triton metrics endpoint is down"

      - alert: GpuMetricsDown
        expr: up{job="dcgm-exporter"} == 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "DCGM exporter is down"

      - alert: HostMetricsDown
        expr: up{job="node-exporter"} == 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Node exporter is down"
EOF

cat > /opt/ncp-genl/alertmanager/alertmanager.yml <<'EOF'
route:
  receiver: default
receivers:
  - name: default
EOF

cat > /opt/ncp-genl/docker-compose.yml <<EOF
services:
  triton:
    image: ${TRITON_IMAGE}
    container_name: ncp-genl-triton
    restart: unless-stopped
    gpus: all
    ipc: host
    shm_size: "8gb"
    env_file:
      - /opt/ncp-genl/.hf.env
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility,video
    command:
      - tritonserver
      - --model-repository=/models
    ports:
      - "127.0.0.1:8000:8000"
      - "127.0.0.1:8001:8001"
      - "127.0.0.1:8002:8002"
    volumes:
      - /opt/ncp-genl/model_repository:/models:ro
      - ${CACHE_MOUNT}/huggingface:/root/.cache/huggingface

  dcgm-exporter:
    image: ${DCGM_IMAGE}
    container_name: ncp-genl-dcgm-exporter
    restart: unless-stopped
    gpus: all
    cap_add:
      - SYS_ADMIN
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
    ports:
      - "127.0.0.1:9400:9400"

  prometheus:
    image: ${PROMETHEUS_IMAGE}
    container_name: ncp-genl-prometheus
    restart: unless-stopped
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --web.enable-lifecycle
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - /opt/ncp-genl/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /opt/ncp-genl/prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro
      - /opt/ncp-genl/data/prometheus:/prometheus

  alertmanager:
    image: ${ALERTMANAGER_IMAGE}
    container_name: ncp-genl-alertmanager
    restart: unless-stopped
    ports:
      - "127.0.0.1:9093:9093"
    volumes:
      - /opt/ncp-genl/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - /opt/ncp-genl/data/alertmanager:/alertmanager

  grafana:
    image: ${GRAFANA_IMAGE}
    container_name: ncp-genl-grafana
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - /opt/ncp-genl/data/grafana:/var/lib/grafana

  node-exporter:
    image: ${NODE_EXPORTER_IMAGE}
    container_name: ncp-genl-node-exporter
    restart: unless-stopped
    pid: host
    command:
      - --path.rootfs=/host
    ports:
      - "127.0.0.1:9100:9100"
    volumes:
      - /:/host:ro,rslave

  cadvisor:
    image: ${CADVISOR_IMAGE}
    container_name: ncp-genl-cadvisor
    restart: unless-stopped
    privileged: true
    devices:
      - /dev/kmsg
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker:/var/lib/docker:ro
      - /dev/disk:/dev/disk:ro
EOF

log "ECR_LOGIN"
aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null

log "PULL_IMAGES"
docker compose -f /opt/ncp-genl/docker-compose.yml pull

log "START_STACK"
docker compose -f /opt/ncp-genl/docker-compose.yml up -d

log "WAIT_TRITON_READY"
for i in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8000/v2/health/ready >/dev/null 2>&1; then
    log "TRITON_READY attempt=${i}"
    break
  fi
  if [[ "$i" == "120" ]]; then
    log "TRITON_NOT_READY"
    docker logs --tail 200 ncp-genl-triton || true
    exit 1
  fi
  sleep 10
done

log "STACK_STATUS"
docker compose -f /opt/ncp-genl/docker-compose.yml ps
REMOTE

  sed -i \
    -e "s|__AWS_REGION__|${AWS_REGION}|g" \
    -e "s|__ECR_REGISTRY__|${ECR_REGISTRY}|g" \
    -e "s|__CACHE_VOLUME_ID__|${CACHE_VOLUME_ID_PLACEHOLDER:-__CACHE_VOLUME_ID__}|g" \
    -e "s|__CACHE_MOUNT__|${CACHE_MOUNT}|g" \
    -e "s|__MODEL_ID__|${MODEL_ID}|g" \
    -e "s|__MODEL_MAX_LEN__|${MODEL_MAX_LEN}|g" \
    -e "s|__GPU_MEMORY_UTILIZATION__|${GPU_MEMORY_UTILIZATION}|g" \
    -e "s|__TRITON_IMAGE__|${TRITON_IMAGE}|g" \
    -e "s|__DCGM_IMAGE__|${DCGM_IMAGE}|g" \
    -e "s|__PROMETHEUS_IMAGE__|${PROMETHEUS_IMAGE}|g" \
    -e "s|__GRAFANA_IMAGE__|${GRAFANA_IMAGE}|g" \
    -e "s|__ALERTMANAGER_IMAGE__|${ALERTMANAGER_IMAGE}|g" \
    -e "s|__NODE_EXPORTER_IMAGE__|${NODE_EXPORTER_IMAGE}|g" \
    -e "s|__CADVISOR_IMAGE__|${CADVISOR_IMAGE}|g" \
    "$path"
}

deploy_stack() {
  local instance_id="$1"
  local volume_id="$2"
  local remote_script result status
  remote_script="$(mktemp)"
  CACHE_VOLUME_ID_PLACEHOLDER="$volume_id" write_remote_deploy_script "$remote_script"

  result="$(send_ssm_script "$instance_id" "$remote_script" "Deploy NCP-GENL single-node Triton stack" 7200)"
  rm -f "$remote_script"
  printf '%s\n' "$result"
  status="$(printf '%s\n' "$result" | jq -r '.Status')"
  if [[ "$status" != "Success" ]]; then
    exit 1
  fi
}

main() {
  ensure_local_state_dir

  local vpc_id subnet_id sg_id volume_id instance_id
  vpc_id="$(default_vpc_id)"
  if [[ "$vpc_id" == "None" || -z "$vpc_id" ]]; then
    log "DEFAULT_VPC_NOT_FOUND"
    exit 1
  fi
  subnet_id="$(subnet_for_az "$vpc_id")"
  if [[ "$subnet_id" == "None" || -z "$subnet_id" ]]; then
    log "DEFAULT_SUBNET_NOT_FOUND az=${AZ} vpc=${vpc_id}"
    exit 1
  fi

  ensure_iam
  sg_id="$(ensure_security_group "$vpc_id")"
  volume_id="$(ensure_cache_volume)"
  instance_id="$(launch_instance "$subnet_id" "$sg_id")"

  wait_for_instance_and_ssm "$instance_id"
  attach_cache_volume "$instance_id" "$volume_id"
  sleep 8
  deploy_stack "$instance_id" "$volume_id"

  cat > "$STATE_FILE" <<EOF
AWS_PROFILE=${AWS_PROFILE}
AWS_REGION=${AWS_REGION}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID}
INSTANCE_ID=${instance_id}
CACHE_VOLUME_ID=${volume_id}
SECURITY_GROUP_ID=${sg_id}
SUBNET_ID=${subnet_id}
AVAILABILITY_ZONE=${AZ}
INSTANCE_NAME=${INSTANCE_NAME}
CACHE_VOLUME_NAME=${CACHE_VOLUME_NAME}
EOF

  log "STATE_FILE ${STATE_FILE}"
  log "INSTANCE_ID ${instance_id}"
  log "CACHE_VOLUME_ID ${volume_id}"
}

main "$@"
