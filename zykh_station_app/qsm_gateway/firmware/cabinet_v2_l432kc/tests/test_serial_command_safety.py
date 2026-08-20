#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "serial_command_test.sh"


class FakeController(threading.Thread):
    def __init__(self, master_fd: int, responses: list[str]) -> None:
        super().__init__(daemon=True)
        self.master_fd = master_fd
        self.response_count = len(responses)
        self.responses = iter(responses)
        self.commands: list[str] = []
        self.error: BaseException | None = None

    def run(self) -> None:
        buffer = b""
        try:
            while True:
                ready, _, _ = select.select([self.master_fd], [], [], 5)
                if not ready:
                    return
                chunk = os.read(self.master_fd, 256)
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n" in buffer:
                    raw_command, buffer = buffer.split(b"\r\n", 1)
                    command = raw_command.decode("ascii")
                    self.commands.append(command)
                    try:
                        response = next(self.responses)
                    except StopIteration:
                        return
                    os.write(self.master_fd, f"{response}\r\n".encode("ascii"))
                    if len(self.commands) == self.response_count:
                        return
        except BaseException as exc:  # surfaced by assert_finished
            self.error = exc

    def assert_finished(self) -> None:
        self.join(timeout=6)
        assert not self.is_alive(), "fake controller did not finish"
        if self.error is not None:
            raise self.error


def run_light_test(
    command: str,
    responses: list[str],
    lock_path: Path,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    master_fd, slave_fd = pty.openpty()
    device_dir = Path(tempfile.mkdtemp(prefix="devices-", dir=lock_path.parent))
    (device_dir / "ttyACM0").symlink_to(os.ttyname(slave_fd))
    controller = FakeController(master_fd, responses)
    controller.start()
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_LIGHT_COMMANDS": "1",
            "CABINET_LIGHT_DEVICE_DIR": str(device_dir),
            "CABINET_LIGHT_LOCK_FILE": str(lock_path),
            "CABINET_LIGHT_TEST_MODE": "1",
            "LIGHT_HOLD_SECONDS": "0",
        }
    )
    try:
        result = subprocess.run(
            [str(SCRIPT), os.ttyname(slave_fd), command, f"OK {command}"],
            text=True,
            capture_output=True,
            timeout=15,
            env=env,
            check=False,
        )
        controller.assert_finished()
        return result, controller.commands
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def test_success_is_one_bounded_light_lifecycle(temp_dir: Path) -> None:
    result, commands = run_light_test(
        "CABINET 2",
        [
            "OK OFF",
            "STATUS OFF",
            "OK CABINET 2",
            "STATUS CABINET 2",
            "OK OFF",
            "STATUS OFF",
        ],
        temp_dir / "hardware.lock",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert commands == ["OFF", "STATUS", "CABINET 2", "STATUS", "OFF", "STATUS"]
    assert "LIGHT_TEST PASS cabinet=2 final_status=off" in result.stdout


def test_failure_after_light_attempts_off_before_exit(temp_dir: Path) -> None:
    result, commands = run_light_test(
        "CABINET 1",
        [
            "OK OFF",
            "STATUS OFF",
            "OK CABINET 1",
            "STATUS OFF",
            "OK OFF",
            "STATUS OFF",
        ],
        temp_dir / "hardware.lock",
    )
    assert result.returncode != 0
    assert commands == ["OFF", "STATUS", "CABINET 1", "STATUS", "OFF", "STATUS"]
    assert "cleanup_off=attempted" in result.stderr


def test_final_status_failure_repeats_off_in_cleanup(temp_dir: Path) -> None:
    result, commands = run_light_test(
        "CABINET 1",
        [
            "OK OFF",
            "STATUS OFF",
            "OK CABINET 1",
            "STATUS CABINET 1",
            "OK OFF",
            "STATUS CABINET 1",
            "OK OFF",
            "STATUS OFF",
        ],
        temp_dir / "final-status.lock",
    )
    assert result.returncode != 0
    assert commands == [
        "OFF",
        "STATUS",
        "CABINET 1",
        "STATUS",
        "OFF",
        "STATUS",
        "OFF",
        "STATUS",
    ]
    assert "cleanup_status=STATUS OFF" in result.stderr


def test_existing_hardware_lock_rejects_without_uart_access(temp_dir: Path) -> None:
    lock_path = temp_dir / "hardware.lock"
    master_fd, slave_fd = pty.openpty()
    device_dir = temp_dir / "locked-devices"
    device_dir.mkdir()
    (device_dir / "ttyACM0").symlink_to(os.ttyname(slave_fd))
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_LIGHT_COMMANDS": "1",
            "CABINET_LIGHT_DEVICE_DIR": str(device_dir),
            "CABINET_LIGHT_LOCK_FILE": str(lock_path),
            "CABINET_LIGHT_TEST_MODE": "1",
            "LIGHT_HOLD_SECONDS": "0",
        }
    )
    try:
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(
                [str(SCRIPT), os.ttyname(slave_fd), "CABINET 3", "OK CABINET 3"],
                text=True,
                capture_output=True,
                timeout=5,
                env=env,
                check=False,
            )
        ready, _, _ = select.select([master_fd], [], [], 0)
        assert result.returncode != 0
        assert "another cabinet light test is active" in result.stderr
        assert not ready, "locked invocation must not touch the UART"
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def test_status_respects_existing_hardware_lock(temp_dir: Path) -> None:
    lock_path = temp_dir / "status.lock"
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env.update(
        {
            "CABINET_LIGHT_LOCK_FILE": str(lock_path),
            "CABINET_LIGHT_TEST_MODE": "1",
        }
    )
    try:
        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(
                [str(SCRIPT), os.ttyname(slave_fd), "STATUS", "STATUS OFF"],
                text=True,
                capture_output=True,
                timeout=5,
                env=env,
                check=False,
            )
        ready, _, _ = select.select([master_fd], [], [], 0)
        assert result.returncode != 0
        assert "cabinet controller is busy" in result.stderr
        assert not ready, "locked STATUS invocation must not touch the UART"
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def test_multiple_controller_candidates_are_rejected(temp_dir: Path) -> None:
    device_dir = temp_dir / "multiple-devices"
    device_dir.mkdir()
    first_master, first_slave = pty.openpty()
    second_master, second_slave = pty.openpty()
    (device_dir / "ttyACM0").symlink_to(os.ttyname(first_slave))
    (device_dir / "ttyACM1").symlink_to(os.ttyname(second_slave))
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_LIGHT_COMMANDS": "1",
            "CABINET_LIGHT_DEVICE_DIR": str(device_dir),
            "CABINET_LIGHT_LOCK_FILE": str(temp_dir / "multiple.lock"),
            "CABINET_LIGHT_TEST_MODE": "1",
            "LIGHT_HOLD_SECONDS": "0",
        }
    )
    try:
        result = subprocess.run(
            [str(SCRIPT), os.ttyname(first_slave), "CABINET 1", "OK CABINET 1"],
            text=True,
            capture_output=True,
            timeout=5,
            env=env,
            check=False,
        )
        assert result.returncode != 0
        assert "exactly one ttyACM controller is required" in result.stderr
    finally:
        os.close(first_slave)
        os.close(first_master)
        os.close(second_slave)
        os.close(second_master)


def test_test_only_overrides_reject_real_device_mode(temp_dir: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "CABINET_LIGHT_DEVICE_DIR": str(temp_dir),
            "CABINET_LIGHT_LOCK_FILE": str(temp_dir / "override.lock"),
        }
    )
    result = subprocess.run(
        [str(SCRIPT), "/dev/null", "STATUS", "STATUS OFF"],
        text=True,
        capture_output=True,
        timeout=5,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "test-only UART overrides require a PTY" in result.stderr


def test_test_only_overrides_reject_pty_path_traversal(temp_dir: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "CABINET_LIGHT_DEVICE_DIR": str(temp_dir),
            "CABINET_LIGHT_LOCK_FILE": str(temp_dir / "traversal.lock"),
            "CABINET_LIGHT_TEST_MODE": "1",
        }
    )
    result = subprocess.run(
        [str(SCRIPT), "/dev/pts/../null", "STATUS", "STATUS OFF"],
        text=True,
        capture_output=True,
        timeout=5,
        env=env,
        check=False,
    )
    assert result.returncode != 0
    assert "test-only UART overrides require a PTY" in result.stderr


def test_off_ignores_invalid_light_hold_setting(temp_dir: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    controller = FakeController(master_fd, ["OK OFF"])
    controller.start()
    env = os.environ.copy()
    env.update(
        {
            "CABINET_LIGHT_LOCK_FILE": str(temp_dir / "off.lock"),
            "CABINET_LIGHT_TEST_MODE": "1",
            "LIGHT_HOLD_SECONDS": "not-a-duration",
        }
    )
    try:
        result = subprocess.run(
            [str(SCRIPT), os.ttyname(slave_fd), "OFF", "OK OFF"],
            text=True,
            capture_output=True,
            timeout=5,
            env=env,
            check=False,
        )
        controller.assert_finished()
        assert result.returncode == 0, result.stdout + result.stderr
        assert controller.commands == ["OFF"]
    finally:
        os.close(slave_fd)
        os.close(master_fd)


def test_term_preserves_exit_code_and_attempts_off(temp_dir: Path) -> None:
    master_fd, slave_fd = pty.openpty()
    device_dir = temp_dir / "signal-devices"
    device_dir.mkdir()
    (device_dir / "ttyACM0").symlink_to(os.ttyname(slave_fd))
    controller = FakeController(
        master_fd,
        [
            "OK OFF",
            "STATUS OFF",
            "OK CABINET 1",
            "STATUS CABINET 1",
            "OK OFF",
            "STATUS OFF",
        ],
    )
    controller.start()
    env = os.environ.copy()
    env.update(
        {
            "ALLOW_LIGHT_COMMANDS": "1",
            "CABINET_LIGHT_DEVICE_DIR": str(device_dir),
            "CABINET_LIGHT_LOCK_FILE": str(temp_dir / "signal.lock"),
            "CABINET_LIGHT_TEST_MODE": "1",
            "LIGHT_HOLD_SECONDS": "30",
        }
    )
    process = subprocess.Popen(
        [str(SCRIPT), os.ttyname(slave_fd), "CABINET 1", "OK CABINET 1"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while len(controller.commands) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert controller.commands[:4] == ["OFF", "STATUS", "CABINET 1", "STATUS"]
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
        controller.assert_finished()
        assert process.returncode == 143, stdout + stderr
        assert controller.commands == [
            "OFF",
            "STATUS",
            "CABINET 1",
            "STATUS",
            "OFF",
            "STATUS",
        ]
        assert "cleanup_status=STATUS OFF" in stderr
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        os.close(slave_fd)
        os.close(master_fd)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zykh-cabinet-serial-test.") as raw_temp_dir:
        temp_dir = Path(raw_temp_dir)
        test_success_is_one_bounded_light_lifecycle(temp_dir)
        test_failure_after_light_attempts_off_before_exit(temp_dir)
        test_final_status_failure_repeats_off_in_cleanup(temp_dir)
        test_existing_hardware_lock_rejects_without_uart_access(temp_dir)
        test_status_respects_existing_hardware_lock(temp_dir)
        test_multiple_controller_candidates_are_rejected(temp_dir)
        test_test_only_overrides_reject_real_device_mode(temp_dir)
        test_test_only_overrides_reject_pty_path_traversal(temp_dir)
        test_off_ignores_invalid_light_hold_setting(temp_dir)
        test_term_preserves_exit_code_and_attempts_off(temp_dir)
    print(
        "SERIAL_COMMAND_SAFETY PASS lifecycle=single-panel "
        "controller=unique lock=exclusive cleanup=off"
    )


if __name__ == "__main__":
    main()
