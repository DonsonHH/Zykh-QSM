from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = APP_ROOT / "scripts" / "deploy_cloudbase_sync.py"
SHELL_SCRIPT_PATH = APP_ROOT / "scripts" / "deploy_cloudbase_sync.sh"
SPEC = importlib.util.spec_from_file_location("deploy_cloudbase_sync", SCRIPT_PATH)
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)


class FakeCli:
    def __init__(
        self,
        *,
        functions: tuple[str, ...] = ("api",),
        triggers: tuple[dict[str, object], ...] = (),
        environment: tuple[dict[str, str], ...] = (),
        function_details: dict[str, dict[str, object]] | None = None,
        invoke_result: dict[str, object] | None = None,
    ) -> None:
        self.env_id = "env-test"
        self.functions = set(functions)
        self.triggers = [dict(item) for item in triggers]
        self.environment = [dict(item) for item in environment]
        self.function_details = {
            name: {
                "FunctionName": name,
                "Status": "Active",
                "AvailableStatus": "Available",
                "Type": "Event",
                "Runtime": "Nodejs16.13",
                "Handler": "index.main",
            }
            for name in self.functions
        }
        for name, detail in (function_details or {}).items():
            self.function_details.setdefault(name, {}).update(detail)
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.invoke_result = invoke_result or {
            "InvokeResult": 0,
            "ErrMsg": "",
            "RetMsg": (
                '{"ok":true,"capability":"caregiverNotificationWorker","version":"v1"}'
            ),
        }

    def api(
        self,
        region: str,
        service: str,
        action: str,
        version: str,
        body: dict[str, object],
        *,
        echo: bool = True,
    ) -> dict[str, object]:
        del region, service, version, echo
        self.calls.append((action, body))
        if action == "ListFunctions":
            return {
                "Functions": [
                    {"FunctionName": name, "Status": "Active"}
                    for name in sorted(self.functions)
                ]
            }
        if action == "GetFunction":
            return {
                **self.function_details.get(str(body["FunctionName"]), {}),
                "Environment": {"Variables": self.environment},
            }
        if action == "CreateFunction":
            self.functions.add(str(body["FunctionName"]))
            self.function_details[str(body["FunctionName"])] = {
                "FunctionName": body["FunctionName"],
                "Status": "Active",
                "AvailableStatus": "Available",
                "Type": body["Type"],
                "Runtime": body["Runtime"],
                "Handler": body["Handler"],
            }
            self.environment = list((body.get("Environment") or {}).get("Variables") or [])
            return {}
        if action == "UpdateFunctionConfiguration":
            if body.get("Environment"):
                self.environment = list((body["Environment"] or {}).get("Variables") or [])
            return {}
        if action == "ListTriggers":
            return {"Triggers": [dict(item) for item in self.triggers]}
        if action == "CreateTrigger":
            self.triggers.append(
                {
                    "TriggerName": body["TriggerName"],
                    "Type": body["Type"],
                    "TriggerDesc": body["TriggerDesc"],
                    "Enable": body["Enable"],
                }
            )
            return {}
        if action == "UpdateTriggerStatus":
            for trigger in self.triggers:
                if trigger.get("TriggerName") == body["TriggerName"]:
                    trigger["Enable"] = body["Enable"]
            return {}
        if action == "InvokeFunction":
            return {"Result": dict(self.invoke_result)}
        return {}


class CloudBaseDeployContractTest(unittest.TestCase):
    def _function_dir(self, required: tuple[str, ...]) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for name in required:
            (root / name).write_text(f"// {name}\n", encoding="utf-8")
        (root / "test-secret.cjs").write_text("throw new Error('not deployable')\n", encoding="utf-8")
        return temporary, root

    def test_worker_archive_uses_an_explicit_production_whitelist(self) -> None:
        temporary, root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(temporary.cleanup)

        archive = deploy.source_zip(root, deploy.WORKER_SPEC.required_files)

        with tempfile.NamedTemporaryFile(suffix=".zip") as output:
            output.write(archive)
            output.flush()
            with zipfile.ZipFile(output.name) as packaged:
                self.assertEqual(
                    sorted(packaged.namelist()),
                    sorted(deploy.WORKER_SPEC.required_files),
                )
                self.assertNotIn("test-secret.cjs", packaged.namelist())

    def test_missing_worker_is_created_as_a_bounded_event_function(self) -> None:
        temporary, root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(temporary.cleanup)
        cli = FakeCli(functions=("api",))

        deploy.deploy_function(
            cli,
            "ap-shanghai",
            root,
            deploy.WORKER_SPEC,
            environment={
                "CAREGIVER_NOTIFICATION_PAGE": "pages/records/index",
                "CAREGIVER_NOTIFICATION_TRIGGER_NAME": deploy.WORKER_TRIGGER_NAME,
            },
        )

        create = next(body for action, body in cli.calls if action == "CreateFunction")
        self.assertEqual(create["FunctionName"], "caregiverNotificationWorker")
        self.assertEqual(create["Handler"], "index.main")
        self.assertEqual(create["Runtime"], "Nodejs16.13")
        self.assertEqual(create["Type"], "Event")
        self.assertEqual(create["Timeout"], 30)
        self.assertEqual(create["CodeSource"], "ZipFile")
        self.assertTrue((create["Code"] or {}).get("ZipFile"))

    def test_existing_worker_update_preserves_unrelated_environment_variables(self) -> None:
        temporary, root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            environment=(
                {"Key": "UNRELATED_SECRET", "Value": "keep-me"},
                {"Key": "CAREGIVER_NOTIFICATION_PAGE", "Value": "old-page"},
            ),
        )

        deploy.deploy_function(
            cli,
            "ap-shanghai",
            root,
            deploy.WORKER_SPEC,
            environment={"CAREGIVER_NOTIFICATION_PAGE": "pages/records/index"},
        )

        configuration = next(
            body for action, body in cli.calls if action == "UpdateFunctionConfiguration"
        )
        variables = {
            item["Key"]: item["Value"]
            for item in (configuration["Environment"] or {})["Variables"]
        }
        self.assertEqual(variables["UNRELATED_SECRET"], "keep-me")
        self.assertEqual(variables["CAREGIVER_NOTIFICATION_PAGE"], "pages/records/index")
        self.assertTrue(any(action == "UpdateFunctionCode" for action, _ in cli.calls))

    def test_timer_is_created_closed_and_only_explicitly_enabled(self) -> None:
        cli = FakeCli(functions=("api", "caregiverNotificationWorker"))

        deploy.ensure_worker_trigger(cli, "ap-shanghai", enable=False)

        create = next(body for action, body in cli.calls if action == "CreateTrigger")
        self.assertEqual(create["TriggerName"], deploy.WORKER_TRIGGER_NAME)
        self.assertEqual(create["TriggerDesc"], deploy.WORKER_TRIGGER_CRON)
        self.assertEqual(create["Enable"], "CLOSE")

        deploy.ensure_worker_trigger(cli, "ap-shanghai", enable=True)
        update = next(body for action, body in cli.calls if action == "UpdateTriggerStatus")
        self.assertEqual(update["Enable"], "OPEN")

    def test_conflicting_existing_timer_fails_without_deleting_it(self) -> None:
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            triggers=(
                {
                    "TriggerName": deploy.WORKER_TRIGGER_NAME,
                    "Type": "timer",
                    "TriggerDesc": "0 */9 * * * * *",
                    "Enable": "CLOSE",
                },
            ),
        )

        with self.assertRaisesRegex(deploy.DeployError, "触发器配置"):
            deploy.ensure_worker_trigger(cli, "ap-shanghai", enable=False)

        self.assertFalse(any(action == "DeleteTrigger" for action, _ in cli.calls))

    def test_worker_enablement_requires_all_external_confirmations(self) -> None:
        for values in (
            {"template_id": "", "page": "pages/records/index", "openapi": True, "subscriptions": True},
            {"template_id": "tpl", "page": "", "openapi": True, "subscriptions": True},
            {"template_id": "tpl", "page": "pages/records/index", "openapi": False, "subscriptions": True},
            {"template_id": "tpl", "page": "pages/records/index", "openapi": True, "subscriptions": False},
        ):
            with self.subTest(values=values):
                with self.assertRaises(deploy.DeployError):
                    deploy.validate_worker_enablement(**values)

        deploy.validate_worker_enablement(
            template_id="tpl-approved",
            page="pages/records/index",
            openapi=True,
            subscriptions=True,
        )

    def _shell_arguments(self, extra_environment: dict[str, str] | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            fake_python = Path(temporary) / "python"
            fake_python.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            environment = {
                **os.environ,
                "PYTHON": str(fake_python),
                "CLOUDBASE_CLI": "/bin/true",
            }
            environment.update(extra_environment or {})
            completed = subprocess.run(
                ["sh", str(SHELL_SCRIPT_PATH)],
                cwd=APP_ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.splitlines()

    def test_shell_deploys_api_and_worker_but_keeps_timer_closed_by_default(self) -> None:
        arguments = self._shell_arguments()

        self.assertIn("--function-dir", arguments)
        self.assertIn(str(APP_ROOT / "cloudbase" / "cloudfunctions" / "api"), arguments)
        self.assertIn("--worker-function-dir", arguments)
        self.assertIn(
            str(APP_ROOT / "cloudbase" / "cloudfunctions" / "caregiverNotificationWorker"),
            arguments,
        )
        self.assertNotIn("--enable-notification-worker", arguments)

    def test_shell_only_enables_worker_with_all_explicit_confirmations(self) -> None:
        arguments = self._shell_arguments({
            "CLOUDBASE_ENABLE_NOTIFICATION_WORKER": "1",
            "CAREGIVER_NOTIFICATION_TEMPLATE_ID": "tpl-approved",
            "CAREGIVER_NOTIFICATION_PAGE": "pages/records/index",
            "CLOUDBASE_CONFIRM_WORKER_OPENAPI_PERMISSION": "1",
            "CLOUDBASE_CONFIRM_NOTIFICATION_SUBSCRIPTIONS": "1",
        })

        for expected in (
            "--enable-notification-worker",
            "--notification-template-id",
            "tpl-approved",
            "--notification-page",
            "pages/records/index",
            "--confirm-worker-openapi-permission",
            "--confirm-notification-subscriptions",
        ):
            self.assertIn(expected, arguments)

    def test_stack_closes_worker_before_updates_and_only_opens_after_schema_check(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            triggers=({
                "TriggerName": deploy.WORKER_TRIGGER_NAME,
                "Type": "timer",
                "TriggerDesc": deploy.WORKER_TRIGGER_CRON,
                "Enable": "OPEN",
            },),
        )

        def schema_checked(_: str) -> None:
            cli.calls.append(("SchemaChecked", {}))

        with patch.object(deploy, "wait_for_schema", side_effect=schema_checked):
            deploy.deploy_application(
                cli=cli,
                region="ap-shanghai",
                api_function_dir=api_root,
                worker_function_dir=worker_root,
                endpoint="https://example.invalid/api",
                worker_environment={
                    "CAREGIVER_NOTIFICATION_PAGE": "pages/records/index",
                    "CAREGIVER_NOTIFICATION_TRIGGER_NAME": deploy.WORKER_TRIGGER_NAME,
                },
                enable_worker=True,
            )

        sequence = [
            (
                action,
                str(body.get("Enable") if action == "UpdateTriggerStatus" else body.get("FunctionName") or ""),
            )
            for action, body in cli.calls
            if action in {
                "UpdateTriggerStatus",
                "UpdateFunctionConfiguration",
                "SchemaChecked",
            }
        ]
        self.assertEqual(sequence[0], ("UpdateTriggerStatus", "CLOSE"))
        self.assertLess(
            sequence.index(("UpdateFunctionConfiguration", "caregiverNotificationWorker")),
            sequence.index(("UpdateFunctionConfiguration", "api")),
        )
        self.assertLess(
            sequence.index(("SchemaChecked", "")),
            sequence.index(("UpdateTriggerStatus", "OPEN")),
        )

    def test_stack_rejects_a_same_name_worker_with_the_wrong_function_identity(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            function_details={
                "caregiverNotificationWorker": {
                    "Type": "Web",
                    "Runtime": "Python3.10",
                    "Handler": "legacy.main",
                },
            },
        )

        with patch.object(deploy, "wait_for_schema", return_value=None):
            with self.assertRaisesRegex(deploy.DeployError, "身份|运行时|类型"):
                deploy.deploy_application(
                    cli=cli,
                    region="ap-shanghai",
                    api_function_dir=api_root,
                    worker_function_dir=worker_root,
                    endpoint="https://example.invalid/api",
                    worker_environment={},
                    enable_worker=False,
                )

        mutating_actions = {
            "CreateFunction",
            "UpdateFunctionConfiguration",
            "UpdateFunctionCode",
            "CreateTrigger",
            "UpdateTriggerStatus",
        }
        self.assertFalse(any(action in mutating_actions for action, _ in cli.calls))

    def test_stack_rejects_any_unmanaged_worker_trigger_before_code_update(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            triggers=(
                {
                    "TriggerName": deploy.WORKER_TRIGGER_NAME,
                    "Type": "timer",
                    "TriggerDesc": deploy.WORKER_TRIGGER_CRON,
                    "Enable": "CLOSE",
                },
                {
                    "TriggerName": "legacy-open-trigger",
                    "Type": "timer",
                    "TriggerDesc": "0 */5 * * * * *",
                    "Enable": "OPEN",
                },
            ),
        )

        with patch.object(deploy, "wait_for_schema", return_value=None):
            with self.assertRaisesRegex(deploy.DeployError, "未受管触发器"):
                deploy.deploy_application(
                    cli=cli,
                    region="ap-shanghai",
                    api_function_dir=api_root,
                    worker_function_dir=worker_root,
                    endpoint="https://example.invalid/api",
                    worker_environment={},
                    enable_worker=False,
                )

        self.assertFalse(any(
            action in {"UpdateFunctionConfiguration", "UpdateFunctionCode"}
            for action, _ in cli.calls
        ))

    def test_stack_missing_api_fails_before_worker_or_trigger_mutation(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(functions=("caregiverNotificationWorker",))

        with self.assertRaisesRegex(deploy.DeployError, "缺少既有 api"):
            deploy.deploy_application(
                cli=cli,
                region="ap-shanghai",
                api_function_dir=api_root,
                worker_function_dir=worker_root,
                endpoint="https://example.invalid/api",
                worker_environment={},
                enable_worker=False,
            )

        self.assertFalse(any(
            action in {
                "CreateFunction",
                "UpdateFunctionConfiguration",
                "UpdateFunctionCode",
                "CreateTrigger",
                "UpdateTriggerStatus",
            }
            for action, _ in cli.calls
        ))

    def test_schema_failure_leaves_the_existing_worker_timer_closed(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            triggers=({
                "TriggerName": deploy.WORKER_TRIGGER_NAME,
                "Type": "timer",
                "TriggerDesc": deploy.WORKER_TRIGGER_CRON,
                "Enable": "OPEN",
            },),
        )

        with patch.object(
            deploy,
            "wait_for_schema",
            side_effect=deploy.DeployError("schema probe failed"),
        ):
            with self.assertRaisesRegex(deploy.DeployError, "schema probe failed"):
                deploy.deploy_application(
                    cli=cli,
                    region="ap-shanghai",
                    api_function_dir=api_root,
                    worker_function_dir=worker_root,
                    endpoint="https://example.invalid/api",
                    worker_environment={},
                    enable_worker=True,
                )

        managed = next(
            row for row in cli.triggers
            if row["TriggerName"] == deploy.WORKER_TRIGGER_NAME
        )
        self.assertEqual(managed["Enable"], "CLOSE")
        self.assertFalse(any(
            action == "UpdateTriggerStatus" and body.get("Enable") == "OPEN"
            for action, body in cli.calls
        ))

    def test_worker_runtime_probe_must_pass_before_timer_can_open(self) -> None:
        api_temporary, api_root = self._function_dir(deploy.API_SPEC.required_files)
        worker_temporary, worker_root = self._function_dir(deploy.WORKER_SPEC.required_files)
        self.addCleanup(api_temporary.cleanup)
        self.addCleanup(worker_temporary.cleanup)
        cli = FakeCli(
            functions=("api", "caregiverNotificationWorker"),
            triggers=({
                "TriggerName": deploy.WORKER_TRIGGER_NAME,
                "Type": "timer",
                "TriggerDesc": deploy.WORKER_TRIGGER_CRON,
                "Enable": "CLOSE",
            },),
            invoke_result={
                "InvokeResult": 1,
                "ErrMsg": "handler failed",
                "RetMsg": "",
            },
        )

        with patch.object(deploy, "wait_for_schema", return_value=None):
            with self.assertRaisesRegex(deploy.DeployError, "运行探针"):
                deploy.deploy_application(
                    cli=cli,
                    region="ap-shanghai",
                    api_function_dir=api_root,
                    worker_function_dir=worker_root,
                    endpoint="https://example.invalid/api",
                    worker_environment={},
                    enable_worker=True,
                )

        self.assertTrue(any(action == "InvokeFunction" for action, _ in cli.calls))
        self.assertFalse(any(
            action == "UpdateTriggerStatus" and body.get("Enable") == "OPEN"
            for action, body in cli.calls
        ))


if __name__ == "__main__":
    unittest.main()
