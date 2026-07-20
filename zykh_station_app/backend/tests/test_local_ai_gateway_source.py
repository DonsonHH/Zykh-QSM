from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LocalAiGatewaySourceTest(unittest.TestCase):
    def test_qsm_runtime_uses_bounded_memory_defaults(self) -> None:
        source = (ROOT / "qsm_gateway" / "start_local_ai.sh").read_text(encoding="utf-8")

        self.assertIn('CTX_SIZE="${LOCAL_AI_CTX_SIZE:-1024}"', source)
        self.assertIn('THREADS="${LOCAL_AI_THREADS:-3}"', source)
        self.assertIn('BATCH_SIZE="${LOCAL_AI_BATCH_SIZE:-128}"', source)
        self.assertIn('UBATCH_SIZE="${LOCAL_AI_UBATCH_SIZE:-32}"', source)
        self.assertIn('--ctx-size "$CTX_SIZE"', source)
        self.assertIn('--batch-size "$BATCH_SIZE"', source)
        self.assertIn('--ubatch-size "$UBATCH_SIZE"', source)


if __name__ == "__main__":
    unittest.main()
