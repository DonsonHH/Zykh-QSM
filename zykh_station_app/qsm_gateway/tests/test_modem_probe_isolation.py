from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_SOURCE = REPOSITORY_ROOT / "zykh_app" / "server.pl"


class ModemProbeIsolationTest(unittest.TestCase):
    def test_generic_status_never_runs_the_explicit_modem_network_probe(self) -> None:
        source = GATEWAY_SOURCE.read_text(encoding="utf-8-sig")
        api_status = source.split("sub api_status {", 1)[1].split(
            "sub qsm_network_status {", 1
        )[0]

        self.assertNotIn("qsm_network_status()", api_status)
        self.assertIn("network_probe", api_status)
        self.assertIn("'not_requested'", api_status)
        self.assertIn("'/api/network/status'", source)
        self.assertIn("return send_json($client, 200, qsm_network_status());", source)


if __name__ == "__main__":
    unittest.main()
