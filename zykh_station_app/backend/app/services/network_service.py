from __future__ import annotations

import re
import subprocess

from .. import db
from ..config import settings


class NetworkService:
    def status(self) -> dict[str, object]:
        preferred = db.get_setting("network_mode", settings.network_preferred_mode).strip().lower() or "sim"
        interface = settings.network_sim_interface
        sim_ip = self._interface_ipv4(interface)
        default_iface = self._default_interface()
        sim_route = default_iface == interface
        reachable = self._ping_target("223.5.5.5") if sim_ip else False

        if preferred in {"local", "offline"}:
            return {
                "ok": True,
                "mode": "local",
                "transport": "local",
                "status": "offline",
                "signal": "none",
                "label": "本地兜底",
                "ai_mode": "local_fallback",
                "sim_interface": interface,
                "sim_ip": sim_ip,
                "default_interface": default_iface,
                "simulated": False,
                "warnings": ["当前手动切换到本地兜底。"],
            }

        if sim_ip and (sim_route or reachable):
            return {
                "ok": True,
                "mode": "sim",
                "transport": "sim",
                "status": "good" if reachable or sim_route else "weak",
                "signal": "good" if reachable or sim_route else "weak",
                "label": "SIM网络",
                "ai_mode": "cloud",
                "sim_interface": interface,
                "sim_ip": sim_ip,
                "default_interface": default_iface,
                "simulated": False,
                "warnings": [] if sim_route else ["SIM接口已获取地址，但默认出口未走 SIM。"],
            }

        if settings.network_demo_simulate:
            return {
                "ok": True,
                "mode": "sim",
                "transport": "sim",
                "status": "good",
                "signal": "good",
                "label": "SIM网络",
                "ai_mode": "cloud",
                "sim_interface": interface,
                "sim_ip": sim_ip,
                "default_interface": default_iface,
                "simulated": True,
                "warnings": ["未检测到 SIM 出口，演示模式显示为可用。"],
            }

        return {
            "ok": True,
            "mode": "local",
            "transport": "local",
            "status": "offline",
            "signal": "none",
            "label": "本地兜底",
            "ai_mode": "local_fallback",
            "sim_interface": interface,
            "sim_ip": sim_ip,
            "default_interface": default_iface,
            "simulated": False,
            "warnings": ["未检测到可用 SIM 出口。"],
        }

    def set_mode(self, mode: str) -> dict[str, object]:
        normalized = (mode or "").strip().lower()
        if normalized not in {"sim", "local", "offline"}:
            normalized = "sim"
        db.set_setting("network_mode", normalized)
        return self.status()

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
