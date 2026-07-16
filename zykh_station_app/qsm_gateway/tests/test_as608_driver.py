from __future__ import annotations

import json
import os
import pty
import select
import struct
import subprocess
import threading
import tty
import unittest
from pathlib import Path


DRIVER = Path(__file__).resolve().parents[1] / "as608.pl"


def acknowledgement(code: int) -> bytes:
    body = bytes([0x07, 0x00, 0x03, code])
    return bytes.fromhex("ef01ffffffff") + body + struct.pack(">H", sum(body) & 0xFFFF)


class As608DriverTest(unittest.TestCase):
    def test_no_valid_image_is_accepted_as_stable_finger_removal(self) -> None:
        master, slave = pty.openpty()
        tty.setraw(slave)
        responses = iter([0x00, 0x00, 0x15, 0x15, 0x00, 0x00, 0x00, 0x00])
        instructions: list[int] = []
        stop = threading.Event()

        def emulate_module() -> None:
            buffer = b""
            while not stop.is_set():
                ready, _, _ = select.select([master], [], [], 0.1)
                if not ready:
                    continue
                chunk = os.read(master, 512)
                if not chunk:
                    return
                buffer += chunk
                while True:
                    start = buffer.find(bytes.fromhex("ef01"))
                    if start < 0:
                        buffer = buffer[-1:]
                        break
                    buffer = buffer[start:]
                    if len(buffer) < 9:
                        break
                    packet_length = int.from_bytes(buffer[7:9], "big")
                    total_length = 9 + packet_length
                    if len(buffer) < total_length:
                        break
                    packet, buffer = buffer[:total_length], buffer[total_length:]
                    instructions.append(packet[9])
                    os.write(master, acknowledgement(next(responses)))

        thread = threading.Thread(target=emulate_module, daemon=True)
        thread.start()
        env = os.environ.copy()
        env["AS608_DEVICE"] = os.ttyname(slave)
        try:
            process = subprocess.run(
                ["perl", str(DRIVER), "enroll", "42", "3"],
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        finally:
            stop.set()
            thread.join(timeout=1)
            os.close(master)
            os.close(slave)

        events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        self.assertEqual(process.returncode, 0, process.stderr or process.stdout)
        self.assertEqual(
            [event.get("event") for event in events],
            [
                "place_finger_first",
                "remove_finger",
                "finger_removed",
                "place_same_finger_second",
                "enrolled",
            ],
        )
        self.assertEqual(instructions, [0x01, 0x02, 0x01, 0x01, 0x01, 0x02, 0x05, 0x06])


if __name__ == "__main__":
    unittest.main()
