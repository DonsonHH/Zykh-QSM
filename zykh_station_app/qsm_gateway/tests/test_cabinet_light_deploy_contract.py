from __future__ import annotations

import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_ROOT = APP_ROOT / "qsm_gateway"


class CabinetLightDeployContractTest(unittest.TestCase):
    def test_station_start_uses_v2_uart_and_turns_lights_off_before_serving(self) -> None:
        source = (GATEWAY_ROOT / "start_station_gateway.sh").read_text(encoding="utf-8")

        self.assertIn('CABINET_LIGHT_UART="${CABINET_LIGHT_UART:-/dev/ttyACM0}"', source)
        self.assertIn('CABINET_LIGHT_UART_BAUD="${CABINET_LIGHT_UART_BAUD:-115200}"', source)
        self.assertIn("Zykh::CabinetLightProtocol->new", source)
        self.assertIn("$protocol->off()", source)
        self.assertLess(source.index("$protocol->off()"), source.index('perl "$QSM_HOME/server.pl" --daemon'))
        self.assertNotIn(
            "print STDERR((",
            source,
            "Perl parses STDERR(...) as a subroutine call and hides the real OFF failure",
        )

    def test_every_station_gateway_deployer_ships_the_protocol_module(self) -> None:
        for relative in (
            "scripts/deploy_qsm_gateway.sh",
            "scripts/deploy_local_asr.sh",
            "scripts/deploy_offline_tts.sh",
        ):
            with self.subTest(relative=relative):
                source = (APP_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("CabinetLightProtocol.pm", source)
                self.assertIn("Zykh", source)


if __name__ == "__main__":
    unittest.main()
