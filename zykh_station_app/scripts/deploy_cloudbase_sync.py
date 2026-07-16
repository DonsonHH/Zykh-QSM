#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
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


COLLECTIONS = ("service_users", "today_plans", "inquiries")


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


def source_zip(function_dir: Path) -> bytes:
    required = ("index.js", "package.json", "config.json")
    missing = [name for name in required if not (function_dir / name).is_file()]
    if missing:
        raise DeployError(f"云函数目录缺少文件：{', '.join(missing)}")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in required:
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


def wait_for_function_active(cli: CloudBaseCli, region: str) -> None:
    for _ in range(45):
        detail = cli.api(
            region,
            "scf",
            "GetFunction",
            "2018-04-16",
            {"FunctionName": "api", "Namespace": cli.env_id},
            echo=False,
        )
        if detail.get("Status") == "Active" and detail.get("AvailableStatus") in {None, "Available"}:
            return
        time.sleep(2)
    raise DeployError("等待 api 云函数恢复 Active 状态超时。")


def deploy_function(cli: CloudBaseCli, region: str, function_dir: Path) -> None:
    archive = source_zip(function_dir)
    print(f"[cloudbase] 函数源码压缩包：{len(archive)} bytes")
    cli.api(
        region,
        "scf",
        "UpdateFunctionConfiguration",
        "2018-04-16",
        {
            "FunctionName": "api",
            "Namespace": cli.env_id,
            "Timeout": 15,
        },
    )
    wait_for_function_active(cli, region)
    cli.api(
        region,
        "scf",
        "UpdateFunctionCode",
        "2018-04-16",
        {
            "FunctionName": "api",
            "Namespace": cli.env_id,
            "Handler": "index.main",
            "InstallDependency": "TRUE",
            "Code": {"ZipFile": base64.b64encode(archive).decode("ascii")},
        },
    )
    wait_for_function_active(cli, region)


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
            if int(result.get("schemaVersion") or 0) == 2:
                print("[cloudbase] schemaVersion=2，云函数部署完成。")
                return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(3)
    raise DeployError("云函数更新后 90 秒内未返回 schemaVersion=2。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--env-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--function-dir", required=True, type=Path)
    args = parser.parse_args()

    cli = CloudBaseCli(args.cli, args.env_id)
    detail = cli.environment_detail()
    region = str(detail.get("region") or "ap-shanghai")
    databases = detail.get("resources", {}).get("databases") or []
    if not databases or not databases[0].get("InstanceId"):
        raise DeployError("云环境没有可用文档数据库实例。")
    database_tag = str(databases[0]["InstanceId"])

    print(f"[cloudbase] 环境：{args.env_id}，区域：{region}")
    ensure_collections(cli, region, database_tag)
    deploy_function(cli, region, args.function_dir)
    wait_for_schema(args.endpoint)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DeployError, KeyError) as error:
        print(f"[cloudbase] 部署失败：{error}", file=sys.stderr)
        raise SystemExit(1)
