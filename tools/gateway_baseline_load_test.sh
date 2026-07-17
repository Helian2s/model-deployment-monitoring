#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-finetuning-local}"
AWS_REGION="${AWS_REGION:-us-west-2}"
STATE_FILE="${STATE_FILE:-.ncp-genl/ec2-single-node.env}"
INSTANCE_ID="${INSTANCE_ID:-}"
API_GATEWAY_HOST_PORT="${API_GATEWAY_HOST_PORT:-8088}"
API_GATEWAY_API_KEY_PARAM="${API_GATEWAY_API_KEY_PARAM:-/ncp-genl/api-gateway/api-key}"

REQUESTS="${REQUESTS:-20}"
CONCURRENCY="${CONCURRENCY:-2}"
MAX_TOKENS="${MAX_TOKENS:-64}"
TEMPERATURE="${TEMPERATURE:-0.2}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-120}"
PROMPT="${PROMPT:-Briefly explain one reliability practice for a production LLM API.}"

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
        "cat > /tmp/ncp-genl-gateway-load.sh <<'\''REMOTE_SCRIPT'\''\n\($script)\nREMOTE_SCRIPT",
        "chmod +x /tmp/ncp-genl-gateway-load.sh",
        "sudo /tmp/ncp-genl-gateway-load.sh"
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

prompt_b64="$(printf '%s' "$PROMPT" | base64 -w0)"
remote_script="$(mktemp)"
cat > "$remote_script" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="__AWS_REGION__"
API_GATEWAY_HOST_PORT="__API_GATEWAY_HOST_PORT__"
API_GATEWAY_API_KEY_PARAM="__API_GATEWAY_API_KEY_PARAM__"
REQUESTS="__REQUESTS__"
CONCURRENCY="__CONCURRENCY__"
MAX_TOKENS="__MAX_TOKENS__"
TEMPERATURE="__TEMPERATURE__"
TIMEOUT_SECONDS="__TIMEOUT_SECONDS__"
PROMPT_B64="__PROMPT_B64__"

API_GATEWAY_API_KEY_VALUE="$(aws ssm get-parameter \
  --region "$AWS_REGION" \
  --name "$API_GATEWAY_API_KEY_PARAM" \
  --with-decryption \
  --query Parameter.Value \
  --output text)"
export API_GATEWAY_API_KEY_VALUE API_GATEWAY_HOST_PORT REQUESTS CONCURRENCY
export MAX_TOKENS TEMPERATURE TIMEOUT_SECONDS PROMPT_B64

python3 - <<'PY'
import base64
import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.request

url = f"http://127.0.0.1:{os.environ['API_GATEWAY_HOST_PORT']}/v1/chat/completions"
api_key = os.environ["API_GATEWAY_API_KEY_VALUE"]
requests = int(os.environ["REQUESTS"])
concurrency = int(os.environ["CONCURRENCY"])
max_tokens = int(os.environ["MAX_TOKENS"])
temperature = float(os.environ["TEMPERATURE"])
timeout = float(os.environ["TIMEOUT_SECONDS"])
prompt = base64.b64decode(os.environ["PROMPT_B64"]).decode("utf-8")

payload = {
    "messages": [
        {"role": "system", "content": "You are concise and practical."},
        {"role": "user", "content": prompt},
    ],
    "max_tokens": max_tokens,
    "temperature": temperature,
}

def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]

def one(index):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "x-request-id": f"baseline-load-{index}",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_body = response.read()
            latency = time.perf_counter() - started
            data = json.loads(response_body)
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            return {
                "ok": True,
                "status": response.status,
                "latency_seconds": latency,
                "content_chars": len(content),
                "total_tokens": usage.get("total_tokens"),
            }
    except urllib.error.HTTPError as exc:
        latency = time.perf_counter() - started
        return {
            "ok": False,
            "status": exc.code,
            "latency_seconds": latency,
            "error": exc.read().decode("utf-8", errors="replace")[:300],
        }
    except Exception as exc:
        latency = time.perf_counter() - started
        return {
            "ok": False,
            "status": 0,
            "latency_seconds": latency,
            "error": repr(exc)[:300],
        }

started = time.perf_counter()
with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
    results = list(pool.map(one, range(requests)))
elapsed = time.perf_counter() - started

latencies = [item["latency_seconds"] for item in results]
status_counts = {}
for item in results:
    status_counts[str(item["status"])] = status_counts.get(str(item["status"]), 0) + 1

summary = {
    "requests": requests,
    "concurrency": concurrency,
    "succeeded": sum(1 for item in results if item["ok"]),
    "failed": sum(1 for item in results if not item["ok"]),
    "status_counts": status_counts,
    "elapsed_seconds": round(elapsed, 3),
    "requests_per_second": round(requests / elapsed, 3) if elapsed else None,
    "latency_seconds": {
        "min": round(min(latencies), 3) if latencies else None,
        "mean": round(statistics.fmean(latencies), 3) if latencies else None,
        "p50": round(percentile(latencies, 50), 3) if latencies else None,
        "p95": round(percentile(latencies, 95), 3) if latencies else None,
        "p99": round(percentile(latencies, 99), 3) if latencies else None,
        "max": round(max(latencies), 3) if latencies else None,
    },
}
print(json.dumps(summary, indent=2, sort_keys=True))

if summary["failed"]:
    raise SystemExit(1)
PY

unset API_GATEWAY_API_KEY_VALUE
REMOTE

sed -i \
  -e "s|__AWS_REGION__|${AWS_REGION}|g" \
  -e "s|__API_GATEWAY_HOST_PORT__|${API_GATEWAY_HOST_PORT}|g" \
  -e "s|__API_GATEWAY_API_KEY_PARAM__|${API_GATEWAY_API_KEY_PARAM}|g" \
  -e "s|__REQUESTS__|${REQUESTS}|g" \
  -e "s|__CONCURRENCY__|${CONCURRENCY}|g" \
  -e "s|__MAX_TOKENS__|${MAX_TOKENS}|g" \
  -e "s|__TEMPERATURE__|${TEMPERATURE}|g" \
  -e "s|__TIMEOUT_SECONDS__|${TIMEOUT_SECONDS}|g" \
  -e "s|__PROMPT_B64__|${prompt_b64}|g" \
  "$remote_script"

result="$(send_ssm_script "$remote_script" "Baseline load test NCP-GENL API gateway" 1200)"
rm -f "$remote_script"
printf '%s\n' "$result" | jq -r '.Stdout'
stderr="$(printf '%s\n' "$result" | jq -r '.Stderr')"
if [[ -n "$stderr" && "$stderr" != "null" ]]; then
  printf '%s\n' "$stderr" >&2
fi
status="$(printf '%s\n' "$result" | jq -r '.Status')"
if [[ "$status" != "Success" ]]; then
  exit 1
fi
