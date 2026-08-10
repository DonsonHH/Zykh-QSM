from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from typing import Protocol
from uuid import uuid4

from ..repositories.identity_assertion_repository import IdentityAssertionRepository
from ..repositories.manual_medication_access_repository import (
    ManualMedicationAccessRepository,
    ManualMedicationPersonSnapshot,
    SafetyCheckSnapshot,
    StoredSafetyCheck,
)
from ..repositories.medicine_repository import MedicineRepository
from ..schemas.manual_medication_access import (
    AssessManualMedicationCommand,
    ConfirmManualMedicationCommand,
    ManualDispenseExecutionCommand,
    ManualDispenseExecutionResult,
    ManualMedicationAssessment,
    ManualMedicationOutcome,
)
from ..schemas.medicine import Medicine
from .medicine_knowledge_repository import MedicineKnowledgeRepository
from .dispense_service import DispenseError


_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
MANUAL_MEDICATION_RULESET_VERSION = "manual-medication-safety-v2"


class ManualDispenseAdapter(Protocol):
    def confirm_manual(
        self,
        command: ManualDispenseExecutionCommand,
    ) -> ManualDispenseExecutionResult: ...


class ManualMedicationAccessModule:
    """Deep module for deterministic person-medicine checks and one-time dispense."""

    def __init__(
        self,
        *,
        repository: ManualMedicationAccessRepository | None = None,
        identity_assertions: IdentityAssertionRepository | None = None,
        medicine_repository: MedicineRepository | None = None,
        dispense_adapter: ManualDispenseAdapter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or ManualMedicationAccessRepository()
        self.identity_assertions = identity_assertions or IdentityAssertionRepository()
        self.medicine_repository = medicine_repository or MedicineRepository()
        self.dispense_adapter = dispense_adapter
        self._clock = clock or datetime.now

    def assess(
        self,
        command: AssessManualMedicationCommand,
    ) -> ManualMedicationAssessment:
        payload_digest = self._payload_digest(command)
        replay = self.repository.get_replay(
            request_id=command.request_id,
            request_payload_digest=payload_digest,
        )
        if replay is not None:
            return replay

        now = self._clock()
        person = self.repository.get_person(command.service_user_id)
        medicine = self.medicine_repository.get_by_id(command.medicine_id)
        assertion = self.identity_assertions.get_valid(
            command.verification_assertion_id,
            service_user_id=command.service_user_id,
            verification_method=command.verification_method,
        )
        current_fingerprint = (
            MedicineRepository.review_fingerprint(medicine) if medicine is not None else ""
        )
        check_status, reason_codes, message = self._assess_current_state(
            command=command,
            person=person,
            medicine=medicine,
            identity_assertion_valid=assertion is not None,
            current_fingerprint=current_fingerprint,
        )
        expires_at = (
            (now + timedelta(seconds=90)).strftime(_TIMESTAMP_FORMAT)
            if check_status == "PASSED"
            else ""
        )
        assessment = ManualMedicationAssessment(
            check_id=f"safety-check-{uuid4().hex}",
            check_status=check_status,
            reason_codes=reason_codes,
            message=message,
            expires_at=expires_at,
            dispense_status="NOT_STARTED",
        )
        snapshot = SafetyCheckSnapshot(
            request_id=command.request_id,
            service_user_id=command.service_user_id,
            service_user_name=person.name if person else "未登记人物",
            persona_generation=person.persona_generation if person else "",
            safety_profile_revision=person.safety_profile_revision if person else 0,
            person_safety_fingerprint=person.safety_fingerprint() if person else "",
            verification_method=command.verification_method,
            verification_assertion_id=command.verification_assertion_id,
            medicine_id=command.medicine_id,
            medicine_name=medicine.name if medicine else "未找到药品",
            slot=command.slot,
            hardware_slot=int(medicine.hardware_slot or 0) if medicine else 0,
            stock=int(medicine.stock) if medicine else -1,
            review_fingerprint=current_fingerprint,
            ruleset_version=MANUAL_MEDICATION_RULESET_VERSION,
        )
        return self.repository.save_assessment(
            snapshot=snapshot,
            request_payload_digest=payload_digest,
            assessment=assessment,
            created_at=now.strftime(_TIMESTAMP_FORMAT),
        )

    def confirm(
        self,
        command: ConfirmManualMedicationCommand,
    ) -> ManualMedicationOutcome:
        payload_digest = self._payload_digest(command)
        replay = self.repository.get_confirm_replay(
            request_id=command.request_id,
            request_payload_digest=payload_digest,
        )
        if replay is not None:
            return self._with_inventory_confirmation_state(replay)
        if command.confirmed_safety_notice is not True:
            raise ValueError("请先阅读并确认药品说明与安全提示。")
        if self.dispense_adapter is None:
            from .manual_dispense_adapter import DispenseServiceManualAdapter

            self.dispense_adapter = DispenseServiceManualAdapter()

        check = self.repository.get_check(command.safety_check_id)
        if check is None:
            raise ValueError("安全核查记录不存在。")
        if check.check_status != "PASSED":
            raise ValueError("只有核查通过的记录才能继续取药。")
        now = self._clock()
        now_text = now.strftime(_TIMESTAMP_FORMAT)
        if not check.expires_at or check.expires_at <= now_text:
            raise ValueError("该安全核查已过期，请重新确认身份并核查。")
        if check.consumed_at:
            replay = self.repository.get_confirm_replay(
                request_id=command.request_id,
                request_payload_digest=payload_digest,
            )
            if replay is not None:
                return self._with_inventory_confirmation_state(replay)
            raise ValueError("该安全核查已被使用，请重新确认身份并核查。")

        person = self.repository.get_person(check.service_user_id)
        identity_assertion_valid = self.identity_assertions.get_valid(
            check.verification_assertion_id,
            service_user_id=check.service_user_id,
            verification_method=check.verification_method,
        ) is not None
        medicine = self.medicine_repository.get_by_id(check.medicine_id)
        final_recheck_failure = self._evaluate_final_recheck(
            check=check,
            person=person,
            medicine=medicine,
            identity_assertion_valid=identity_assertion_valid,
        )
        if final_recheck_failure is not None:
            check_status, reason_codes, message = final_recheck_failure
            outcome = self.repository.invalidate_confirm_before_qsm(
                check_id=check.check_id,
                request_id=command.request_id,
                request_payload_digest=payload_digest,
                check_status=check_status,
                reason_codes=reason_codes,
                message=message,
                completed_at=now_text,
            )
            raise ValueError(outcome.message)
        assert person is not None
        assert medicine is not None

        qsm_operation_id = f"manual-dispense-{uuid4().hex}"
        should_execute = self.repository.begin_confirm(
            request_id=command.request_id,
            request_payload_digest=payload_digest,
            check_id=check.check_id,
            qsm_operation_id=qsm_operation_id,
            consumed_at=now_text,
        )
        if not should_execute:
            replay = self.repository.get_confirm_replay(
                request_id=command.request_id,
                request_payload_digest=payload_digest,
            )
            if replay is None:
                raise RuntimeError("取药确认幂等状态不完整，请勿自动重试。")
            return self._with_inventory_confirmation_state(replay)
        execution = ManualDispenseExecutionCommand(
            qsm_operation_id=qsm_operation_id,
            medicine_id=medicine.id,
            medicine_name=medicine.name,
            slot=medicine.slot,
            quantity=1,
            service_user_id=person.service_user_id,
            service_user_name=person.name,
            verification_method=check.verification_method,
            verification_assertion_id=check.verification_assertion_id,
            expected_persona_generation=check.persona_generation,
            expected_safety_profile_revision=check.safety_profile_revision,
            expected_person_safety_fingerprint=check.person_safety_fingerprint,
            expected_review_fingerprint=check.review_fingerprint,
            expected_hardware_slot=check.hardware_slot,
            expected_stock=check.stock,
            expected_expire_date=medicine.expire_date,
        )
        try:
            result = self.dispense_adapter.confirm_manual(execution)
        except DispenseError as exc:
            check_status, reason_codes, message = self._classify_final_recheck_failure(
                check=check,
                fallback_message=exc.message,
            )
            outcome = self.repository.invalidate_confirm_before_qsm(
                check_id=check.check_id,
                request_id=command.request_id,
                request_payload_digest=payload_digest,
                check_status=check_status,
                reason_codes=reason_codes,
                message=message,
                completed_at=self._clock().strftime(_TIMESTAMP_FORMAT),
            )
            raise ValueError(outcome.message)
        except Exception:
            return self.repository.complete_confirm(
                check_id=check.check_id,
                dispense_status="RESULT_UNKNOWN",
                message="柜门结果待现场确认，请勿自动重试。",
                dispense_record_id="",
                completed_at=self._clock().strftime(_TIMESTAMP_FORMAT),
            )
        return self._with_inventory_confirmation_state(
            self.repository.complete_confirm(
                check_id=check.check_id,
                dispense_status=result.dispense_status,
                message=result.message,
                dispense_record_id=result.dispense_record_id,
                completed_at=self._clock().strftime(_TIMESTAMP_FORMAT),
            )
        )

    def _with_inventory_confirmation_state(
        self,
        outcome: ManualMedicationOutcome,
    ) -> ManualMedicationOutcome:
        return outcome.model_copy(
            update={
                "inventory_confirmation_required": (
                    outcome.ok
                    and self.medicine_repository.inventory_confirmation_required(
                        outcome.dispense_record_id
                    )
                )
            }
        )

    def _classify_final_recheck_failure(
        self,
        *,
        check: StoredSafetyCheck,
        fallback_message: str,
    ) -> tuple[str, list[str], str]:
        person = self.repository.get_person(check.service_user_id)
        medicine = self.medicine_repository.get_by_id(check.medicine_id)
        identity_assertion_valid = self.identity_assertions.get_valid(
            check.verification_assertion_id,
            service_user_id=check.service_user_id,
            verification_method=check.verification_method,
        ) is not None
        failure = self._evaluate_final_recheck(
            check=check,
            person=person,
            medicine=medicine,
            identity_assertion_valid=identity_assertion_valid,
        )
        if failure is not None:
            return failure
        return (
            "CHECK_FAILED",
            [self._fallback_precondition_reason(fallback_message)],
            f"{fallback_message.rstrip('。')}；本次柜门未打开。",
        )

    def _evaluate_final_recheck(
        self,
        *,
        check: StoredSafetyCheck,
        person: ManualMedicationPersonSnapshot | None,
        medicine: Medicine | None,
        identity_assertion_valid: bool,
    ) -> tuple[str, list[str], str] | None:
        current_fingerprint = (
            MedicineRepository.review_fingerprint(medicine) if medicine is not None else ""
        )
        current_status, reason_codes, message = self._assess_current_state(
            command=AssessManualMedicationCommand(
                request_id="final-recheck",
                medicine_id=check.medicine_id,
                slot=check.slot,
                service_user_id=check.service_user_id,
                verification_method=check.verification_method,
                verification_assertion_id=check.verification_assertion_id,
                expected_review_fingerprint=check.review_fingerprint,
            ),
            person=person,
            medicine=medicine,
            identity_assertion_valid=identity_assertion_valid,
            current_fingerprint=current_fingerprint,
        )
        if current_status != "PASSED":
            return current_status, reason_codes, message
        if (
            person is None
            or person.persona_generation != check.persona_generation
            or person.safety_profile_revision != check.safety_profile_revision
            or person.safety_fingerprint() != check.person_safety_fingerprint
        ):
            return (
                "CHECK_FAILED",
                ["PROFILE_GENERATION_MISMATCH"],
                "人物资料已经更新，请重新确认身份并核查；本次柜门未打开。",
            )
        if (
            medicine is None
            or medicine.slot != check.slot
            or int(medicine.hardware_slot or 0) != check.hardware_slot
            or medicine.stock != check.stock
            or current_fingerprint != check.review_fingerprint
        ):
            if medicine is not None and medicine.stock <= 0:
                reason_code = "OUT_OF_STOCK"
                snapshot_message = "当前库存不足，请重新核查；本次柜门未打开。"
            elif medicine is not None and medicine.stock != check.stock:
                reason_code = "MEDICINE_DATA_UNREVIEWED"
                snapshot_message = "药品库存记录已经变化，请重新核查；本次柜门未打开。"
            elif medicine is not None and int(medicine.hardware_slot or 0) != check.hardware_slot:
                reason_code = "MEDICINE_DATA_UNREVIEWED"
                snapshot_message = "药品仓位映射已经变化，请重新核查；本次柜门未打开。"
            else:
                reason_code = "MEDICINE_DATA_UNREVIEWED"
                snapshot_message = "药品身份或安全资料已经变化，请重新核查；本次柜门未打开。"
            return (
                "CHECK_FAILED",
                [reason_code],
                snapshot_message,
            )
        return None

    @staticmethod
    def _fallback_precondition_reason(message: str) -> str:
        if "库存" in message:
            return "OUT_OF_STOCK"
        if "包装" in message:
            return "PACKAGE_UNVERIFIED"
        if "人物" in message or "身份" in message:
            return "PROFILE_GENERATION_MISMATCH"
        return "MEDICINE_DATA_UNREVIEWED"

    def _assess_current_state(
        self,
        *,
        command: AssessManualMedicationCommand,
        person: ManualMedicationPersonSnapshot | None,
        medicine: Medicine | None,
        identity_assertion_valid: bool,
        current_fingerprint: str,
    ) -> tuple[str, list[str], str]:
        if (
            not identity_assertion_valid
            or person is None
            or person.archived
            or not person.persona_generation.strip()
        ):
            return (
                "CHECK_FAILED",
                ["PROFILE_UNAVAILABLE"],
                "未找到可用于核查的个人健康档案，本次柜门未打开。",
            )
        profile_complete = (
            self._has_auditable_medical_history(person.medical_conditions)
            and self._has_auditable_current_medications(person.current_medications)
            and self._has_auditable_allergy_conclusion(
                person.allergy_facts,
                person.legacy_allergies,
            )
        )
        if medicine is None or medicine.slot != command.slot:
            return (
                "CHECK_FAILED",
                ["MEDICINE_DATA_UNREVIEWED"],
                "药品身份或仓位资料不完整，本次柜门未打开。",
            )
        if current_fingerprint != command.expected_review_fingerprint:
            return (
                "CHECK_FAILED",
                ["MEDICINE_DATA_UNREVIEWED"],
                "药品身份或安全资料已经变化，请重新核对；本次柜门未打开。",
            )
        if not medicine.package_verified:
            return (
                "CHECK_FAILED",
                ["PACKAGE_UNVERIFIED"],
                "该仓位包装信息尚未核验，本次柜门未打开。",
            )
        if (
            medicine.safety_review_status != "reviewed"
            or not medicine.safety_reviewed_by.strip()
            or not medicine.safety_reviewed_at.strip()
            or medicine.guidance_source == "pending"
        ):
            return (
                "CHECK_FAILED",
                ["MEDICINE_DATA_UNREVIEWED"],
                "该药品安全资料尚未完成核验，本次柜门未打开。",
            )
        if not self._has_known_expiry(medicine.expire_date):
            return (
                "CHECK_FAILED",
                ["MEDICINE_DATA_UNREVIEWED"],
                "该药品有效期尚未完成核验，本次柜门未打开。",
            )
        if MedicineKnowledgeRepository.is_expired(medicine.expire_date):
            return (
                "BLOCKED",
                ["MEDICINE_EXPIRED"],
                f"{medicine.name}已过有效期，本次已阻止取药，柜门未打开。",
            )
        if medicine.stock <= 0:
            return (
                "CHECK_FAILED",
                ["OUT_OF_STOCK"],
                "当前库存不足，本次柜门未打开。",
            )

        block_reason_codes: list[str] = []
        block_messages: list[str] = []
        allergy_label = self._allergy_conflict(person, medicine)
        if allergy_label:
            block_reason_codes.append("ALLERGY_CONFLICT")
            block_messages.append(f"已登记过敏“{allergy_label}”与{medicine.name}冲突")

        condition_label = self._condition_conflict(person, medicine)
        if condition_label:
            block_reason_codes.append("CONDITION_CONTRAINDICATION")
            block_messages.append(f"已登记病史“{condition_label}”与{medicine.name}禁忌冲突")

        duplicate_ingredient = self._duplicate_active_ingredient(person, medicine)
        if duplicate_ingredient:
            block_reason_codes.append("DUPLICATE_ACTIVE_INGREDIENT")
            block_messages.append(f"与已登记当前用药存在重复成分“{duplicate_ingredient}”")

        interaction_message = self._reviewed_interaction(person, medicine)
        if interaction_message:
            block_reason_codes.append("REVIEWED_INTERACTION")
            block_messages.append(interaction_message.rstrip("，。；"))

        if block_reason_codes:
            return (
                "BLOCKED",
                block_reason_codes,
                f"{'；'.join(block_messages)}；本次已阻止取药，柜门未打开。",
            )

        if not profile_complete:
            return (
                "CHECK_FAILED",
                ["PROFILE_UNAVAILABLE"],
                "个人病史、当前用药或过敏结论不完整，本次柜门未打开。",
            )

        return (
            "PASSED",
            [],
            "未发现已登记冲突，请核对药品说明后继续。",
        )

    @staticmethod
    def _has_auditable_medical_history(
        conditions: tuple[dict[str, object], ...],
    ) -> bool:
        return bool(conditions) and all(
            str(condition.get("concept_code") or "").strip()
            and str(condition.get("status") or "").strip().lower()
            in {"present", "absent"}
            for condition in conditions
        )

    @staticmethod
    def _has_auditable_current_medications(
        medications: tuple[dict[str, object], ...],
    ) -> bool:
        if not medications:
            return False
        for medication in medications:
            status = str(medication.get("status") or "").strip().lower()
            if status == "absent":
                conclusion = str(
                    medication.get("display_text")
                    or medication.get("medicine_name")
                    or ""
                ).strip()
                if not conclusion:
                    return False
                continue
            if status not in {"", "present", "current", "active"}:
                return False
            ingredients = medication.get("active_ingredients")
            if not isinstance(ingredients, list) or not any(
                str(ingredient).strip() for ingredient in ingredients
            ):
                return False
        return True

    @staticmethod
    def _has_auditable_allergy_conclusion(
        allergy_facts: tuple[dict[str, object], ...],
        legacy_allergies: str,
    ) -> bool:
        if not allergy_facts:
            legacy_conclusion = legacy_allergies.strip()
            if not legacy_conclusion:
                return False
            normalized = "".join(legacy_conclusion.split()).strip("，。；、,.!?！？")
            return normalized.lower() not in {
                "未知",
                "待补充",
                "不清楚",
                "不知道",
                "未确认",
                "待确认",
                "无资料",
                "无记录",
                "unknown",
                "pending",
                "pendingconfirmation",
                "unconfirmed",
                "unclear",
                "nodata",
                "norecord",
            }
        return all(
            str(fact.get("status") or "").strip().lower()
            in {"present", "absent"}
            and bool(
                str(
                    fact.get("display_text")
                    or fact.get("substance")
                    or ""
                ).strip()
            )
            for fact in allergy_facts
        )

    @staticmethod
    def _condition_conflict(
        person: ManualMedicationPersonSnapshot,
        medicine: Medicine,
    ) -> str:
        contraindication_codes = {
            str(item.get("concept_code") or "").strip()
            for item in medicine.structured_contraindications
            if str(item.get("concept_code") or "").strip()
        }
        for condition in person.medical_conditions:
            if str(condition.get("status") or "present").strip().lower() != "present":
                continue
            concept_code = str(condition.get("concept_code") or "").strip()
            if concept_code and concept_code in contraindication_codes:
                return str(condition.get("display_text") or concept_code).strip()
        return ""

    @staticmethod
    def _allergy_conflict(
        person: ManualMedicationPersonSnapshot,
        medicine: Medicine,
    ) -> str:
        present = [
            item
            for item in person.allergy_facts
            if str(item.get("status") or "present").strip().lower() == "present"
        ]
        allergy_text = "；".join(
            item
            for item in (
                person.legacy_allergies.strip(),
                *(
                    str(value.get("display_text") or value.get("substance") or "").strip()
                    for value in present
                ),
            )
            if item
        )
        if allergy_text and MedicineKnowledgeRepository.has_allergy_conflict(
            medicine,
            allergy_text,
        ):
            return allergy_text
        return ""

    @classmethod
    def _duplicate_active_ingredient(
        cls,
        person: ManualMedicationPersonSnapshot,
        medicine: Medicine,
    ) -> str:
        selected = {
            cls._compact(value): value
            for value in medicine.active_ingredients
            if cls._compact(value)
        }
        for current in person.current_medications:
            ingredients = current.get("active_ingredients")
            if not isinstance(ingredients, list):
                continue
            for ingredient in ingredients:
                compact = cls._compact(ingredient)
                if compact and compact in selected:
                    return selected[compact]
        return ""

    def _reviewed_interaction(
        self,
        person: ManualMedicationPersonSnapshot,
        medicine: Medicine,
    ) -> str:
        selected = {
            self._compact(value)
            for value in medicine.active_ingredients
            if self._compact(value)
        }
        current = {
            self._compact(value)
            for item in person.current_medications
            for value in (
                item.get("active_ingredients")
                if isinstance(item.get("active_ingredients"), list)
                else []
            )
            if self._compact(value)
        }
        if not selected or not current:
            return ""
        for rule in self.medicine_repository.list_reviewed_ingredient_conflicts():
            left = self._compact(rule.left_ingredient)
            right = self._compact(rule.right_ingredient)
            if (left in selected and right in current) or (
                right in selected and left in current
            ):
                return rule.message.strip() or (
                    f"已登记当前用药成分与{medicine.name}命中已审核相互作用规则"
                )
        return ""

    @staticmethod
    def _compact(value: object) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())

    @staticmethod
    def _has_known_expiry(value: object) -> bool:
        match = re.fullmatch(
            r"(\d{4})[-./](\d{1,2})(?:[-./](\d{1,2}))?",
            str(value or "").strip(),
        )
        if not match:
            return False
        try:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3) or 1)
            date(year, month, day)
        except ValueError:
            return False
        return True

    @staticmethod
    def _payload_digest(
        command: AssessManualMedicationCommand | ConfirmManualMedicationCommand,
    ) -> str:
        encoded = json.dumps(
            command.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
