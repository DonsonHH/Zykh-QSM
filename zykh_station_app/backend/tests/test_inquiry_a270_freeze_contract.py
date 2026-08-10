from __future__ import annotations

import hashlib
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AI_DECISION_SHA256_AT_A27057C = {
    "app/services/ai_service.py": "6048456f3c14c596f7c467bbcde4ed4ae23cf38dc22d99c213d332453b0c31c5",
    "app/services/inquiry_dialogue_policy.py": "c928cd70625972cb48ec716574685f95ace61e4a7016469a7c6c529a2c6aa5ae",
    "app/services/inquiry_service.py": "a3a667242fea049503f6898337cbb6759340322ddc934efc0d14fd0f62979e3d",
    "app/services/medicine_combination_policy.py": "74144f024f3570be895e72a8382c36a796da559eda64f224dd1d0c7ce6a501bf",
    "app/services/medicine_safety_engine.py": "763f9b7bb26bdb11c504c441df7d0f6f789c13a127d3f4c99e688260ce42eb28",
    "app/services/offline_inquiry_catalog.py": "039cbe5c540b8c29cb63d1b7bee5c0b1a59a08acc7c7eae31108b8c78f05aa7b",
    "app/services/offline_inquiry_rules.py": "6d528e946d08add9d2ec09d2af7a630538a37f6ba62dbd99d7de532f816c606c",
    "app/services/rules_engine.py": "c218e4e4d497162a7cbc00e3599661b5490b89ead1b46b5e75c5a3cb248972e6",
    "app/services/symptom_interpreter.py": "610ff284db55193c0e266082c1f739b487bc277c17ea7d3c2b026c52f8fc8b57",
    "app/services/weather_context_service.py": "b8c93d3b7251f4c50a656a543b0e31acca43f5c27ebb9f00dd9f9368f6dabc35",
}

AI_SERVICE_A270_RESPONSES_REASONING = b'''        if reasoning_effort != "off":
            payload["reasoning"] = {"effort": reasoning_effort}
'''
AI_SERVICE_FAST_RESPONSES_REASONING = b'''        payload["reasoning"] = {
            "effort": "none" if reasoning_effort == "off" else reasoning_effort
        }
'''


def normalized_lf_sha256(path: Path) -> str:
    contents = path.read_bytes()
    normalized = contents.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if path.name == "ai_service.py":
        if normalized.count(AI_SERVICE_FAST_RESPONSES_REASONING) != 1:
            raise AssertionError(
                "ai_service.py must contain exactly one reviewed Responses speed patch"
            )
        normalized = normalized.replace(
            AI_SERVICE_FAST_RESPONSES_REASONING,
            AI_SERVICE_A270_RESPONSES_REASONING,
        )
    return hashlib.sha256(normalized).hexdigest()


class InquiryA270FreezeContractTest(unittest.TestCase):
    """Freeze the AI decision chain at a27057c, independent of Git metadata.

    Persona generation, vitals provenance, candidate retrieval, dispense
    execution, and inventory confirmation are production-policy boundaries and
    are deliberately outside this generative decision freeze. The sole
    normalized transport delta sends the
    provider-documented Responses ``reasoning.effort=none`` when the unchanged
    decision chain requests non-thinking mode.
    """

    def test_ai_decision_files_match_a27057c_except_reviewed_speed_transport_patch(self) -> None:
        mismatches = []
        for relative_path, expected_sha256 in AI_DECISION_SHA256_AT_A27057C.items():
            actual_sha256 = normalized_lf_sha256(BACKEND_ROOT / relative_path)
            if actual_sha256 != expected_sha256:
                mismatches.append(
                    f"{relative_path}: expected {expected_sha256}, got {actual_sha256}"
                )

        self.assertEqual([], mismatches, "\n" + "\n".join(mismatches))


if __name__ == "__main__":
    unittest.main()
