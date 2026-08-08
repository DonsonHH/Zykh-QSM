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
from app.services.medicine_knowledge_repository import MedicineKnowledgeRepository  # noqa: E402
from app.services.offline_inquiry_rules import OfflineInquiryRules  # noqa: E402
from app.services.records_service import RecordsService  # noqa: E402


class MedicationDemoScenariosTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "medication-scenarios.db"
        self.db_patch = patch("app.db.settings", SimpleNamespace(db_path=self.db_path))
        self.db_patch.start()
        db.init_db()
        self.rules = OfflineInquiryRules()
        self.repository = MedicineRepository()
        self.all_candidates = [
            item.model_dump(mode="json")
            for item in self.repository.list_all()
        ]

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _extract(self, transcript: str) -> dict:
        return self.rules.extract(
            transcript,
            {"conversation_turns": 1, "conversation": []},
            {},
        )

    def _rank(self, case_summary: str | dict, candidates: list[dict] | None = None) -> dict:
        context = (
            {
                "case_summary": case_summary.get("case_summary", ""),
                "observations": case_summary.get("observations", []),
            }
            if isinstance(case_summary, dict)
            else {"case_summary": case_summary, "observations": []}
        )
        return self.rules.rank(
            context,
            candidates if candidates is not None else self.all_candidates,
        )

    def test_scenario_1_daily_plan_contains_hypertension_and_nutrition_items(self) -> None:
        plans = RecordsService().list_today_plans(due_only=False)
        zhangsan_plan_ids = {
            item.medicine_id
            for item in plans
            if item.service_user_id == "zhangsan"
        }

        self.assertIn("slot-21-amlodipine", zhangsan_plan_ids)
        self.assertIn("slot-02-centrum", zhangsan_plan_ids)

    def test_scenarios_2_and_3_keep_symptom_drugs_as_choices_not_default_combinations(self) -> None:
        mild_cold = self._extract("受凉后鼻塞、流清鼻涕、头痛和轻微咳嗽，没有明显高热")
        cold_options = self._rank(mild_cold["case_summary"])["options"]
        significant_cough = self._extract("感冒后咳嗽比较明显，夜里一直咳")
        cough_options = self._rank(significant_cough["case_summary"])["options"]
        throat_options = self._rank("咽喉不适")["options"]

        self.assertEqual(mild_cold["case_summary"], "感冒样不适")
        self.assertEqual([item["medicine_ids"] for item in cold_options], [["slot-01-fufang-ganmaoling"]])
        self.assertEqual(significant_cough["case_summary"], "咳嗽咳痰不适")
        self.assertEqual(cough_options[0]["medicine_ids"], ["slot-05-nin-jiom-pei-pa-koa"])
        self.assertEqual(
            [item["medicine_ids"] for item in throat_options],
            [["slot-07-yinhuang"], ["slot-11-guilin-xiguashuang"]],
        )

    def test_scenarios_4_and_5_recognize_doctor_gated_drugs_without_auto_unlocking_them(self) -> None:
        flu = self._extract("突然高热、头痛、肌肉酸痛和明显乏力，远程医生判断为流感")
        bacterial = self._extract("持续发热、咳嗽加重，对症处理后没改善，医生怀疑细菌感染")

        self.assertEqual(flu["case_summary"], "流感样不适需医生核验")
        self.assertEqual(
            self._rank(flu)["options"][0]["medicine_ids"],
            ["slot-13-ibuprofen", "slot-14-oseltamivir"],
        )
        self.assertEqual(bacterial["case_summary"], "疑似细菌感染需医生核验")
        self.assertEqual(
            [item["medicine_ids"] for item in self._rank(bacterial)["options"]],
            [["slot-04-amoxicillin"], ["slot-13-ibuprofen"]],
        )
        bacterial_without_marked_fever = self._extract("咳嗽加重，对症处理后没改善，医生怀疑细菌感染")
        self.assertEqual(
            [item["medicine_ids"] for item in self._rank(bacterial_without_marked_fever)["options"]],
            [["slot-04-amoxicillin"]],
        )
        rejected_flu = self._extract("医生判断不是流感，只是普通感冒")
        rejected_ids = {
            medicine_id
            for option in self._rank(rejected_flu)["options"]
            for medicine_id in option["medicine_ids"]
        }
        self.assertNotIn("slot-14-oseltamivir", rejected_ids)
        self.assertNotIn("slot-13-ibuprofen", rejected_ids)
        normalized_rejection = self.rules.rank(
            {
                "case_summary": "流感样不适需医生核验",
                "observations": [{"evidence": "医生判断不是流感"}],
            },
            self.all_candidates,
        )
        self.assertEqual(normalized_rejection["options"], [])

        safe_ids = {
            item.id
            for item in MedicineKnowledgeRepository(self.repository).safe_candidate_pool("")
        }
        # Slot 13 has the new online identity but remains outside the AI pool
        # until its dynamic safety metadata receives controlled review.
        self.assertNotIn("slot-13-ibuprofen", safe_ids)
        self.assertNotIn("slot-14-oseltamivir", safe_ids)
        self.assertNotIn("slot-04-amoxicillin", safe_ids)

    def test_scenarios_6_to_8_cover_diarrhea_food_related_discomfort_and_constipation(self) -> None:
        diarrhea = self._extract("饮食不洁后急性腹泻，没有便血、持续高热或剧烈腹痛")
        food_related = self._extract("进食生冷或油腻食物后恶心、腹胀、胃部不适并且反酸")
        constipation = self._extract("老人近期饮水少、活动量减少，排便困难")

        self.assertEqual(
            self._rank(diarrhea)["options"][0]["medicine_ids"],
            ["slot-03-diosmectite", "slot-09-bifid-triple"],
        )
        diarrhea_red_flag = self._extract("急性腹泻而且便血，肚子剧烈疼痛")
        self.assertEqual(self._rank(diarrhea_red_flag)["options"], [])
        changed_red_flag = self._extract("之前没有便血；现在便血")
        self.assertEqual(self._rank(changed_red_flag)["options"], [])
        self.assertEqual(food_related["case_summary"], "饮食相关胃肠不适")
        self.assertEqual(
            [item["medicine_ids"] for item in self._rank(food_related["case_summary"])["options"]],
            [["slot-08-huoxiang-zhengqi"], ["slot-12-hydrotalcite"]],
        )
        self.assertEqual(
            self._rank(constipation["case_summary"])["options"][0]["medicine_ids"],
            ["slot-06-lactulose"],
        )

    def test_scenario_9_combines_nasal_roles_but_keeps_prescription_item_gated(self) -> None:
        rhinitis = self._extract("接触花粉和灰尘后连续打喷嚏、流清鼻涕并且鼻塞")
        planned = self._rank(rhinitis["case_summary"])["options"][0]["medicine_ids"]
        safe_candidates = [
            item.model_dump(mode="json")
            for item in MedicineKnowledgeRepository(self.repository).safe_candidate_pool("")
        ]
        available = self._rank(rhinitis["case_summary"], safe_candidates)["options"]

        self.assertEqual(planned, ["slot-23-desloratadine", "slot-18-budesonide-nasal"])
        self.assertEqual(available[0]["medicine_ids"], ["slot-18-budesonide-nasal"])

        directed_candidates = MedicineKnowledgeRepository(self.repository).safe_candidate_pool(
            "",
            existing_direction_ids={"slot-23-desloratadine"},
        )
        directed_by_id = {item.id: item for item in directed_candidates}
        directed_options = self._rank(
            rhinitis["case_summary"],
            [item.model_dump(mode="json") for item in directed_candidates],
        )["options"]
        self.assertTrue(directed_by_id["slot-23-desloratadine"].requires_existing_direction)
        self.assertEqual(
            directed_options[0]["medicine_ids"],
            ["slot-23-desloratadine", "slot-18-budesonide-nasal"],
        )

    def test_scenario_10_handles_wound_cover_choice_and_intact_skin_sprain_care(self) -> None:
        injury = self._extract("在山路跌倒，手部擦伤，同时有轻度脚踝扭伤，但脚踝皮肤完整")
        options = self._rank(injury)["options"]

        self.assertEqual(injury["case_summary"], "擦伤伴轻度扭伤")
        self.assertEqual(
            [item["medicine_ids"] for item in options],
            [
                ["slot-17-iodophor", "slot-22-cotton-swab", "slot-20-bandage", "slot-19-ketoprofen-gel"],
                ["slot-17-iodophor", "slot-22-cotton-swab", "slot-10-gauze", "slot-19-ketoprofen-gel"],
            ],
        )
        broken_skin = self._extract("山路跌倒手部擦伤，同时脚踝扭伤处也破皮")
        broken_options = self._rank(broken_skin)["options"]
        self.assertTrue(broken_options)
        self.assertTrue(all(
            "slot-19-ketoprofen-gel" not in option["medicine_ids"]
            for option in broken_options
        ))

    def test_scenario_11_distinguishes_bacterial_and_fungal_skin_flows(self) -> None:
        bacterial = self._extract("皮肤有脓疱，远程医生看照片后判断为细菌感染")
        fungal = self._extract("脚趾缝脱皮发痒，远程医生看照片后判断为真菌感染")

        self.assertEqual(
            self._rank(bacterial)["options"][0]["medicine_ids"],
            ["slot-15-mupirocin"],
        )
        self.assertEqual(
            self._rank(fungal)["options"][0]["medicine_ids"],
            ["slot-16-ketoconazole"],
        )
        unconfirmed_fungal = self._extract("脚趾缝脱皮发痒，像是真菌感染")
        self.assertEqual(self._rank(unconfirmed_fungal)["options"], [])
        negated_confirmation = self._extract("没有医生确认，只是怀疑真菌感染")
        self.assertEqual(self._rank(negated_confirmation)["options"], [])

        safe_ids = {
            item.id
            for item in MedicineKnowledgeRepository(self.repository).safe_candidate_pool("")
        }
        self.assertNotIn("slot-15-mupirocin", safe_ids)
        self.assertIn("slot-16-ketoconazole", safe_ids)

    def test_scenario_12_recognizes_altitude_illness_without_inventing_a_cabinet_drug(self) -> None:
        altitude = self._extract("到高海拔地区后头痛、恶心，怀疑出现高反")
        ranked = self._rank(altitude["case_summary"])

        self.assertEqual(altitude["case_summary"], "高海拔不适")
        self.assertEqual(altitude["next_action"], "ask")
        self.assertEqual(ranked["options"], [])


if __name__ == "__main__":
    unittest.main()
