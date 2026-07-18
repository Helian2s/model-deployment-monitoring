# NeMo Helpdesk Rails

This project uses NeMo Guardrails for the live helpdesk triage path:

```text
API gateway -> NeMo Guardrails -> API gateway internal endpoint -> Triton/vLLM
```

## Configuration Locations

- Source-controlled NeMo config: `services/nemo-guardrails/configs/helpdesk-triage.json`
- EC2 deployment loader: `tools/ec2_single_node_up.sh`
- EC2 validation checks: `tools/ec2_single_node_validate.sh`
- Gateway deterministic policy: `services/api-gateway/app/helpdesk.py`
- Gateway Guardrails client: `services/api-gateway/app/guardrails.py`

The EC2 deployment script reads the source-controlled JSON, validates it with `jq`, base64-encodes it, writes it to `/opt/ncp-genl/guardrails/helpdesk-triage.json`, and registers it with the NeMo Guardrails microservice.

## Active NeMo Rail

The first active NeMo rail is intentionally narrow:

```json
"rails": {
  "input": {
    "parallel": false,
    "flows": ["self check input"]
  }
}
```

The configured prompt task is:

```json
{
  "task": "self_check_input"
}
```

It blocks only clear cases of:

- prompt injection or attempts to reveal/override system or developer instructions;
- secrets or credentials in ticket text;
- requests for the assistant to grant access, bypass approval, disable controls, or impersonate an administrator;
- requests unrelated to internal IT support triage.

It explicitly allows normal helpdesk tickets that mention MFA, payroll, access requests, phishing, malware, suspicious login, names, emails, departments, urgent business impact, or deadlines.

## Gateway-Enforced Controls

These controls remain deterministic in the API gateway:

- prompt-injection block;
- possible-secret block;
- PII flagging;
- security-sensitive flagging;
- strict Pydantic output contract;
- deterministic output repair for narrow schema-shape errors;
- priority policy correction;
- human-handoff policy through `requires_human`.

The reason is operational: deterministic controls are easier to regression test and safer for high-impact routing decisions. NeMo input self-check adds semantic coverage, but it still needs false-positive calibration on a labeled helpdesk safety set.

## Deployment Status

The repository and EC2 deployment template now include the rail. Because the EC2 instance is stopped, the live NeMo SQLite config on the instance is not updated yet. It will be updated the next time the instance is started and the EC2 deployment/update path registers `helpdesk-triage`.
