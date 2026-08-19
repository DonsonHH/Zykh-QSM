from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
import unittest
from pathlib import Path


GATEWAY_DIR = Path(__file__).resolve().parents[1]
LIB_DIR = GATEWAY_DIR / "lib"


class CabinetController:
    def __init__(self, master_fd: int, replies: dict[str, str]) -> None:
        self.master_fd = master_fd
        self.replies = replies
        self.commands: list[str] = []
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "CabinetController":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        self._thread.join(timeout=3)
        if self._thread.is_alive():
            raise AssertionError("cabinet controller did not finish")
        if self.error is not None:
            raise self.error

    def _run(self) -> None:
        try:
            pending = b""
            deadline = time.monotonic() + 3
            while self.replies and time.monotonic() < deadline:
                ready, _, _ = select.select([self.master_fd], [], [], 0.1)
                if not ready:
                    continue
                chunk = os.read(self.master_fd, 4096)
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    raw, pending = pending.split(b"\n", 1)
                    command = raw.rstrip(b"\r").decode("ascii")
                    if not command:
                        continue
                    self.commands.append(command)
                    reply = self.replies.pop(command)
                    os.write(self.master_fd, f"{reply}\r\n".encode("ascii"))
            if self.replies:
                raise AssertionError(f"controller did not receive: {sorted(self.replies)}")
        except BaseException as exc:  # pragma: no cover - surfaced by __exit__
            self.error = exc


class CabinetLightProtocolTest(unittest.TestCase):
    def run_protocol(
        self,
        method: str,
        device: str,
        *args: object,
        ignore_sigchld: bool = False,
    ) -> dict[str, object]:
        perl_args = ", ".join(repr(str(argument)) for argument in args)
        signal_setup = "$SIG{CHLD} = 'IGNORE'; " if ignore_sigchld else ""
        expression = (
            signal_setup
            + "my $protocol = Zykh::CabinetLightProtocol->new("
            f"device => {device!r}, timeout_seconds => 1); "
            f"print JSON::PP::encode_json($protocol->{method}({perl_args}));"
        )
        completed = subprocess.run(
            [
                "perl",
                "-I",
                str(LIB_DIR),
                "-MJSON::PP",
                "-MZykh::CabinetLightProtocol",
                "-e",
                expression,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stderr, "")
        return json.loads(completed.stdout)

    def test_illuminate_requires_ack_and_status_confirmation(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {
                "CABINET 2": "OK CABINET 2",
                "STATUS": "STATUS CABINET 2",
            }) as controller:
                result = self.run_protocol("illuminate", slave_name, 2)
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "success")
        self.assertEqual(result["cabinet_id"], 2)
        self.assertEqual(result["status"], "cabinet_2")
        self.assertEqual(controller.commands, ["CABINET 2", "STATUS"])

    def test_wrong_ack_is_result_unknown_and_never_claims_success(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {"CABINET 3": "OK CABINET 2"}) as controller:
                result = self.run_protocol("illuminate", slave_name, 3)
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertFalse(result["ok"])
        self.assertEqual(result["result"], "result_unknown")
        self.assertTrue(result["result_unknown"])
        self.assertFalse(result["retry_safe"])
        self.assertEqual(controller.commands, ["CABINET 3"])

    def test_off_requires_off_ack_and_status_confirmation(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {
                "OFF": "OK OFF",
                "STATUS": "STATUS OFF",
            }) as controller:
                result = self.run_protocol("off", slave_name)
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "off")
        self.assertEqual(controller.commands, ["OFF", "STATUS"])

    def test_off_ack_mismatch_is_unknown_but_safe_to_retry(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {"OFF": "OK CABINET 1"}) as controller:
                result = self.run_protocol("off", slave_name)
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertFalse(result["ok"])
        self.assertEqual(result["result"], "result_unknown")
        self.assertTrue(result["result_unknown"])
        self.assertTrue(result["retry_safe"])
        self.assertIn("可安全重试", result["detail"])
        self.assertEqual(controller.commands, ["OFF"])

    def test_status_is_read_only_and_parses_active_cabinet(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {"STATUS": "STATUS CABINET 1"}) as controller:
                result = self.run_protocol("status", slave_name)
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "cabinet_1")
        self.assertEqual(result["cabinet_id"], 1)
        self.assertEqual(controller.commands, ["STATUS"])

    def test_status_works_when_gateway_ignores_sigchld(self) -> None:
        master_fd, slave_fd = os.openpty()
        slave_name = os.ttyname(slave_fd)
        try:
            with CabinetController(master_fd, {"STATUS": "STATUS OFF"}) as controller:
                result = self.run_protocol(
                    "status",
                    slave_name,
                    ignore_sigchld=True,
                )
        finally:
            os.close(master_fd)
            os.close(slave_fd)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "off")
        self.assertEqual(controller.commands, ["STATUS"])

    def test_invalid_cabinet_is_rejected_before_opening_uart(self) -> None:
        result = self.run_protocol("illuminate", "/definitely/missing", 4)

        self.assertFalse(result["ok"])
        self.assertEqual(result["result"], "invalid_cabinet")
        self.assertTrue(result["retry_safe"])


if __name__ == "__main__":
    unittest.main()
