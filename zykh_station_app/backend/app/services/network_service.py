from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .. import db
from ..config import APP_ROOT, settings
from .local_ai_client import LocalAiClient
from .local_inquiry_status import local_inquiry_status
from .qsm_client import QsmClient


class NetworkService:
    _sim_signal_lock = threading.Lock()
    _sim_signal_cache: tuple[float, dict[str, object]] | None = None
    _sim_signal_ttl_seconds = 45.0
    _sim_identity_lock = threading.Lock()
    _qsm_network_lock = threading.Lock()
    _qsm_network_cache: tuple[float, dict[str, object]] | None = None
    _qsm_network_ttl_seconds = 8.0

    def status(self) -> dict[str, object]:
        preferred = db.get_setting("network_mode", settings.network_preferred_mode).strip().lower() or "sim"
        interface = settings.network_sim_interface
        sim_ip = self._interface_ipv4(interface)
        default_iface = self._default_interface()
        wifi = self._wifi_status(default_iface)
        sim_route = default_iface == interface
        reachable = self._ping_target("223.5.5.5", interface) if sim_ip else False
        host_tether_ready = self._host_tether_ready(interface)
        qsm_network = self._qsm_network_status()
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
        sim_connected = bool(
            (qsm_connected and host_tether_ready)
            or (sim_ip and sim_route and reachable)
        )
        sim_present = bool(qsm_sim_present or sim_ip)
        local_ai = local_inquiry_status(LocalAiClient().status())
        local_ai_ready = bool(local_ai.get("ready"))
        local_rule_mode = local_ai.get("mode") == "offline_rules"
        local_label = "本地问询" if local_rule_mode else "离线模型" if local_ai_ready else "离线问询"
        local_ai_mode = "offline_rules" if local_rule_mode else "local_llm" if local_ai_ready else "local_unavailable"
        local_warnings = [] if local_ai_ready else ["本地问询服务尚未就绪。"]
        sim_enabled = self._bool_setting("sim_enabled", True)
        sim_identity = self._sim_identity(qsm_network, qsm_at)

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
                "qsm_sim_connected": qsm_connected,
                "host_tether_ready": host_tether_ready,
                "sim_signal": str(qsm_network.get("signal") or ("good" if sim_connected else "none")),
                "sim_enabled": sim_enabled,
                **sim_identity,
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
                "qsm_sim_connected": qsm_connected,
                "host_tether_ready": host_tether_ready,
                "sim_signal": str(qsm_network.get("signal") or ("good" if sim_connected else "none")),
                "sim_enabled": sim_enabled,
                **sim_identity,
                **sim_signal_data,
                "simulated": False,
                "source": "host",
                "warnings": [] if (not sim_enabled or sim_connected) else ["SIM 备用链路未连通。"],
            }

        if qsm_connected and host_tether_ready:
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
                "qsm_sim_connected": True,
                "host_tether_ready": True,
                "sim_signal": str(qsm_network.get("signal") or "good"),
                "sim_enabled": sim_enabled,
                **sim_identity,
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
                "qsm_sim_connected": qsm_connected,
                "host_tether_ready": host_tether_ready,
                "sim_signal": str(qsm_network.get("signal") or "weak"),
                "sim_enabled": sim_enabled,
                **sim_identity,
                **sim_signal_data,
                "simulated": False,
                "source": "qsm",
                "warnings": [
                    "数据网络已连接，但主机备用通道未就绪。"
                    if qsm_connected
                    else "外设已检测到 SIM 模块，但数据网络未连通。",
                    *local_warnings,
                ],
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
                "qsm_sim_connected": qsm_connected,
                "host_tether_ready": host_tether_ready,
                "sim_signal": "good",
                "sim_enabled": sim_enabled,
                **sim_identity,
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
            "qsm_sim_connected": qsm_connected,
            "host_tether_ready": host_tether_ready,
            "sim_signal": "none",
            "sim_enabled": sim_enabled,
            **sim_identity,
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

    @classmethod
    def _qsm_network_status(cls) -> dict[str, object]:
        now = time.monotonic()
        cached = cls._qsm_network_cache
        if cached and now - cached[0] <= cls._qsm_network_ttl_seconds:
            return dict(cached[1])
        with cls._qsm_network_lock:
            now = time.monotonic()
            cached = cls._qsm_network_cache
            if cached and now - cached[0] <= cls._qsm_network_ttl_seconds:
                return dict(cached[1])
            result = QsmClient().get_network_status()
            cls._qsm_network_cache = (now, dict(result))
            return result

    @staticmethod
    def _bool_setting(key: str, default: bool) -> bool:
        value = db.get_setting(key, "true" if default else "false").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @classmethod
    def _sim_identity(cls, qsm_network: dict[str, object], qsm_at: dict[str, object]) -> dict[str, str]:
        live_operator_code = str(
            qsm_network.get("operator_code")
            or qsm_network.get("operator")
            or qsm_at.get("operator")
            or ""
        ).strip()
        if live_operator_code and db.get_setting("sim_operator_code", "") != live_operator_code:
            db.set_setting("sim_operator_code", live_operator_code)
        operator_code = live_operator_code or db.get_setting("sim_operator_code", "").strip()
        operator_map = {
            "46000": "中国移动",
            "46002": "中国移动",
            "46004": "中国移动",
            "46007": "中国移动",
            "46008": "中国移动",
            "46001": "中国联通",
            "46006": "中国联通",
            "46009": "中国联通",
            "46003": "中国电信",
            "46005": "中国电信",
            "46011": "中国电信",
        }
        live_operator = str(qsm_network.get("operator_name") or "").strip()
        operator = live_operator or operator_map.get(operator_code, "") or db.get_setting("sim_operator", "").strip()
        if operator and db.get_setting("sim_operator", "") != operator:
            db.set_setting("sim_operator", operator)
        phone_number = str(
            qsm_network.get("phone_number")
            or qsm_network.get("sim_phone_number")
            or qsm_at.get("phone_number")
            or db.get_setting("sim_phone_number", "")
            or ""
        ).strip()
        if not phone_number and bool(qsm_network.get("sim_present") or qsm_network.get("connected")):
            phone_number = cls._read_qsm_sim_phone_number()
        return {
            "sim_operator": operator,
            "sim_operator_code": operator_code,
            "sim_phone_number": phone_number,
        }

    @classmethod
    def _read_qsm_sim_phone_number(cls) -> str:
        with cls._sim_identity_lock:
            cached = db.get_setting("sim_phone_number", "").strip()
            if cached:
                return cached
            command = (
                "PORT=/dev/ttyUSB2; OUT=/tmp/zykh_sim_cnum.txt; "
                "stty -F \"$PORT\" 115200 raw -echo 2>/dev/null; rm -f \"$OUT\"; "
                "timeout 4 cat \"$PORT\" > \"$OUT\" 2>/dev/null & reader=$!; sleep 0.3; "
                "printf 'AT+CNUM\\r\\n' > \"$PORT\"; sleep 1; "
                "kill \"$reader\" 2>/dev/null; wait \"$reader\" 2>/dev/null; cat \"$OUT\" 2>/dev/null"
            )
            adb = ["adb"]
            serial = os.environ.get("ADB_SERIAL", "").strip()
            if serial:
                adb.extend(["-s", serial])
            adb.extend(["shell", command])
            try:
                result = subprocess.run(adb, capture_output=True, text=True, timeout=6, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return ""
            match = re.search(r'\+CNUM:\s*"[^"]*","([+\d]{6,20})"', result.stdout or "")
            phone_number = match.group(1) if match else ""
            if phone_number:
                db.set_setting("sim_phone_number", phone_number)
            return phone_number

    def start_4g(self) -> dict[str, object]:
        db.set_setting("network_mode", "sim")
        result = QsmClient().start_4g_network()
        tether = self._prepare_host_tether() if result.get("ok") else {
            "ok": False,
            "message": "QSM 数据网络尚未启动，未配置主机备用通道。",
        }
        self.__class__._qsm_network_cache = None
        status = self.status()
        return {
            "ok": bool(result.get("ok")) and bool(tether.get("ok")),
            "message": (
                str(tether.get("message") or "")
                or str(result.get("detail") or result.get("error_message") or "")
            ),
            "raw": result,
            "tether": tether,
            "network": status,
        }

    def disable_host_tether(self) -> dict[str, object]:
        helper = settings.network_host_tether_helper
        if not Path(helper).is_file():
            return {"ok": True, "message": "主机备用通道未安装，无需关闭。"}
        result = self._run_command(["sudo", "-n", helper, "disable"], timeout=5)
        if result is None or result.returncode != 0:
            detail = ((result.stderr if result else "") or "").strip()
            return {"ok": False, "message": detail or "主机备用通道未能关闭。"}
        return {"ok": True, "message": (result.stdout or "").strip()}

    def _prepare_host_tether(self) -> dict[str, object]:
        remote_script = settings.network_qsm_tether_script
        local_script = APP_ROOT / "qsm_gateway" / "start_host_tether.sh"
        if not local_script.is_file():
            return {"ok": False, "message": "缺少 QSM 主机网络共享脚本。"}

        adb = self._adb_prefix()
        remote_dir = remote_script.rsplit("/", 1)[0]
        commands = (
            [*adb, "shell", f"mkdir -p '{remote_dir}'"],
            [*adb, "push", str(local_script), remote_script],
            [*adb, "shell", f"chmod +x '{remote_script}'; sh '{remote_script}' start"],
        )
        for command in commands:
            result = self._run_command(command, timeout=12)
            if result is None or result.returncode != 0:
                detail = ((result.stderr if result else "") or (result.stdout if result else "") or "").strip()
                return {"ok": False, "message": f"QSM 网络共享准备失败：{detail[:180]}"}

        helper = settings.network_host_tether_helper
        if not Path(helper).is_file():
            return {
                "ok": False,
                "message": "主机数据网络组件尚未安装，请重新运行启动脚本并完成一次管理员授权。",
            }
        result = self._run_command(["sudo", "-n", helper, "enable"], timeout=6)
        if result is None or result.returncode != 0:
            detail = ((result.stderr if result else "") or "").strip()
            return {"ok": False, "message": detail or "主机数据网络备用路由未能启用。"}

        for _ in range(10):
            if self._host_tether_ready(settings.network_sim_interface):
                return {"ok": True, "message": "数据网络备用通道已就绪。"}
            time.sleep(0.2)
        return {"ok": False, "message": "主机已配置备用路由，但未能连接 QSM 网关地址。"}

    @staticmethod
    def _adb_prefix() -> list[str]:
        command = ["adb"]
        serial = os.environ.get("ADB_SERIAL", "").strip()
        if serial:
            command.extend(["-s", serial])
        return command

    @staticmethod
    def _run_command(command: list[str], timeout: float) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _host_tether_ready(self, interface: str) -> bool:
        return (
            self._interface_ipv4(interface) == settings.network_host_tether_address
            and self._ping_target(settings.network_host_tether_gateway, interface)
        )

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
    def _ping_target(target: str, interface: str = "") -> bool:
        command = ["ping"]
        if interface:
            command.extend(["-I", interface])
        command.extend(["-c", "1", "-W", "1", target])
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0
