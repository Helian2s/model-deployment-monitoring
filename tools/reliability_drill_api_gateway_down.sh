#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
STATE_FILE="${STATE_FILE:-.ncp-genl/ec2-single-node.env}"
INSTANCE_ID="${INSTANCE_ID:-}"
API_GATEWAY_HOST_PORT="${API_GATEWAY_HOST_PORT:-8088}"
ALERT_NAME="${ALERT_NAME:-ApiGatewayDown}"
ALERT_TIMEOUT_SECONDS="${ALERT_TIMEOUT_SECONDS:-240}"
RECOVERY_TIMEOUT_SECONDS="${RECOVERY_TIMEOUT_SECONDS:-180}"
REPORT_DIR="${REPORT_DIR:-reports}"

if [[ -z "$INSTANCE_ID" && -f "$STATE_FILE" ]]; then
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

send_ssm_script() {
  local script_file="$1"
  local comment="$2"
  local timeout_seconds="${3:-900}"
  local params_file command_id
  params_file="$(mktemp)"

  jq -n \
    --rawfile script "$script_file" \
    --arg timeout "$timeout_seconds" \
    '{
      commands: [
        "cat > /tmp/ncp-genl-api-gateway-down-drill.sh <<'\''REMOTE_SCRIPT'\''\n\($script)\nREMOTE_SCRIPT",
        "chmod +x /tmp/ncp-genl-api-gateway-down-drill.sh",
        "sudo /tmp/ncp-genl-api-gateway-down-drill.sh"
      ],
      executionTimeout: [$timeout]
    }' > "$params_file"

  command_id="$(aws_cli ssm send-command \
    --region "$AWS_REGION" \
    --document-name AWS-RunShellScript \
    --instance-ids "$INSTANCE_ID" \
    --comment "$comment" \
    --parameters "file://${params_file}" \
    --query 'Command.CommandId' \
    --output text)"
  rm -f "$params_file"

  local deadline status
  deadline=$((SECONDS + timeout_seconds + 120))
  while true; do
    status="$(aws_cli ssm get-command-invocation \
      --region "$AWS_REGION" \
      --command-id "$command_id" \
      --instance-id "$INSTANCE_ID" \
      --query 'Status' \
      --output text 2>/dev/null || true)"
    case "$status" in
      Success|Cancelled|Failed|TimedOut|Cancelling)
        break
        ;;
    esac
    if (( SECONDS > deadline )); then
      break
    fi
    sleep 5
  done

  aws_cli ssm get-command-invocation \
    --region "$AWS_REGION" \
    --command-id "$command_id" \
    --instance-id "$INSTANCE_ID" \
    --query '{Status:Status,ResponseCode:ResponseCode,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' \
    --output json
}

remote_script="$(mktemp)"
cat > "$remote_script" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

API_GATEWAY_HOST_PORT="__API_GATEWAY_HOST_PORT__"
ALERT_NAME="__ALERT_NAME__"
ALERT_TIMEOUT_SECONDS="__ALERT_TIMEOUT_SECONDS__"
RECOVERY_TIMEOUT_SECONDS="__RECOVERY_TIMEOUT_SECONDS__"

log() {
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >&2
}

iso_now() {
  date -u +'%Y-%m-%dT%H:%M:%SZ'
}

epoch_now() {
  date -u +'%s'
}

alert_state() {
  curl -fsS http://127.0.0.1:9090/api/v1/alerts \
    | jq -r --arg name "$ALERT_NAME" '[.data.alerts[] | select(.labels.alertname == $name) | .state][0] // "inactive"'
}

gateway_stopped=false
cleanup() {
  if [[ "$gateway_stopped" == "true" ]]; then
    log "CLEANUP_START_API_GATEWAY"
    docker start ncp-genl-api-gateway >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

log "CHECK_GATEWAY_READY_BEFORE_DRILL"
curl -fsS "http://127.0.0.1:${API_GATEWAY_HOST_PORT}/health/ready" >/dev/null

start_iso="$(iso_now)"
start_epoch="$(epoch_now)"
initial_state="$(alert_state)"

log "STOP_API_GATEWAY"
docker stop ncp-genl-api-gateway >/dev/null
gateway_stopped=true
stopped_iso="$(iso_now)"
stopped_epoch="$(epoch_now)"

pending_iso=""
pending_epoch=""
firing_iso=""
firing_epoch=""
last_down_state="inactive"

log "WAIT_ALERT_FIRING ${ALERT_NAME}"
deadline=$((SECONDS + ALERT_TIMEOUT_SECONDS))
while (( SECONDS <= deadline )); do
  state="$(alert_state)"
  last_down_state="$state"
  if [[ "$state" == "pending" && -z "$pending_iso" ]]; then
    pending_iso="$(iso_now)"
    pending_epoch="$(epoch_now)"
    log "ALERT_PENDING ${ALERT_NAME}"
  fi
  if [[ "$state" == "firing" ]]; then
    firing_iso="$(iso_now)"
    firing_epoch="$(epoch_now)"
    log "ALERT_FIRING ${ALERT_NAME}"
    break
  fi
  sleep 5
done

log "START_API_GATEWAY"
docker start ncp-genl-api-gateway >/dev/null
gateway_stopped=false
restarted_iso="$(iso_now)"
restarted_epoch="$(epoch_now)"

ready_iso=""
ready_epoch=""
log "WAIT_GATEWAY_READY"
deadline=$((SECONDS + RECOVERY_TIMEOUT_SECONDS))
while (( SECONDS <= deadline )); do
  if curl -fsS "http://127.0.0.1:${API_GATEWAY_HOST_PORT}/health/ready" >/dev/null 2>&1; then
    ready_iso="$(iso_now)"
    ready_epoch="$(epoch_now)"
    log "GATEWAY_READY"
    break
  fi
  sleep 5
done

cleared_iso=""
cleared_epoch=""
last_recovery_state="$(alert_state)"
log "WAIT_ALERT_CLEAR ${ALERT_NAME}"
deadline=$((SECONDS + RECOVERY_TIMEOUT_SECONDS))
while (( SECONDS <= deadline )); do
  state="$(alert_state)"
  last_recovery_state="$state"
  if [[ "$state" == "inactive" ]]; then
    cleared_iso="$(iso_now)"
    cleared_epoch="$(epoch_now)"
    log "ALERT_INACTIVE ${ALERT_NAME}"
    break
  fi
  sleep 5
done

container_status="$(docker inspect ncp-genl-api-gateway --format 'status={{.State.Status}} restart_count={{.RestartCount}} started_at={{.State.StartedAt}}')"
target_health="$(curl -fsS http://127.0.0.1:9090/api/v1/targets | jq -r '[.data.activeTargets[] | select(.labels.job == "api-gateway") | .health][0] // "missing"')"

alert_fired=false
gateway_recovered=false
alert_cleared=false
[[ -n "$firing_iso" ]] && alert_fired=true
[[ -n "$ready_iso" ]] && gateway_recovered=true
[[ -n "$cleared_iso" ]] && alert_cleared=true

detection_seconds=-1
if [[ -n "$firing_epoch" ]]; then
  detection_seconds=$((firing_epoch - stopped_epoch))
fi

recovery_seconds=-1
if [[ -n "$ready_epoch" ]]; then
  recovery_seconds=$((ready_epoch - restarted_epoch))
fi

alert_clear_seconds=-1
if [[ -n "$cleared_epoch" ]]; then
  alert_clear_seconds=$((cleared_epoch - restarted_epoch))
fi

jq -n \
  --arg drill "api-gateway-down" \
  --arg alert_name "$ALERT_NAME" \
  --arg started_at "$start_iso" \
  --arg stopped_at "$stopped_iso" \
  --arg pending_at "$pending_iso" \
  --arg firing_at "$firing_iso" \
  --arg restarted_at "$restarted_iso" \
  --arg ready_at "$ready_iso" \
  --arg cleared_at "$cleared_iso" \
  --arg initial_state "$initial_state" \
  --arg last_down_state "$last_down_state" \
  --arg last_recovery_state "$last_recovery_state" \
  --arg container_status "$container_status" \
  --arg target_health "$target_health" \
  --argjson alert_fired "$alert_fired" \
  --argjson gateway_recovered "$gateway_recovered" \
  --argjson alert_cleared "$alert_cleared" \
  --argjson detection_seconds "$detection_seconds" \
  --argjson recovery_seconds "$recovery_seconds" \
  --argjson alert_clear_seconds "$alert_clear_seconds" \
  '{
    drill: $drill,
    alert_name: $alert_name,
    timeline: {
      started_at: $started_at,
      gateway_stopped_at: $stopped_at,
      alert_pending_at: $pending_at,
      alert_firing_at: $firing_at,
      gateway_restarted_at: $restarted_at,
      gateway_ready_at: $ready_at,
      alert_cleared_at: $cleared_at
    },
    durations_seconds: {
      stop_to_firing: $detection_seconds,
      restart_to_ready: $recovery_seconds,
      restart_to_alert_clear: $alert_clear_seconds
    },
    states: {
      initial_alert_state: $initial_state,
      last_state_while_down: $last_down_state,
      last_state_after_recovery: $last_recovery_state,
      api_gateway_target_health: $target_health,
      api_gateway_container: $container_status
    },
    success: {
      alert_fired: $alert_fired,
      gateway_recovered: $gateway_recovered,
      alert_cleared: $alert_cleared
    }
  }'
REMOTE

sed -i \
  -e "s|__API_GATEWAY_HOST_PORT__|${API_GATEWAY_HOST_PORT}|g" \
  -e "s|__ALERT_NAME__|${ALERT_NAME}|g" \
  -e "s|__ALERT_TIMEOUT_SECONDS__|${ALERT_TIMEOUT_SECONDS}|g" \
  -e "s|__RECOVERY_TIMEOUT_SECONDS__|${RECOVERY_TIMEOUT_SECONDS}|g" \
  "$remote_script"

result="$(send_ssm_script "$remote_script" "Reliability drill: API gateway down" 900)"
rm -f "$remote_script"

stdout="$(printf '%s\n' "$result" | jq -r '.Stdout')"
stderr="$(printf '%s\n' "$result" | jq -r '.Stderr')"
status="$(printf '%s\n' "$result" | jq -r '.Status')"

if [[ -n "$stderr" && "$stderr" != "null" ]]; then
  printf '%s\n' "$stderr" >&2
fi

if [[ "$status" != "Success" ]]; then
  printf '%s\n' "$stdout"
  exit 1
fi

mkdir -p "$REPORT_DIR"
timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
json_report="${REPORT_DIR}/api-gateway-down-drill-${timestamp}.json"
md_report="${REPORT_DIR}/api-gateway-down-drill-${timestamp}.md"

printf '%s\n' "$stdout" | jq . > "$json_report"

alert_fired="$(jq -r '.success.alert_fired' "$json_report")"
gateway_recovered="$(jq -r '.success.gateway_recovered' "$json_report")"
alert_cleared="$(jq -r '.success.alert_cleared' "$json_report")"
stop_to_firing="$(jq -r '.durations_seconds.stop_to_firing' "$json_report")"
restart_to_ready="$(jq -r '.durations_seconds.restart_to_ready' "$json_report")"
restart_to_alert_clear="$(jq -r '.durations_seconds.restart_to_alert_clear' "$json_report")"
started_at="$(jq -r '.timeline.started_at' "$json_report")"
stopped_at="$(jq -r '.timeline.gateway_stopped_at' "$json_report")"
firing_at="$(jq -r '.timeline.alert_firing_at' "$json_report")"
ready_at="$(jq -r '.timeline.gateway_ready_at' "$json_report")"
cleared_at="$(jq -r '.timeline.alert_cleared_at' "$json_report")"
target_health="$(jq -r '.states.api_gateway_target_health' "$json_report")"

cat > "$md_report" <<EOF
# API Gateway Down Reliability Drill

Date: ${started_at}

## Scenario

The ncp-genl-api-gateway container was stopped to verify that Prometheus detects the outage and fires ${ALERT_NAME}. The gateway was then restarted and recovery was validated.

## Result

| Check | Result |
| --- | --- |
| Alert fired | \`${alert_fired}\` |
| Gateway recovered | \`${gateway_recovered}\` |
| Alert cleared | \`${alert_cleared}\` |
| Final Prometheus target health | \`${target_health}\` |

## Timeline

| Event | Time |
| --- | --- |
| Drill started | ${started_at} |
| Gateway stopped | ${stopped_at} |
| Alert firing | ${firing_at} |
| Gateway ready after restart | ${ready_at} |
| Alert cleared | ${cleared_at} |

## Durations

| Metric | Seconds |
| --- | ---: |
| Stop to alert firing | ${stop_to_firing} |
| Restart to gateway ready | ${restart_to_ready} |
| Restart to alert clear | ${restart_to_alert_clear} |

## Follow-Ups

- Repeat the drill after adding notification receivers to Alertmanager.
- Capture screenshots from Grafana and Alertmanager during the firing window.
- Add a similar drill for Triton container failure.
EOF

printf 'JSON report: %s\n' "$json_report"
printf 'Markdown report: %s\n' "$md_report"
printf '%s\n' "$stdout" | jq .

if [[ "$alert_fired" != "true" || "$gateway_recovered" != "true" || "$alert_cleared" != "true" ]]; then
  exit 2
fi
