from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app import db  # noqa: E402
from app.repositories.medicine_repository import MedicineRepository  # noqa: E402
from app.services.medicine_knowledge_repository import (  # noqa: E402
    MedicineKnowledgeRepository,
    MedicineSafetyContext,
)


# Each row describes an appropriate retrieval case, not an instruction to
# dispense. The later safety and ranking stages remain authoritative.
CATALOG_REACHABILITY_CASES = (
    ("slot-01-fufang-ganmaoling", "风热感冒发烧喉咙疼并且咳嗽痰黄"),
    ("slot-02-centrum", "缺乏维生素和矿物质需要营养补充"),
    ("slot-03-diosmectite", "今天开始拉肚子，水样便但能喝水"),
    ("slot-04-amoxicillin", "医生确认呼吸道细菌感染，已有阿莫西林处方"),
    ("slot-05-nin-jiom-pei-pa-koa", "咳得厉害，痰多而且嗓子干痒声音嘶哑"),
    ("slot-06-lactulose", "最近便秘排便困难"),
    ("slot-07-yinhuang", "风热后嗓子疼、咽干"),
    ("slot-08-huoxiang-zhengqi", "暑湿后肚子胀、恶心呕吐和腹泻"),
    ("slot-09-bifid-triple", "肠道菌群失调后拉肚子并且消化不良"),
    ("slot-10-gauze", "擦破皮的伤口清洁后需要纱布覆盖吸收渗液"),
    ("slot-11-guilin-xiguashuang", "口腔溃疡并有咽喉肿痛"),
    ("slot-12-hydrotalcite", "胃不舒服、反酸、烧心和饱胀"),
    ("slot-13-ibuprofen", "普通感冒发烧，伴有头疼和肌肉痛"),
    ("slot-14-oseltamivir", "远程医生判断为流感，已有奥司他韦医嘱"),
    ("slot-15-mupirocin", "医生确认毛囊炎化脓为细菌性皮肤感染，已有莫匹罗星处方"),
    ("slot-16-ketoconazole", "医生确认足癣真菌感染，脚趾脱皮发痒"),
    ("slot-17-iodophor", "擦破皮的浅表伤口需要消毒"),
    ("slot-18-budesonide-nasal", "季节性过敏性鼻炎，鼻子堵、打喷嚏和流鼻水"),
    ("slot-19-ketoprofen-gel", "脚扭了，皮肤完整但局部肌肉关节疼"),
    ("slot-20-bandage", "止血后的浅表小伤口需要创口贴覆盖"),
    ("slot-21-amlodipine", "血压高，按原来的氨氯地平长期计划服药"),
    ("slot-22-cotton-swab", "浅表伤口清洁消毒，需要棉签蘸外用消毒液"),
    ("slot-23-desloratadine", "过敏性鼻炎一直打喷嚏、流鼻水，按原来的枸地氯雷他定医嘱使用"),
)

PRESCRIPTION_DIRECTION_IDS = frozenset(
    {
        "slot-04-amoxicillin",
        "slot-14-oseltamivir",
        "slot-15-mupirocin",
        "slot-21-amlodipine",
        "slot-23-desloratadine",
    }
)


class MedicineCatalogReachabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "catalog-reachability.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.medicines = MedicineRepository()
        self.medicines.list_all()
        self.knowledge = MedicineKnowledgeRepository(self.medicines)

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _candidate_ids(
        self,
        case_text: str,
        *,
        directions: frozenset[str] = PRESCRIPTION_DIRECTION_IDS,
    ) -> list[str]:
        assessment = self.knowledge.assess_candidates(
            MedicineSafetyContext(
                relevance_text=case_text,
                existing_direction_ids=directions,
            ),
            limit=8,
        )
        return [candidate.id for candidate in assessment.candidates]

    def test_every_in_date_catalog_item_is_reachable_for_an_appropriate_case(self) -> None:
        # Isolate retrieval from expiry by representing a newly verified,
        # in-date package in this temporary database only.
        for medicine_id, _ in CATALOG_REACHABILITY_CASES:
            self.medicines.update(medicine_id, {"expire_date": "2035-12"})

        self.assertEqual(len(CATALOG_REACHABILITY_CASES), 23)
        for medicine_id, case_text in CATALOG_REACHABILITY_CASES:
            with self.subTest(medicine_id=medicine_id, case_text=case_text):
                assessment = self.knowledge.assess_candidates(
                    MedicineSafetyContext(
                        relevance_text=case_text,
                        existing_direction_ids=PRESCRIPTION_DIRECTION_IDS,
                    ),
                    limit=8,
                )
                self.assertIn(
                    medicine_id,
                    [candidate.id for candidate in assessment.candidates],
                )
                selection = self.knowledge.validate_ai_selection(
                    {
                        "options": [
                            {
                                "medicine_ids": [medicine_id],
                                "label": "当前适用选择",
                                "reason": "当前描述与受控用途相符。",
                            }
                        ]
                    },
                    assessment.candidates,
                )
                self.assertEqual(
                    [
                        medicine.id
                        for option in selection.options
                        for medicine in option.medicines
                    ],
                    [medicine_id],
                )

    def test_colloquial_symptoms_keep_more_than_one_direct_safe_choice(self) -> None:
        for case_text, expected_ids in (
            (
                "今天发烧并且头疼，没有吃过药也没有过敏",
                {"slot-01-fufang-ganmaoling", "slot-13-ibuprofen"},
            ),
            (
                "今天喉咙疼，吞咽的时候更明显",
                {"slot-07-yinhuang", "slot-11-guilin-xiguashuang"},
            ),
            (
                "今天开始拉肚子，目前可以喝水",
                {"slot-03-diosmectite", "slot-09-bifid-triple"},
            ),
            (
                "今天突然窜稀，目前可以喝水",
                {"slot-03-diosmectite", "slot-09-bifid-triple"},
            ),
        ):
            with self.subTest(case_text=case_text):
                candidates = set(self._candidate_ids(case_text, directions=frozenset()))
                self.assertTrue(expected_ids <= candidates)

    def test_controlled_spoken_cases_retrieve_the_expected_catalog_item(self) -> None:
        for case_text, medicine_id in (
            ("流鼻涕、打喷嚏、清水样鼻涕", "slot-18-budesonide-nasal"),
            (
                "流鼻涕、打喷嚏、清水样鼻涕；本次还没有用药；没有过敏",
                "slot-18-budesonide-nasal",
            ),
            ("肚子有点痛，主要是腹痛", "slot-12-hydrotalcite"),
            ("舌头上打了个泡，吃东西会疼", "slot-11-guilin-xiguashuang"),
            ("医生确认是脚气，脚趾缝脱皮很痒", "slot-16-ketoconazole"),
            ("脚扭了，皮肤完整，活动时疼", "slot-19-ketoprofen-gel"),
            (
                "肚子痛、窜稀；本次还没有用药；没有过敏",
                "slot-03-diosmectite",
            ),
        ):
            with self.subTest(case_text=case_text):
                self.assertIn(
                    medicine_id,
                    self._candidate_ids(case_text, directions=frozenset()),
                )

    def test_numbers_and_generic_case_words_do_not_create_incidental_matches(self) -> None:
        for case_text in (
            "眩晕症状；体温36.6；心率70；血氧97",
            "头晕不适；体征测量时间2026-08-10 10:06；一般症状",
            "没有头痛，也没有发热",
            "没有咳嗽，也没有发冷",
        ):
            with self.subTest(case_text=case_text):
                self.assertEqual(
                    self._candidate_ids(case_text, directions=frozenset()),
                    [],
                )

    def test_clinician_gated_rules_are_not_unlocked_by_a_guess_or_rejection(self) -> None:
        for case_text, medicine_id in (
            ("像是脚气，但没有医生确认真菌感染", "slot-16-ketoconazole"),
            ("医生判断不是流感，只是普通感冒", "slot-14-oseltamivir"),
            ("只是怀疑有细菌感染，还没有医生确认", "slot-04-amoxicillin"),
        ):
            with self.subTest(case_text=case_text):
                self.assertNotIn(medicine_id, self._candidate_ids(case_text))

    def test_cold_candidate_requires_an_unnegated_respiratory_and_chill_cluster(self) -> None:
        for case_text in (
            "不是感冒，只是空调太冷所以发冷",
            "医生说不是感冒，是低血糖时头晕手脚发冷",
            "打完疫苗后发冷，没有咳嗽鼻塞咽痛",
            "不是感冒，只是咳嗽和发冷",
            "医生说咳嗽是过敏，不是感冒；今天低血糖时发冷",
            "咳嗽已经好了，现在只是发冷",
            "医生已经排除感冒；今天咳嗽和发冷",
            "并非感冒，只是咳嗽和发冷",
            "非感冒导致，今天咳嗽和发冷",
            "感冒已经好了，现在咳嗽和发冷是过敏导致",
            "咳嗽和发冷不是同时发生",
        ):
            with self.subTest(case_text=case_text):
                self.assertNotIn(
                    "slot-01-fufang-ganmaoling",
                    self._candidate_ids(case_text, directions=frozenset()),
                )

        self.assertIn(
            "slot-01-fufang-ganmaoling",
            self._candidate_ids(
                "今天有一点咳嗽和发冷，没有呼吸困难",
                directions=frozenset(),
            ),
        )
        self.assertIn(
            "slot-01-fufang-ganmaoling",
            self._candidate_ids(
                "目前无法排除感冒，今天有一点咳嗽和发冷",
                directions=frozenset(),
            ),
        )
        for case_text in (
            "今天咳嗽而且非常怕冷",
            "今天非常咳嗽并且发冷",
        ):
            with self.subTest(case_text=case_text):
                self.assertIn(
                    "slot-01-fufang-ganmaoling",
                    self._candidate_ids(case_text, directions=frozenset()),
                )

    def test_prescription_items_still_require_an_existing_direction(self) -> None:
        for medicine_id, case_text in CATALOG_REACHABILITY_CASES:
            if medicine_id not in PRESCRIPTION_DIRECTION_IDS:
                continue
            with self.subTest(medicine_id=medicine_id):
                self.assertNotIn(
                    medicine_id,
                    self._candidate_ids(case_text, directions=frozenset()),
                )

    def test_currently_expired_package_stays_blocked_even_with_a_direction(self) -> None:
        medicine_id = "slot-15-mupirocin"
        case_text = dict(CATALOG_REACHABILITY_CASES)[medicine_id]

        self.assertNotIn(medicine_id, self._candidate_ids(case_text))


if __name__ == "__main__":
    unittest.main()
