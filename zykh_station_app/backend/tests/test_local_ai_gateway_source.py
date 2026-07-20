from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class LocalAiGatewaySourceTest(unittest.TestCase):
    def test_qsm_runtime_uses_bounded_memory_defaults(self) -> None:
        source = (ROOT / "qsm_gateway" / "start_local_ai.sh").read_text(encoding="utf-8")

        self.assertIn('CTX_SIZE="${LOCAL_AI_CTX_SIZE:-1536}"', source)
        self.assertIn('THREADS="${LOCAL_AI_THREADS:-4}"', source)
        self.assertIn('BATCH_SIZE="${LOCAL_AI_BATCH_SIZE:-256}"', source)
        self.assertIn('UBATCH_SIZE="${LOCAL_AI_UBATCH_SIZE:-64}"', source)
        self.assertIn('CACHE_RAM="${LOCAL_AI_CACHE_RAM:-64}"', source)
        self.assertIn('--ctx-size "$CTX_SIZE"', source)
        self.assertIn('--batch-size "$BATCH_SIZE"', source)
        self.assertIn('--ubatch-size "$UBATCH_SIZE"', source)
        self.assertIn('--cache-type-k q8_0', source)
        self.assertIn('--cache-type-v q8_0', source)
        self.assertIn('--cache-ram "$CACHE_RAM"', source)
        self.assertIn('--cache-prompt', source)
        self.assertIn('--offline', source)
        self.assertIn('--no-webui', source)


if __name__ == "__main__":
    unittest.main()
