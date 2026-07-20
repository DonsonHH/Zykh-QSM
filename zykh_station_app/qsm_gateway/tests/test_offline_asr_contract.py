from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class OfflineAsrContractTest(unittest.TestCase):
    def test_resident_service_uses_paraformer_on_board_port_6006(self) -> None:
        source = (ROOT / "qsm_gateway" / "start_asr_service.sh").read_text(encoding="utf-8")

        self.assertIn("sherpa-onnx-offline-websocket-server", source)
        self.assertIn('PORT="${ASR_WS_PORT:-6006}"', source)
        self.assertIn("--model-type=paraformer", source)
        self.assertIn("--paraformer=", source)

    def test_deployment_removes_old_zipformer_and_verifies_bundle(self) -> None:
        source = (ROOT / "scripts" / "deploy_local_asr.sh").read_text(encoding="utf-8")

        self.assertIn("rm -rf '$APP_ROOT/local_asr'", source)
        self.assertIn("check_checksum", source)
        self.assertIn('DEVICE_PORT="${QSM_LOCAL_ASR_FORWARD_DEVICE_PORT:-6006}"', source)
        self.assertIn("penicillin-allergy.wav", source)

    def test_gateway_startup_preloads_resident_asr(self) -> None:
        source = (ROOT / "qsm_gateway" / "start_station_gateway.sh").read_text(encoding="utf-8")

        self.assertIn("start_asr_service.sh", source)
        self.assertIn("resident Paraformer ASR", source)

    def test_microphone_stream_terminates_arecord_when_host_disconnects(self) -> None:
        source = (ROOT / "qsm_gateway" / "audio_capture_gateway.pl").read_text(encoding="utf-8")

        self.assertIn("my $capture_pid = open my $audio, '-|', @command", source)
        self.assertIn("stop_capture_process($capture_pid)", source)
        self.assertIn("kill 'TERM', $pid", source)
        self.assertIn("kill 'KILL', $pid", source)


if __name__ == "__main__":
    unittest.main()
