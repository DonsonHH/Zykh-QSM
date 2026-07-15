from __future__ import annotations

import re
import subprocess
import threading
import time

from .. import db
from ..config import settings
from .local_ai_client import LocalAiClient
from .qsm_client import QsmClient


class NetworkService:
    _sim_signal_lock = threading.Lock()
    _sim_signal_cache: tuple[float, dict[str, object]] | None = None
    _sim_signal_ttl_seconds = 45.0

    def status(self) -> dict[str, object]:
        preferred = db.get_setting("network_mode", settings.network_preferred_mode).strip().lower() or "sim"
        interface = settings.network_sim_interface
        sim_ip = self._interface_ipv4(interface)
        default_iface = self._default_interface()
        wifi = self._wifi_status(default_iface)
        sim_route = default_iface == interface
        reachable = self._ping_target("223.5.5.5") if sim_ip else False
        qsm_network = QsmClient().get_network_status()
        qsm_at = qsm_network.get("at") if isinstance(qsm_network.get("at"), dict) else {}
        qsm_sim_present = bool(qsm_network.get("sim_present") or qsm_network.get("connected"))
        qsm_connected = bool(qsm_network.get("connected"))
        qsm_ip = str(qsm_network.get("ip") or qsm_network.get("sim_ip") or "")
        raw_csq = qsm_network.get("signal_csq", qsm_at.get("signal_csq"))
        sim_metrics = self.stable_sim_signal_metrics(raw_csq, connected=qsm_connected)
        sim_signal_data = {
            "sim_signal_csq": sim_metrics["csq"],
            "sim_signal_dbm": sim_metrics["dbm"],
            "sim_signal_percent": sim_metrics["percent"],
            "sim_signal_bars": sim_metrics["bars"],
            "sim_signal_level": sim_metrics["level"],
            "sim_signal_sample": sim_metrics["sample"],
            "sim_signal_sample_age_seconds": sim_metrics["sample_age_seconds"],
        }
        sim_connected = bool(qsm_connected or (sim_ip and (sim_route or reachable)))
        sim_present = bool(qsm_sim_present or sim_ip)
        local_ai = LocalAiClient().status()
        local_ai_ready = bool(local_ai.get("ready"))
        local_label = "离线模型" if local_ai_ready else "离线问询"
        local_ai_mode = "local_llm" if local_ai_ready else "rules_fallback"
        local_warnings = [] if local_ai_ready else ["离线模型未就绪，当前仅保留安全规则。"]

        if preferred in {"local", "offline"}:
            return {
                "ok": True,
                "mode": "local",
                "transport": "local",
                "status": "offline",
                "signal": "none",
                "label": local_label,
                "ai_mode": local_ai_mode,
                "local_ai": local_ai,
                "sim_interface": interface,
                "sim_ip": sim_ip,
                "default_interface": default_iface,
                **wifi,
                "sim_present": sim_present,
                "sim_connected": sim_connected,
                "sim_signal": str(qsm_network.get("signal") or ("good" if sim_connected else "none")),
                **sim_signal_data,
                "simulated": False,
                "warnings": ["当前手动切换到离线模式。", *local_warnings],
            }

        if wifi["wifi_connected"]:
            return {
                "ok": True,
                "mode": "wifi",
                "transport": "wifi",
                "status": "good",
                "signal": "good",
                "label": "联网正常",
                "ai_mode": "cloud",
                "local_ai": local_ai,
                "sim_interface": str(qsm_network.get("interface") or interface),
                "sim_ip": qsm_ip or sim_ip,
                "default_interface": default_iface,
                **wifi,
                "sim_present": sim_present,
                "sim_connected": sim_connected,
                "sim_signal": str(qsm_network.get("signal") or ("good" if sim_connected else "none")),
                **sim_signal_data,
                "simulated": False,
                "source": "host",
                "warnings": [] if sim_connected else ["SIM 备用链路未连通。"],
            }

        if qsm_connected:
            return {
                "ok": True,
                "mode": "sim",
                "transport": "sim",
                "status": "good",
                "signal": "good",
                "label": "SIM网络",
                "ai_mode": "cloud",
                "local_ai": local_ai,
                "sim_interface": str(qsm_network.get("interface") or interface),
                "sim_ip": qsm_ip,
                "default_interface": str(qsm_network.get("default_interface") or default_iface),
                **wifi,
                "sim_present": sim_present,
                "sim_connected": True,
                "sim_signal": str(qsm_network.get("signal") or "good"),
                **sim_signal_data,
                "simulated": False,
                "source": "qsm",
                "warnings": [],
            }

        if qsm_sim_present:
            qsm_ip = str(qsm_network.get("ip") or qsm_network.get("sim_ip") or "")
            return {
                "ok": True,
                "mode": "local",
                "transport": "local",
                "status": "offline",
                "signal": "none",
                "label": local_label,
                "ai_mode": local_ai_mode,
                "local_ai": local_ai,
                "sim_interface": str(qsm_network.get("interface") or interface),
                "sim_ip": qsm_ip,
                "default_interface": str(qsm_network.get("default_interface") or default_iface),
                **wifi,
                "sim_present": True,
                "sim_connected": False,
                "sim_signal": str(qsm_network.get("signal") or "weak"),
                **sim_signal_data,
                "simulated": False,
                "source": "qsm",
                "warnings": ["外设已检测到 SIM 模块，但数据网络未连通。", *local_warnings],
            }

        if sim_ip and (sim_route or reachable):
            return {
                "ok": True,
                "mode": "sim",
                "transport": "sim",
                "status": "good",
                "signal": "good",
                "label": "SIM网络",
                "ai_mode": "cloud",
                "local_ai": local_ai,
                "sim_interface": interface,
                "sim_ip": sim_ip,
                "default_interface": default_iface,
                **wifi,
                "sim_present": True,
                "sim_connected": True,
                "sim_signal": "good",
                **sim_signal_data,
                "simulated": False,
                "warnings": [] if sim_route else ["SIM接口已获取地址，但默认出口未走 SIM。"],
            }

        return {
            "ok": True,
            "mode": "local",
            "transport": "local",
            "status": "offline",
            "signal": "none",
            "label": local_label,
            "ai_mode": local_ai_mode,
            "local_ai": local_ai,
            "sim_interface": interface,
            "sim_ip": sim_ip,
            "default_interface": default_iface,
            **wifi,
            "sim_present": sim_present,
            "sim_connected": False,
            "sim_signal": "none",
            **sim_signal_data,
            "simulated": False,
            "warnings": ["未检测到可用 SIM 出口。", *local_warnings],
        }

    def set_mode(self, mode: str) -> dict[str, object]:
        normalized = (mode or "").strip().lower()
        if normalized not in {"sim", "local", "offline"}:
            normalized = "sim"
        db.set_setting("network_mode", normalized)
        return self.status()

    def start_4g(self) -> dict[str, object]:
        db.set_setting("network_mode", "sim")
        result = QsmClient().start_4g_network()
        status = self.status()
        return {
            "ok": bool(result.get("ok")) and bool(status.get("signal") == "good"),
            "message": result.get("detail") or result.get("error_message") or "",
            "raw": result,
            "network": status,
        }

    @staticmethod
    def _interface_ipv4(interface: str) -> str:
        if not interface:
            return ""
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", "dev", interface],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/", result.stdout or "")
        return match.group(1) if match else ""

    @staticmethod
    def _default_interface() -> str:
        try:
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        match = re.search(r"\bdev\s+(\S+)", result.stdout or "")
        return match.group(1) if match else ""

    @staticmethod
    def _wifi_status(default_iface: str) -> dict[str, object]:
        ssid = ""
        signal = "none"
        dbm: int | None = None
        iface = default_iface if default_iface.startswith(("wl", "wlan")) else "wlan0"
        try:
            result = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=1, check=False)
            ssid = (result.stdout or "").strip()
        except (OSError, subprocess.TimeoutExpired):
            ssid = ""
        try:
            result = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=1, check=False)
            output = result.stdout or ""
            if "Connected to" in output:
                if not ssid:
                    match_ssid = re.search(r"SSID:\s*(.+)", output)
                    ssid = match_ssid.group(1).strip() if match_ssid else ""
                match_signal = re.search(r"signal:\s*(-?\d+)", output)
                if match_signal:
                    dbm = int(match_signal.group(1))
                    signal = "good" if dbm >= -67 else "weak" if dbm >= -80 else "none"
        except (OSError, subprocess.TimeoutExpired):
            pass
        connected = bool(ssid or default_iface.startswith(("wl", "wlan")))
        metrics = NetworkService.signal_metrics(dbm, "wifi")
        if connected and signal == "none" and metrics["bars"] > 0:
            signal = "weak"
        return {
            "wifi_connected": connected,
            "wifi_signal": signal,
            "wifi_ssid": ssid,
            "wifi_interface": iface if connected else "",
            "wifi_signal_dbm": metrics["dbm"],
            "wifi_signal_percent": metrics["percent"],
            "wifi_signal_bars": metrics["bars"],
            "wifi_signal_level": metrics["level"],
        }

    @staticmethod
    def signal_metrics(dbm: int | None, kind: str = "wifi") -> dict[str, object]:
        if dbm is None:
            return {"dbm": None, "percent": 0, "bars": 0, "level": "none"}
        value = int(dbm)
        percent = max(0, min(100, round((value + 100) * 2)))
        if kind == "sim":
            thresholds = ((-75, 4, "excellent"), (-85, 3, "good"), (-95, 2, "fair"), (-105, 1, "weak"))
        else:
            thresholds = ((-55, 4, "excellent"), (-67, 3, "good"), (-77, 2, "fair"), (-87, 1, "weak"))
        for threshold, bars, level in thresholds:
            if value >= threshold:
                return {"dbm": value, "percent": percent, "bars": bars, "level": level}
        return {"dbm": value, "percent": percent, "bars": 0, "level": "none"}

    @staticmethod
    def sim_signal_metrics(csq: int | None) -> dict[str, object]:
        value = 99 if csq is None else int(csq)
        if value < 0 or value > 31:
            return {"csq": value, **NetworkService.signal_metrics(None, "sim")}
        dbm = -113 + (2 * value)
        return {"csq": value, **NetworkService.signal_metrics(dbm, "sim")}

    @classmethod
    def stable_sim_signal_metrics(cls, csq: object, *, connected: bool) -> dict[str, object]:
        try:
            value = int(csq)
        except (TypeError, ValueError):
            value = 99

        now = time.monotonic()
        current = cls.sim_signal_metrics(value)
        if 0 <= value <= 31:
            with cls._sim_signal_lock:
                cls._sim_signal_cache = (now, dict(current))
            return {**current, "sample": "live", "sample_age_seconds": 0}

        if connected:
            with cls._sim_signal_lock:
                cached = cls._sim_signal_cache
            if cached:
                measured_at, metrics = cached
                age = max(0.0, now - measured_at)
                if age <= cls._sim_signal_ttl_seconds:
                    return {
                        **metrics,
                        "sample": "cached",
                        "sample_age_seconds": round(age, 1),
                    }

        return {**current, "sample": "unavailable", "sample_age_seconds": None}

    @staticmethod
    def _ping_target(target: str) -> bool:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
