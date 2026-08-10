#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import io
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


COLLECTIONS = (
    "service_users",
    "today_plans",
    "inquiries",
    "medication_safety_events",
    "caregiver_event_receipts",
    "caregiver_notification_outbox",
    "caregiver_notification_subscriptions",
    "device_memberships",
    "device_pairing_codes",
)
TARGET_SCHEMA_REVISION = "2.6-station-pairing-notification-worker"
WORKER_TRIGGER_NAME = "caregiver-notification-worker-timer"
WORKER_TRIGGER_CRON = "0 */2 * * * * *"
DEFAULT_NOTIFICATION_PAGE = "pages/records/index"


@dataclass(frozen=True)
class FunctionSpec:
    name: str
    handler: str
    timeout: int
    runtime: str
    required_files: tuple[str, ...]
    require_existing: bool = False


API_SPEC = FunctionSpec(
    name="api",
    handler="index.main",
    timeout=15,
    runtime="Nodejs16.13",
    required_files=(
        "index.js",
        "medicationSafetyEvents.js",
        "memberships.js",
        "package.json",
        "config.json",
    ),
    require_existing=True,
)
WORKER_SPEC = FunctionSpec(
    name="caregiverNotificationWorker",
    handler="index.main",
    timeout=30,
    runtime="Nodejs16.13",
    required_files=(
        "index.js",
        "worker.js",
        "invocation.js",
        "subscribeMessageSender.js",
        "package.json",
        "config.json",
    ),
)


class DeployError(RuntimeError):
    pass


def parse_json_output(output: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    parsed: dict[str, Any] | None = None
    parsed_size = -1
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and end > parsed_size:
            parsed = value
            parsed_size = end
    if parsed is None:
        raise DeployError("CloudBase CLI 未返回可解析 JSON。")
    return parsed


class CloudBaseCli:
    def __init__(self, path: Path, env_id: str) -> None:
        self.env_id = env_id
        self.command = [str(path)] if os.access(path, os.X_OK) else ["node", str(path)]

    def run(self, arguments: list[str], *, echo: bool = True) -> dict[str, Any]:
        process = subprocess.run(
            [*self.command, *arguments],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if process.stdout and echo:
            print(process.stdout.rstrip())
        if process.returncode != 0:
            raise DeployError(f"CloudBase CLI 执行失败，退出码 {process.returncode}。")
        return parse_json_output(process.stdout)

    def environment_detail(self) -> dict[str, Any]:
        return self.run(["-e", self.env_id, "env", "detail", "--json"], echo=False)["data"]

    def api(
        self,
        region: str,
        service: str,
        action: str,
        version: str,
        body: dict[str, Any],
        *,
        echo: bool = True,
    ) -> dict[str, Any]:
        return self.run(
            [
                "-e",
                self.env_id,
                "-r",
                region,
                "api",
                service,
                action,
                "--api-version",
                version,
                "--body",
                json.dumps(body, separators=(",", ":")),
                "--json",
            ],
            echo=echo,
        )["data"]


def source_zip(function_dir: Path, required_files: tuple[str, ...]) -> bytes:
    missing = [name for name in required_files if not (function_dir / name).is_file()]
    if missing:
        raise DeployError(f"云函数目录缺少文件：{', '.join(missing)}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in required_files:
            archive.write(function_dir / name, name)
    return buffer.getvalue()


def ensure_collections(cli: CloudBaseCli, region: str, database_tag: str) -> None:
    response = cli.api(
        region,
        "flexdb",
        "ListTables",
        "2018-11-27",
        {"Tag": database_tag, "MgoLimit": 100, "MgoOffset": 0},
        echo=False,
    )
    existing = {str(row.get("TableName")) for row in response.get("Tables") or []}
    for collection in COLLECTIONS:
        if collection in existing:
            print(f"[cloudbase] 集合已存在：{collection}")
            continue
        cli.api(
            region,
            "flexdb",
            "CreateTable",
            "2018-11-27",
            {"Tag": database_tag, "TableName": collection},
        )
        print(f"[cloudbase] 已创建集合：{collection}")


def wait_for_function_active(
    cli: CloudBaseCli,
    region: str,
    function_name: str,
) -> None:
    for _ in range(45):
        detail = cli.api(
            region,
            "scf",
            "GetFunction",
            "2018-04-16",
            {"FunctionName": function_name, "Namespace": cli.env_id},
            echo=False,
        )
        status = str(detail.get("Status") or "")
        available = detail.get("AvailableStatus")
        if status == "Active" and available in {None, "Available"}:
            return
        if status in {"CreateFailed", "UpdateFailed"}:
            raise DeployError(f"云函数 {function_name} 进入失败状态：{status}")
        time.sleep(2)
    raise DeployError(f"等待 {function_name} 云函数恢复 Active 状态超时。")


def list_function_names(cli: CloudBaseCli, region: str) -> set[str]:
    response = cli.api(
        region,
        "scf",
        "ListFunctions",
        "2018-04-16",
        {"Namespace": cli.env_id, "Offset": 0, "Limit": 100},
        echo=False,
    )
    return {
        str(row.get("FunctionName") or "")
        for row in response.get("Functions") or []
        if row.get("FunctionName")
    }


def function_detail(cli: CloudBaseCli, region: str, function_name: str) -> dict[str, Any]:
    return cli.api(
        region,
        "scf",
        "GetFunction",
        "2018-04-16",
        {"FunctionName": function_name, "Namespace": cli.env_id},
        echo=False,
    )


def validate_function_identity(
    cli: CloudBaseCli,
    region: str,
    spec: FunctionSpec,
) -> None:
    detail = function_detail(cli, region, spec.name)
    actual_type = str(detail.get("Type") or "").strip().lower()
    actual_runtime = str(detail.get("Runtime") or "").strip()
    actual_handler = str(detail.get("Handler") or "").strip()
    if (
        actual_type != "event"
        or actual_runtime != spec.runtime
        or actual_handler != spec.handler
    ):
        raise DeployError(
            f"既有云函数 {spec.name} 的身份、类型或运行时与受控配置不一致。"
        )


def list_worker_triggers(cli: CloudBaseCli, region: str) -> list[dict[str, Any]]:
    response = cli.api(
        region,
        "scf",
        "ListTriggers",
        "2018-04-16",
        {
            "FunctionName": WORKER_SPEC.name,
            "Namespace": cli.env_id,
            "Offset": 0,
            "Limit": 100,
        },
        echo=False,
    )
    return [dict(row) for row in response.get("Triggers") or []]


def validate_worker_triggers(cli: CloudBaseCli, region: str) -> None:
    rows = list_worker_triggers(cli, region)
    unexpected = [
        row for row in rows
        if str(row.get("TriggerName") or "") != WORKER_TRIGGER_NAME
    ]
    if unexpected:
        raise DeployError("通知 worker 存在未受管触发器，拒绝自动修改或部署。")
    if len(rows) > 1:
        raise DeployError("通知 worker 定时触发器名称重复，拒绝自动修改。")
    if rows and (
        str(rows[0].get("Type") or "").lower() != "timer"
        or trigger_cron(rows[0].get("TriggerDesc")) != trigger_cron(WORKER_TRIGGER_CRON)
    ):
        raise DeployError("通知 worker 触发器配置与受控配置不一致。")


def preflight_deployment(cli: CloudBaseCli, region: str) -> set[str]:
    names = list_function_names(cli, region)
    if API_SPEC.name not in names:
        raise DeployError("云环境缺少既有 api 函数，拒绝在错误环境创建其他资源。")
    validate_function_identity(cli, region, API_SPEC)
    if WORKER_SPEC.name in names:
        validate_function_identity(cli, region, WORKER_SPEC)
        validate_worker_triggers(cli, region)
    return names


def environment_map(detail: dict[str, Any]) -> dict[str, str]:
    environment = detail.get("Environment") or {}
    rows = (environment.get("Variables") or []) if isinstance(environment, dict) else []
    return {
        str(row.get("Key") or ""): str(row.get("Value") or "")
        for row in rows
        if isinstance(row, dict) and row.get("Key")
    }


def environment_payload(values: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    return {
        "Variables": [
            {"Key": key, "Value": value}
            for key, value in sorted(values.items())
        ]
    }


def deploy_function(
    cli: CloudBaseCli,
    region: str,
    function_dir: Path,
    spec: FunctionSpec,
    *,
    environment: dict[str, str] | None = None,
) -> None:
    archive = source_zip(function_dir, spec.required_files)
    encoded_archive = base64.b64encode(archive).decode("ascii")
    print(f"[cloudbase] {spec.name} 函数源码压缩包：{len(archive)} bytes")
    exists = spec.name in list_function_names(cli, region)
    if not exists and spec.require_existing:
        raise DeployError(f"云环境缺少既有 {spec.name} 函数，拒绝自动重建外部路由。")

    if not exists:
        body: dict[str, Any] = {
            "FunctionName": spec.name,
            "Namespace": cli.env_id,
            "Description": "Zykh caregiver notification worker",
            "Handler": spec.handler,
            "Runtime": spec.runtime,
            "Type": "Event",
            "Timeout": spec.timeout,
            "MemorySize": 128,
            "InstallDependency": "TRUE",
            "CodeSource": "ZipFile",
            "Code": {"ZipFile": encoded_archive},
        }
        if environment:
            body["Environment"] = environment_payload(environment)
        cli.api(region, "scf", "CreateFunction", "2018-04-16", body)
        wait_for_function_active(cli, region, spec.name)
        return

    configuration: dict[str, Any] = {
        "FunctionName": spec.name,
        "Namespace": cli.env_id,
        "Timeout": spec.timeout,
        "InstallDependency": "TRUE",
    }
    if environment is not None:
        detail = cli.api(
            region,
            "scf",
            "GetFunction",
            "2018-04-16",
            {"FunctionName": spec.name, "Namespace": cli.env_id},
            echo=False,
        )
        merged = environment_map(detail)
        merged.update({key: value for key, value in environment.items() if value})
        configuration["Environment"] = environment_payload(merged)
    cli.api(
        region,
        "scf",
        "UpdateFunctionConfiguration",
        "2018-04-16",
        configuration,
    )
    wait_for_function_active(cli, region, spec.name)
    cli.api(
        region,
        "scf",
        "UpdateFunctionCode",
        "2018-04-16",
        {
            "FunctionName": spec.name,
            "Namespace": cli.env_id,
            "Handler": spec.handler,
            "InstallDependency": "TRUE",
            "CodeSource": "ZipFile",
            "Code": {"ZipFile": encoded_archive},
        },
    )
    wait_for_function_active(cli, region, spec.name)


def trigger_cron(value: object) -> str:
    raw = str(value or "").strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(parsed, dict):
            raw = str(parsed.get("cron") or parsed.get("Cron") or "").strip()
    return " ".join(raw.split())


def trigger_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value or "").strip().upper() in {"1", "OPEN", "TRUE", "ON"}


def ensure_worker_trigger(
    cli: CloudBaseCli,
    region: str,
    *,
    enable: bool,
) -> None:
    rows = list_worker_triggers(cli, region)
    unexpected = [
        row for row in rows
        if str(row.get("TriggerName") or "") != WORKER_TRIGGER_NAME
    ]
    if unexpected:
        raise DeployError("通知 worker 存在未受管触发器，拒绝自动修改。")
    matches = [
        row
        for row in rows
        if str(row.get("TriggerName") or "") == WORKER_TRIGGER_NAME
    ]
    desired = "OPEN" if enable else "CLOSE"
    if not matches:
        cli.api(
            region,
            "scf",
            "CreateTrigger",
            "2018-04-16",
            {
                "FunctionName": WORKER_SPEC.name,
                "Namespace": cli.env_id,
                "TriggerName": WORKER_TRIGGER_NAME,
                "Type": "timer",
                "TriggerDesc": WORKER_TRIGGER_CRON,
                "Qualifier": "$LATEST",
                "Enable": desired,
                "Description": "Caregiver notification worker timer",
            },
        )
        return
    if len(matches) != 1:
        raise DeployError("通知 worker 定时触发器名称重复，拒绝自动修改。")
    current = matches[0]
    if (
        str(current.get("Type") or "").lower() != "timer"
        or trigger_cron(current.get("TriggerDesc")) != trigger_cron(WORKER_TRIGGER_CRON)
    ):
        raise DeployError("通知 worker 触发器配置与受控配置不一致。")
    if trigger_enabled(current.get("Enable")) == enable:
        return
    cli.api(
        region,
        "scf",
        "UpdateTriggerStatus",
        "2018-04-16",
        {
            "FunctionName": WORKER_SPEC.name,
            "Namespace": cli.env_id,
            "TriggerName": WORKER_TRIGGER_NAME,
            "Type": "timer",
            "Qualifier": "$LATEST",
            "Enable": desired,
        },
    )


def validate_worker_enablement(
    *,
    template_id: str,
    page: str,
    openapi: bool,
    subscriptions: bool,
) -> None:
    if not template_id.strip():
        raise DeployError("启用通知 worker 前必须提供已审核的微信订阅模板 ID。")
    normalized_page = page.strip()
    if (
        not normalized_page.startswith("pages/")
        or "?" in normalized_page
        or "#" in normalized_page
    ):
        raise DeployError("启用通知 worker 前必须提供不含查询参数的真实小程序页面路径。")
    if not openapi:
        raise DeployError("启用通知 worker 前必须确认 subscribeMessage.send 权限。")
    if not subscriptions:
        raise DeployError("启用通知 worker 前必须确认订阅授权已安全落库。")


def wait_for_schema(endpoint: str) -> None:
    request_body = json.dumps({"action": "PING", "data": {}}).encode("utf-8")
    for _ in range(30):
        try:
            request = urllib.request.Request(
                endpoint,
                data=request_body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.load(response)
            capabilities = result.get("capabilities") or {}
            if (
                int(result.get("schemaVersion") or 0) == 2
                and result.get("schemaRevision") == TARGET_SCHEMA_REVISION
                and capabilities.get("devicePairing") == "v1"
                and capabilities.get("devicePairingIssue") == "v1"
                and capabilities.get("caregiverNotificationOutbox") == "v1"
                and capabilities.get("caregiverNotificationWorker") == "v1"
            ):
                print(
                    f"[cloudbase] schemaRevision={TARGET_SCHEMA_REVISION}，"
                    "secure pairing / notification worker 能力已生效。"
                )
                return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(3)
    raise DeployError(
        f"云函数更新后 90 秒内未返回 schemaRevision={TARGET_SCHEMA_REVISION} "
        "及 secure pairing / notification worker 能力。"
    )


def probe_notification_worker(cli: CloudBaseCli, region: str) -> None:
    response = cli.api(
        region,
        "scf",
        "InvokeFunction",
        "2018-04-16",
        {
            "FunctionName": WORKER_SPEC.name,
            "Namespace": cli.env_id,
            "Qualifier": "$LATEST",
            "Event": json.dumps({"action": "PING"}, separators=(",", ":")),
            "LogType": "None",
        },
        echo=False,
    )
    result = response.get("Result") or {}
    try:
        invoke_result = int(result.get("InvokeResult"))
    except (TypeError, ValueError):
        invoke_result = -1
    returned = result.get("RetMsg")
    if isinstance(returned, str):
        try:
            returned = json.loads(returned)
        except json.JSONDecodeError:
            returned = None
    valid = (
        invoke_result == 0
        and not str(result.get("ErrMsg") or "").strip()
        and isinstance(returned, dict)
        and returned.get("ok") is True
        and returned.get("capability") == "caregiverNotificationWorker"
        and returned.get("version") == "v1"
    )
    if not valid:
        raise DeployError("通知 worker 运行探针失败，定时器保持关闭。")


def deploy_application(
    *,
    cli: CloudBaseCli,
    region: str,
    api_function_dir: Path,
    worker_function_dir: Path,
    endpoint: str,
    worker_environment: dict[str, str],
    enable_worker: bool,
) -> None:
    names = preflight_deployment(cli, region)
    if WORKER_SPEC.name in names:
        ensure_worker_trigger(cli, region, enable=False)
    deploy_function(
        cli,
        region,
        worker_function_dir,
        WORKER_SPEC,
        environment=worker_environment,
    )
    ensure_worker_trigger(cli, region, enable=False)
    deploy_function(cli, region, api_function_dir, API_SPEC)
    wait_for_schema(endpoint)
    probe_notification_worker(cli, region)
    if enable_worker:
        ensure_worker_trigger(cli, region, enable=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--env-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--function-dir", required=True, type=Path)
    parser.add_argument("--worker-function-dir", required=True, type=Path)
    parser.add_argument("--notification-template-id", default="")
    parser.add_argument("--notification-page", default="")
    parser.add_argument("--enable-notification-worker", action="store_true")
    parser.add_argument("--confirm-worker-openapi-permission", action="store_true")
    parser.add_argument("--confirm-notification-subscriptions", action="store_true")
    args = parser.parse_args()

    if args.enable_notification_worker:
        validate_worker_enablement(
            template_id=args.notification_template_id,
            page=args.notification_page,
            openapi=args.confirm_worker_openapi_permission,
            subscriptions=args.confirm_notification_subscriptions,
        )

    cli = CloudBaseCli(args.cli, args.env_id)
    detail = cli.environment_detail()
    region = str(detail.get("region") or "ap-shanghai")
    databases = detail.get("resources", {}).get("databases") or []
    if not databases or not databases[0].get("InstanceId"):
        raise DeployError("云环境没有可用文档数据库实例。")
    database_tag = str(databases[0]["InstanceId"])

    print(f"[cloudbase] 环境：{args.env_id}，区域：{region}")
    preflight_deployment(cli, region)
    ensure_collections(cli, region, database_tag)
    notification_page = args.notification_page.strip() or DEFAULT_NOTIFICATION_PAGE
    worker_environment = {
        "CAREGIVER_NOTIFICATION_PAGE": notification_page,
        "CAREGIVER_NOTIFICATION_TRIGGER_NAME": WORKER_TRIGGER_NAME,
    }
    if args.notification_template_id.strip():
        worker_environment["CAREGIVER_NOTIFICATION_TEMPLATE_IDS"] = json.dumps(
            {"MEDICATION_SAFETY_ALERT": args.notification_template_id.strip()},
            separators=(",", ":"),
        )
    deploy_application(
        cli=cli,
        region=region,
        api_function_dir=args.function_dir,
        worker_function_dir=args.worker_function_dir,
        endpoint=args.endpoint,
        worker_environment=worker_environment,
        enable_worker=args.enable_notification_worker,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeployError, KeyError) as error:
        print(f"[cloudbase] 部署失败：{error}", file=sys.stderr)
        raise SystemExit(1)
