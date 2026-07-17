#!/usr/bin/env python3
"""Read-only AWS inventory scanner.

This script shells out to the AWS CLI so it can run in environments where
awscli is available but boto3 is not installed. It intentionally avoids APIs
that read secret values, parameter values, log events, S3 object contents, or
container image layers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = "finetuning-local"
DEFAULT_REGION = "us-east-1"


GLOBAL_COMMANDS = [
    ("iam", "account_summary", ["iam", "get-account-summary"], None),
    ("iam", "users", ["iam", "list-users"], "Users"),
    ("iam", "groups", ["iam", "list-groups"], "Groups"),
    ("iam", "roles", ["iam", "list-roles"], "Roles"),
    ("iam", "customer_managed_policies", ["iam", "list-policies", "--scope", "Local"], "Policies"),
    ("iam", "instance_profiles", ["iam", "list-instance-profiles"], "InstanceProfiles"),
    ("iam", "virtual_mfa_devices", ["iam", "list-virtual-mfa-devices"], "VirtualMFADevices"),
    ("iam", "saml_providers", ["iam", "list-saml-providers"], "SAMLProviderList"),
    ("iam", "oidc_providers", ["iam", "list-open-id-connect-providers"], "OpenIDConnectProviderList"),
    ("s3", "buckets", ["s3api", "list-buckets"], "Buckets"),
    ("route53", "hosted_zones", ["route53", "list-hosted-zones"], "HostedZones"),
    ("cloudfront", "distributions", ["cloudfront", "list-distributions"], "DistributionList.Items"),
    ("organizations", "organization", ["organizations", "describe-organization"], None),
    ("organizations", "accounts", ["organizations", "list-accounts"], "Accounts"),
]


REGIONAL_COMMANDS = [
    ("resourcegroupstaggingapi", "taggable_resources", ["resourcegroupstaggingapi", "get-resources"], "ResourceTagMappingList"),
    ("ec2", "instances", ["ec2", "describe-instances"], "Reservations[].Instances[]"),
    ("ec2", "volumes", ["ec2", "describe-volumes"], "Volumes"),
    ("ec2", "snapshots_owned", ["ec2", "describe-snapshots", "--owner-ids", "self"], "Snapshots"),
    ("ec2", "amis_owned", ["ec2", "describe-images", "--owners", "self"], "Images"),
    ("ec2", "vpcs", ["ec2", "describe-vpcs"], "Vpcs"),
    ("ec2", "subnets", ["ec2", "describe-subnets"], "Subnets"),
    ("ec2", "security_groups", ["ec2", "describe-security-groups"], "SecurityGroups"),
    ("ec2", "network_interfaces", ["ec2", "describe-network-interfaces"], "NetworkInterfaces"),
    ("ec2", "route_tables", ["ec2", "describe-route-tables"], "RouteTables"),
    ("ec2", "internet_gateways", ["ec2", "describe-internet-gateways"], "InternetGateways"),
    ("ec2", "nat_gateways", ["ec2", "describe-nat-gateways"], "NatGateways"),
    ("ec2", "elastic_ips", ["ec2", "describe-addresses"], "Addresses"),
    ("ec2", "key_pairs", ["ec2", "describe-key-pairs"], "KeyPairs"),
    ("ec2", "launch_templates", ["ec2", "describe-launch-templates"], "LaunchTemplates"),
    ("ec2", "vpc_endpoints", ["ec2", "describe-vpc-endpoints"], "VpcEndpoints"),
    ("ec2", "vpc_peering_connections", ["ec2", "describe-vpc-peering-connections"], "VpcPeeringConnections"),
    ("ec2", "transit_gateways", ["ec2", "describe-transit-gateways"], "TransitGateways"),
    ("ec2", "vpn_connections", ["ec2", "describe-vpn-connections"], "VpnConnections"),
    ("ec2", "customer_gateways", ["ec2", "describe-customer-gateways"], "CustomerGateways"),
    ("elbv2", "load_balancers", ["elbv2", "describe-load-balancers"], "LoadBalancers"),
    ("elb", "classic_load_balancers", ["elb", "describe-load-balancers"], "LoadBalancerDescriptions"),
    ("autoscaling", "groups", ["autoscaling", "describe-auto-scaling-groups"], "AutoScalingGroups"),
    ("eks", "clusters", ["eks", "list-clusters"], "clusters"),
    ("ecs", "clusters", ["ecs", "list-clusters"], "clusterArns"),
    ("ecs", "task_definitions", ["ecs", "list-task-definitions", "--status", "ACTIVE"], "taskDefinitionArns"),
    ("lambda", "functions", ["lambda", "list-functions"], "Functions"),
    ("rds", "db_instances", ["rds", "describe-db-instances"], "DBInstances"),
    ("rds", "db_clusters", ["rds", "describe-db-clusters"], "DBClusters"),
    ("dynamodb", "tables", ["dynamodb", "list-tables"], "TableNames"),
    ("ecr", "repositories", ["ecr", "describe-repositories"], "repositories"),
    ("cloudformation", "stacks", ["cloudformation", "describe-stacks"], "Stacks"),
    ("logs", "log_groups", ["logs", "describe-log-groups"], "logGroups"),
    ("sqs", "queues", ["sqs", "list-queues"], "QueueUrls"),
    ("sns", "topics", ["sns", "list-topics"], "Topics"),
    ("kms", "keys", ["kms", "list-keys"], "Keys"),
    ("kms", "aliases", ["kms", "list-aliases"], "Aliases"),
    ("secretsmanager", "secrets", ["secretsmanager", "list-secrets"], "SecretList"),
    ("ssm", "parameters", ["ssm", "describe-parameters"], "Parameters"),
    ("acm", "certificates", ["acm", "list-certificates"], "CertificateSummaryList"),
    ("apigateway", "rest_apis", ["apigateway", "get-rest-apis"], "items"),
    ("apigatewayv2", "apis", ["apigatewayv2", "get-apis"], "Items"),
    ("stepfunctions", "state_machines", ["stepfunctions", "list-state-machines"], "stateMachines"),
    ("events", "rules", ["events", "list-rules"], "Rules"),
    ("cloudtrail", "trails", ["cloudtrail", "describe-trails", "--include-shadow-trails"], "trailList"),
    ("configservice", "configuration_recorders", ["configservice", "describe-configuration-recorders"], "ConfigurationRecorders"),
    ("efs", "file_systems", ["efs", "describe-file-systems"], "FileSystems"),
    ("fsx", "file_systems", ["fsx", "describe-file-systems"], "FileSystems"),
    ("elasticache", "cache_clusters", ["elasticache", "describe-cache-clusters"], "CacheClusters"),
    ("redshift", "clusters", ["redshift", "describe-clusters"], "Clusters"),
    ("opensearch", "domains", ["opensearch", "list-domain-names"], "DomainNames"),
    ("codebuild", "projects", ["codebuild", "list-projects"], "projects"),
    ("codepipeline", "pipelines", ["codepipeline", "list-pipelines"], "pipelines"),
    ("glue", "databases", ["glue", "get-databases"], "DatabaseList"),
    ("glue", "jobs", ["glue", "get-jobs"], "Jobs"),
    ("glue", "crawlers", ["glue", "get-crawlers"], "Crawlers"),
    ("athena", "workgroups", ["athena", "list-work-groups"], "WorkGroups"),
    ("kinesis", "streams", ["kinesis", "list-streams"], "StreamNames"),
    ("firehose", "delivery_streams", ["firehose", "list-delivery-streams"], "DeliveryStreamNames"),
    ("kafka", "msk_clusters", ["kafka", "list-clusters-v2"], "ClusterInfoList"),
    ("elasticbeanstalk", "applications", ["elasticbeanstalk", "describe-applications"], "Applications"),
    ("elasticbeanstalk", "environments", ["elasticbeanstalk", "describe-environments"], "Environments"),
    ("apprunner", "services", ["apprunner", "list-services"], "ServiceSummaryList"),
    ("lightsail", "instances", ["lightsail", "get-instances"], "instances"),
    ("lightsail", "static_ips", ["lightsail", "get-static-ips"], "staticIps"),
    ("lightsail", "disks", ["lightsail", "get-disks"], "disks"),
    ("lightsail", "load_balancers", ["lightsail", "get-load-balancers"], "loadBalancers"),
    ("lightsail", "container_services", ["lightsail", "get-container-services"], "containerServices"),
    ("lightsail", "databases", ["lightsail", "get-relational-databases"], "relationalDatabases"),
    ("lightsail", "buckets", ["lightsail", "get-buckets"], "buckets"),
    ("lightsail", "distributions", ["lightsail", "get-distributions"], "distributions"),
    ("wafv2", "web_acls_regional", ["wafv2", "list-web-acls", "--scope", "REGIONAL"], "WebACLs"),
    ("sagemaker", "endpoints", ["sagemaker", "list-endpoints"], "Endpoints"),
    ("sagemaker", "endpoint_configs", ["sagemaker", "list-endpoint-configs"], "EndpointConfigs"),
    ("sagemaker", "models", ["sagemaker", "list-models"], "Models"),
    ("sagemaker", "notebook_instances", ["sagemaker", "list-notebook-instances"], "NotebookInstances"),
    ("sagemaker", "training_jobs", ["sagemaker", "list-training-jobs"], "TrainingJobSummaries"),
    ("sagemaker", "processing_jobs", ["sagemaker", "list-processing-jobs"], "ProcessingJobSummaries"),
    ("sagemaker", "transform_jobs", ["sagemaker", "list-transform-jobs"], "TransformJobSummaries"),
    ("bedrock", "custom_models", ["bedrock", "list-custom-models"], "modelSummaries"),
    ("bedrock", "provisioned_model_throughputs", ["bedrock", "list-provisioned-model-throughputs"], "provisionedModelSummaries"),
    ("bedrock", "model_customization_jobs", ["bedrock", "list-model-customization-jobs"], "modelCustomizationJobSummaries"),
    ("bedrock-agent", "agents", ["bedrock-agent", "list-agents"], "agentSummaries"),
    ("bedrock-agent", "knowledge_bases", ["bedrock-agent", "list-knowledge-bases"], "knowledgeBaseSummaries"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_aws(
    profile: str,
    args: list[str],
    region: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    cmd = ["aws", "--profile", profile]
    if region:
        cmd.extend(["--region", region])
    cmd.extend(args)
    cmd.extend(["--output", "json", "--no-cli-pager"])

    env = os.environ.copy()
    env["AWS_PAGER"] = ""
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": redact_command(cmd),
            "region": region,
            "duration_seconds": round(time.time() - started, 3),
            "error": f"Timed out after {timeout}s",
            "stdout": (exc.stdout or "")[:2000],
            "stderr": (exc.stderr or "")[:2000],
        }

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    result: dict[str, Any] = {
        "ok": proc.returncode == 0,
        "command": redact_command(cmd),
        "region": region,
        "duration_seconds": round(time.time() - started, 3),
    }
    if proc.returncode == 0:
        if stdout:
            try:
                result["data"] = json.loads(stdout)
            except json.JSONDecodeError:
                result["data"] = stdout
        else:
            result["data"] = None
    else:
        result["error"] = normalize_error(stderr or stdout)
    return result


def redact_command(cmd: list[str]) -> list[str]:
    # The current command set does not include secrets, but keep this generic.
    redacted: list[str] = []
    sensitive_next = False
    for part in cmd:
        if sensitive_next:
            redacted.append("***")
            sensitive_next = False
            continue
        redacted.append(part)
        if part.lower() in {"--secret-id", "--parameter", "--parameters"}:
            sensitive_next = True
    return redacted


def normalize_error(message: str) -> str:
    return " ".join(message.split())[:2000]


def path_values(data: Any, path: str) -> list[Any]:
    values = [data]
    for token in path.split("."):
        expand = token.endswith("[]")
        key = token[:-2] if expand else token
        next_values: list[Any] = []
        for value in values:
            child: Any = value
            if key:
                if isinstance(value, dict):
                    child = value.get(key)
                else:
                    child = None
            if expand:
                if isinstance(child, list):
                    next_values.extend(child)
                elif child is not None:
                    next_values.append(child)
            elif child is not None:
                next_values.append(child)
        values = next_values
    return values


def count_path(data: Any, path: str | None) -> int | None:
    if path is None or data is None:
        return None
    values = path_values(data, path)
    if len(values) == 1 and isinstance(values[0], list):
        return len(values[0])
    return len(values)


def put_nested(root: dict[str, Any], service: str, name: str, result: dict[str, Any], count_key: str | None) -> None:
    service_doc = root.setdefault(service, {})
    entry = {
        "ok": result["ok"],
        "duration_seconds": result["duration_seconds"],
        "command": result["command"],
    }
    if result["ok"]:
        data = result.get("data")
        entry["count"] = count_path(data, count_key)
        entry["data"] = data
    else:
        entry["count"] = None
        entry["error"] = result.get("error", "Unknown error")
    service_doc[name] = entry


def get_enabled_regions(profile: str) -> tuple[list[str], dict[str, Any]]:
    result = run_aws(
        profile,
        ["ec2", "describe-regions", "--all-regions"],
        region=DEFAULT_REGION,
        timeout=60,
    )
    if not result["ok"]:
        return [], result
    regions = []
    for region in result["data"].get("Regions", []):
        status = region.get("OptInStatus")
        if status in ("opt-in-not-required", "opted-in"):
            regions.append(region["RegionName"])
    return sorted(regions), result


def enrich_s3_buckets(profile: str, global_doc: dict[str, Any]) -> None:
    buckets_entry = global_doc.get("s3", {}).get("buckets")
    if not buckets_entry or not buckets_entry.get("ok"):
        return
    buckets = buckets_entry.get("data", {}).get("Buckets", [])
    for bucket in buckets:
        name = bucket.get("Name")
        if not name:
            continue
        location = run_aws(profile, ["s3api", "get-bucket-location", "--bucket", name], region=DEFAULT_REGION, timeout=30)
        if location["ok"]:
            constraint = location.get("data", {}).get("LocationConstraint")
            bucket["Region"] = constraint or "us-east-1"
        else:
            bucket["RegionError"] = location.get("error")


def enrich_ecr_repositories(profile: str, region: str, region_doc: dict[str, Any]) -> None:
    entry = region_doc.get("ecr", {}).get("repositories")
    if not entry or not entry.get("ok"):
        return
    repos = entry.get("data", {}).get("repositories", [])
    image_counts = {}
    for repo in repos:
        repo_name = repo.get("repositoryName")
        if not repo_name:
            continue
        result = run_aws(profile, ["ecr", "list-images", "--repository-name", repo_name], region=region, timeout=60)
        if result["ok"]:
            image_counts[repo_name] = count_path(result.get("data"), "imageIds")
        else:
            image_counts[repo_name] = {"error": result.get("error")}
    entry["image_counts"] = image_counts


def enrich_ecs_clusters(profile: str, region: str, region_doc: dict[str, Any]) -> None:
    entry = region_doc.get("ecs", {}).get("clusters")
    if not entry or not entry.get("ok"):
        return
    cluster_arns = entry.get("data", {}).get("clusterArns", [])
    services_by_cluster = {}
    for cluster_arn in cluster_arns:
        result = run_aws(profile, ["ecs", "list-services", "--cluster", cluster_arn], region=region, timeout=60)
        if result["ok"]:
            services_by_cluster[cluster_arn] = result.get("data", {}).get("serviceArns", [])
        else:
            services_by_cluster[cluster_arn] = {"error": result.get("error")}
    entry["services_by_cluster"] = services_by_cluster


def scan_global(profile: str) -> dict[str, Any]:
    doc: dict[str, Any] = {}
    for service, name, command, count_key in GLOBAL_COMMANDS:
        result = run_aws(profile, command, region=DEFAULT_REGION, timeout=60)
        put_nested(doc, service, name, result, count_key)
    enrich_s3_buckets(profile, doc)
    return doc


def scan_region(profile: str, region: str) -> dict[str, Any]:
    started = time.time()
    print(f"[{utc_now()}] scanning region {region}", flush=True)
    doc: dict[str, Any] = {"_meta": {"started_at": utc_now()}}
    for service, name, command, count_key in REGIONAL_COMMANDS:
        result = run_aws(profile, command, region=region, timeout=90)
        put_nested(doc, service, name, result, count_key)

    if region == "us-east-1":
        result = run_aws(profile, ["wafv2", "list-web-acls", "--scope", "CLOUDFRONT"], region=region, timeout=60)
        put_nested(doc, "wafv2", "web_acls_cloudfront", result, "WebACLs")

    enrich_ecr_repositories(profile, region, doc)
    enrich_ecs_clusters(profile, region, doc)
    doc["_meta"]["finished_at"] = utc_now()
    doc["_meta"]["duration_seconds"] = round(time.time() - started, 3)
    print(f"[{utc_now()}] finished region {region}", flush=True)
    return doc


def collect_counts(inventory: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, Any] = {"global": {}, "regional": {}, "totals_by_service": {}}

    for service, service_doc in inventory.get("global", {}).items():
        for name, entry in service_doc.items():
            if isinstance(entry, dict) and entry.get("ok") and entry.get("count") is not None:
                counts["global"][f"{service}.{name}"] = entry["count"]

    for region, region_doc in inventory.get("regional", {}).items():
        region_counts = {}
        for service, service_doc in region_doc.items():
            if service == "_meta" or not isinstance(service_doc, dict):
                continue
            for name, entry in service_doc.items():
                if not isinstance(entry, dict):
                    continue
                if entry.get("ok") and entry.get("count") is not None:
                    key = f"{service}.{name}"
                    count = entry["count"]
                    region_counts[key] = count
                    counts["totals_by_service"][key] = counts["totals_by_service"].get(key, 0) + count
        counts["regional"][region] = region_counts
    return counts


def collect_errors(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for scope, scope_doc in (("global", inventory.get("global", {})),):
        for service, service_doc in scope_doc.items():
            if not isinstance(service_doc, dict):
                continue
            for name, entry in service_doc.items():
                if isinstance(entry, dict) and not entry.get("ok", True):
                    errors.append({"scope": scope, "service": service, "name": name, "error": entry.get("error")})

    for region, region_doc in inventory.get("regional", {}).items():
        for service, service_doc in region_doc.items():
            if service == "_meta" or not isinstance(service_doc, dict):
                continue
            for name, entry in service_doc.items():
                if isinstance(entry, dict) and not entry.get("ok", True):
                    errors.append({"scope": region, "service": service, "name": name, "error": entry.get("error")})
    return errors


def nonzero_counts(counts: dict[str, Any]) -> list[tuple[str, int]]:
    items = [
        (key, value)
        for key, value in counts.get("totals_by_service", {}).items()
        if isinstance(value, int) and value > 0
    ]
    return sorted(items, key=lambda item: (-item[1], item[0]))


def write_summary(out_dir: Path, inventory: dict[str, Any], counts: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    meta = inventory["metadata"]
    lines = [
        "# AWS Inventory Summary",
        "",
        f"- Profile: `{meta['profile']}`",
        f"- Account: `{meta.get('account_id', 'unknown')}`",
        f"- Principal: `{meta.get('principal_arn', 'unknown')}`",
        f"- Started: `{meta['started_at']}`",
        f"- Finished: `{meta['finished_at']}`",
        f"- Regions scanned: {len(meta['regions'])}",
        f"- API/listing errors: {len(errors)}",
        "",
        "## Global Counts",
        "",
    ]

    global_counts = counts.get("global", {})
    if global_counts:
        for key in sorted(global_counts):
            lines.append(f"- `{key}`: {global_counts[key]}")
    else:
        lines.append("- No global count data collected.")

    lines.extend(["", "## Nonzero Regional Totals", ""])
    nz = nonzero_counts(counts)
    if nz:
        for key, value in nz:
            lines.append(f"- `{key}`: {value}")
    else:
        lines.append("- No nonzero regional resources found by the configured service scans.")

    lines.extend(["", "## Per-Region Nonzero Counts", ""])
    any_region = False
    for region in sorted(counts.get("regional", {})):
        entries = {k: v for k, v in counts["regional"][region].items() if isinstance(v, int) and v > 0}
        if not entries:
            continue
        any_region = True
        lines.append(f"### {region}")
        for key in sorted(entries):
            lines.append(f"- `{key}`: {entries[key]}")
        lines.append("")
    if not any_region:
        lines.append("- No regions had nonzero resource counts.")

    lines.extend(["", "## Errors", ""])
    if errors:
        for error in errors[:200]:
            lines.append(f"- `{error['scope']}` `{error['service']}.{error['name']}`: {error['error']}")
        if len(errors) > 200:
            lines.append(f"- ... {len(errors) - 200} more errors are in `errors.json`.")
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This is a read-only inventory scan.",
            "- The scanner does not read secret values, SSM parameter values, S3 object contents, CloudWatch log events, or ECR image layers.",
            "- `resourcegroupstaggingapi.get-resources` only covers resources visible to that API; service-specific list calls provide additional coverage.",
            "- Some AWS services are global, some are regional, and not every AWS service has a complete generic list API.",
        ]
    )
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only AWS inventory scan using AWS CLI.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", default="aws-inventory")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--regions", nargs="*", help="Optional explicit region list. Defaults to enabled regions.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started_at = utc_now()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    identity = run_aws(args.profile, ["sts", "get-caller-identity"], region=DEFAULT_REGION, timeout=30)
    if not identity["ok"]:
        print(f"Unable to use AWS profile {args.profile}: {identity.get('error')}", file=sys.stderr)
        return 2

    if args.regions:
        regions = sorted(args.regions)
        region_source = {"ok": True, "data": {"source": "cli"}}
    else:
        regions, region_source = get_enabled_regions(args.profile)
        if not regions:
            print(f"Unable to determine enabled regions: {region_source.get('error')}", file=sys.stderr)
            return 2

    print(f"[{utc_now()}] scanning account {identity['data'].get('Account')} with profile {args.profile}", flush=True)
    print(f"[{utc_now()}] regions: {', '.join(regions)}", flush=True)

    inventory: dict[str, Any] = {
        "metadata": {
            "profile": args.profile,
            "started_at": started_at,
            "account_id": identity["data"].get("Account"),
            "principal_arn": identity["data"].get("Arn"),
            "regions": regions,
        },
        "identity": identity,
        "region_discovery": region_source,
        "global": {},
        "regional": {},
    }

    print(f"[{utc_now()}] scanning global services", flush=True)
    inventory["global"] = scan_global(args.profile)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(scan_region, args.profile, region): region for region in regions}
        for future in as_completed(futures):
            region = futures[future]
            try:
                inventory["regional"][region] = future.result()
            except Exception as exc:  # noqa: BLE001
                inventory["regional"][region] = {
                    "_meta": {
                        "started_at": started_at,
                        "finished_at": utc_now(),
                        "error": repr(exc),
                    }
                }

    inventory["metadata"]["finished_at"] = utc_now()
    counts = collect_counts(inventory)
    errors = collect_errors(inventory)

    (out_dir / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True, default=str), encoding="utf-8")
    (out_dir / "counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir / "errors.json").write_text(json.dumps(errors, indent=2, sort_keys=True), encoding="utf-8")
    write_summary(out_dir, inventory, counts, errors)

    print(f"[{utc_now()}] wrote {out_dir / 'inventory.json'}", flush=True)
    print(f"[{utc_now()}] wrote {out_dir / 'summary.md'}", flush=True)
    print(f"[{utc_now()}] errors: {len(errors)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
