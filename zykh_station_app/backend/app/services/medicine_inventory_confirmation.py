from __future__ import annotations

import hashlib
import json

from .. import db
from ..repositories.sync_repository import SyncRepository
from ..schemas.medicine import (
    MedicineInventoryConfirmationRequest,
    MedicineInventoryConfirmationResponse,
)


class MedicineInventoryConfirmationNotFoundError(ValueError):
    pass


class MedicineInventoryConfirmationConflictError(ValueError):
    pass


class MedicineInventoryConfirmationModule:
    """Reconcile the physical remainder after one successful cabinet action."""

    def confirm(
        self,
        medicine_id: str,
        request: MedicineInventoryConfirmationRequest,
    ) -> MedicineInventoryConfirmationResponse:
        normalized_medicine_id = medicine_id.strip()
        payload = {
            "medicine_id": normalized_medicine_id,
            "dispense_record_id": request.dispense_record_id.strip(),
            "observation": request.observation,
        }
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        db.init_db()
        replayed = False
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT request_payload_digest, medicine_id, dispense_record_id, observation,
                       inventory_state, stock_after, confirmed_at
                FROM medicine_inventory_confirmations WHERE request_id=?
                """,
                (request.request_id.strip(),),
            ).fetchone()
            if existing is not None:
                if existing["request_payload_digest"] != digest:
                    raise MedicineInventoryConfirmationConflictError(
                        "同一库存确认请求不能修改药品、取药记录或确认结果。"
                    )
                replayed = True
                result = dict(existing)
            else:
                medicine = conn.execute(
                    """
                    SELECT id, stock, inventory_state, last_inventory_dispense_record_id
                    FROM medicines WHERE id=?
                    """,
                    (normalized_medicine_id,),
                ).fetchone()
                if medicine is None:
                    raise MedicineInventoryConfirmationNotFoundError("未找到该药品。")
                dispense = conn.execute(
                    """
                    SELECT id, medicine_id, dry_run, qsm_ok
                    FROM dispense_records WHERE id=?
                    """,
                    (request.dispense_record_id.strip(),),
                ).fetchone()
                if (
                    dispense is None
                    or dispense["medicine_id"] != normalized_medicine_id
                    or bool(dispense["dry_run"])
                    or not bool(dispense["qsm_ok"])
                ):
                    raise MedicineInventoryConfirmationConflictError(
                        "库存确认必须对应本药品最近一次成功的真实取药记录。"
                    )
                latest = conn.execute(
                    """
                    SELECT id FROM dispense_records
                    WHERE medicine_id=? AND dry_run=0 AND qsm_ok=1
                    ORDER BY created_at DESC, rowid DESC LIMIT 1
                    """,
                    (normalized_medicine_id,),
                ).fetchone()
                if latest is None or latest["id"] != dispense["id"]:
                    raise MedicineInventoryConfirmationConflictError(
                        "该取药记录已不是最新记录，请按当前实物重新确认。"
                    )
                used = conn.execute(
                    """
                    SELECT request_id FROM medicine_inventory_confirmations
                    WHERE dispense_record_id=?
                    """,
                    (dispense["id"],),
                ).fetchone()
                if used is not None:
                    raise MedicineInventoryConfirmationConflictError(
                        "本次取药已经完成库存确认，不能再次修改。"
                    )
                if (
                    medicine["inventory_state"] != "AVAILABLE"
                    or int(medicine["stock"]) != 1
                    or medicine["last_inventory_dispense_record_id"] != dispense["id"]
                ):
                    raise MedicineInventoryConfirmationConflictError(
                        "该库存观察已失效，请以当前库存记录和实物为准。"
                    )
                confirmed_at = db.now_text()
                if request.observation == "HAS_REMAINING":
                    stock_after = max(int(medicine["stock"]), 1)
                    inventory_state = "AVAILABLE"
                    message = "已确认柜内还有药，库存状态已恢复。"
                else:
                    stock_after = 0
                    inventory_state = "DEPLETED"
                    message = "已确认药品用完，已加入补货提示。"
                conn.execute(
                    """
                    UPDATE medicines
                    SET stock=?, inventory_state=?, inventory_confirmed_at=?,
                        last_inventory_request_id=?, last_inventory_dispense_record_id=?,
                        inventory_revision=inventory_revision+1,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        stock_after,
                        inventory_state,
                        confirmed_at,
                        request.request_id.strip(),
                        dispense["id"],
                        confirmed_at,
                        normalized_medicine_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO medicine_inventory_confirmations(
                      request_id, request_payload_digest, medicine_id, dispense_record_id,
                      observation, inventory_state, stock_after, confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.request_id.strip(),
                        digest,
                        normalized_medicine_id,
                        dispense["id"],
                        request.observation,
                        inventory_state,
                        stock_after,
                        confirmed_at,
                    ),
                )
                result = {
                    "medicine_id": normalized_medicine_id,
                    "dispense_record_id": dispense["id"],
                    "observation": request.observation,
                    "inventory_state": inventory_state,
                    "stock_after": stock_after,
                    "confirmed_at": confirmed_at,
                }
        if not replayed:
            SyncRepository().mark_pending()
        message = (
            "已确认柜内还有药，库存状态已恢复。"
            if result["observation"] == "HAS_REMAINING"
            else "已确认药品用完，已加入补货提示。"
        )
        return MedicineInventoryConfirmationResponse(
            replayed=replayed,
            medicine_id=result["medicine_id"],
            dispense_record_id=result["dispense_record_id"],
            observation=result["observation"],
            stock=int(result["stock_after"]),
            inventory_state=result["inventory_state"],
            inventory_confirmed_at=result["confirmed_at"],
            message=message,
        )
