from __future__ import annotations

from ..schemas.inquiry import (
    InquiryVitalsEvidence,
    InquiryVitalsMetric,
    InquiryVitalsRequest,
)


CORE_UNITS = {
    "temperature": "℃",
    "heart_rate": "次/分",
    "spo2": "%",
}

REFERENCE_UNITS = {
    "body_temperature": "℃",
    "blood_pressure": "mmHg",
    "respiratory_rate": "次/分",
    "hrv_sdnn": "ms",
    "hrv_rmssd": "ms",
    "rr_interval": "ms",
    "microcirculation": "",
    "fatigue": "",
    "ambient_temperature": "℃",
}

UNUSABLE_SIGNAL_QUALITIES = {
    "error",
    "failed",
    "no_finger",
    "poor_signal",
    "unavailable",
}


class VitalsEvidenceService:
    """Classifies device evidence without making a medical interpretation."""

    def build(self, request: InquiryVitalsRequest) -> InquiryVitalsEvidence:
        status = "partial" if request.partial and request.status == "complete" else request.status
        quality = request.quality.strip().lower()
        measurement_usable = status in {"complete", "partial"}
        signal_usable = (
            measurement_usable
            and request.finger_detected is not False
            and quality not in UNUSABLE_SIGNAL_QUALITIES
        )

        core: dict[str, InquiryVitalsMetric] = {}
        if request.temperature is not None:
            core["temperature"] = self._metric(
                request.temperature,
                CORE_UNITS["temperature"],
                measurement_usable,
                "measured" if measurement_usable else "unusable",
            )
        if request.heart_rate is not None:
            usable = signal_usable and request.heart_rate_frame_count != 0
            core["heart_rate"] = self._metric(
                request.heart_rate,
                CORE_UNITS["heart_rate"],
                usable,
                "measured" if usable else "signal_unreliable",
            )
        if request.spo2 is not None:
            usable = signal_usable and request.spo2_frame_count != 0
            core["spo2"] = self._metric(
                request.spo2,
                CORE_UNITS["spo2"],
                usable,
                "measured" if usable else "signal_unreliable",
            )

        reference = self._reference_metrics(request)
        core_ready = all(
            core.get(name) is not None and core[name].usable
            for name in ("temperature", "heart_rate", "spo2")
        )
        notes = [
            "额温、心率和血氧仅在本次设备质量合格时作为核心体征。",
            "指温、血压、呼吸频率和 HRV 等数据仅作为辅助参考。",
        ]
        if not core_ready:
            notes.insert(0, "本次没有取得完整且可靠的核心体征。")
        if status in {"failed", "cancelled"}:
            notes.insert(0, "本次体征测量未完成。")

        quality_payload = {
            "quality": request.quality,
            "reference_ready": request.reference_ready,
            "finger_detected": request.finger_detected,
            "sample_count": request.sample_count,
            "valid_frame_count": request.valid_frame_count,
            "contact_frame_count": request.contact_frame_count,
            "heart_rate_frame_count": request.heart_rate_frame_count,
            "spo2_frame_count": request.spo2_frame_count,
            "stabilization_extended": request.stabilization_extended,
            "partial": status == "partial",
            "source": request.source,
            "core_ready": core_ready,
        }
        return InquiryVitalsEvidence(
            measurement_session_id=request.measurement_session_id,
            measurement_status=status,
            core=core,
            reference=reference,
            quality=quality_payload,
            reliability_notes=notes,
            error_message=request.error_message,
            measured_at=request.measured_at,
        )

    @staticmethod
    def _metric(
        value: float | int | str,
        unit: str,
        usable: bool,
        quality: str,
    ) -> InquiryVitalsMetric:
        return InquiryVitalsMetric(
            value=value,
            unit=unit,
            usable=usable,
            quality=quality,
        )

    def _reference_metrics(
        self,
        request: InquiryVitalsRequest,
    ) -> dict[str, InquiryVitalsMetric]:
        reference: dict[str, InquiryVitalsMetric] = {}
        values: dict[str, float | int | str | None] = {
            "body_temperature": request.body_temperature,
            "respiratory_rate": request.respiratory_rate,
            "hrv_sdnn": request.hrv_sdnn,
            "hrv_rmssd": request.hrv_rmssd,
            "rr_interval": request.rr_interval,
            "microcirculation": request.microcirculation,
            "fatigue": request.fatigue,
            "ambient_temperature": request.ambient_temperature,
        }
        if request.systolic_pressure is not None and request.diastolic_pressure is not None:
            values["blood_pressure"] = (
                f"{request.systolic_pressure}/{request.diastolic_pressure}"
            )
        for name, value in values.items():
            if value is None:
                continue
            reference[name] = self._metric(
                value,
                REFERENCE_UNITS[name],
                True,
                "reference_only",
            )
        return reference
