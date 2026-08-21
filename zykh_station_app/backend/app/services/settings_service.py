from __future__ import annotations

import json
import os
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .. import db
from ..config import settings
from ..schemas.settings import BasicSettings, BasicSettingsResponse, BasicSettingsUpdateRequest
from .network_service import NetworkService
from .speaker_volume import get_persisted_speaker_gain, save_persisted_speaker_gain, speaker_gain_to_percent


class SettingsService:
    def get(self) -> BasicSettingsResponse:
        network = NetworkService().status()
        wifi_enabled = self._wifi_radio_enabled()
        sim_enabled = self._bool_setting("sim_enabled", True)
        values = BasicSettings(
            wifi_enabled=wifi_enabled,
            sim_enabled=sim_enabled,
            network_mode=db.get_setting("network_mode", settings.network_preferred_mode) or "sim",
            network_simulated=bool(network.get("simulated")),
            network_source=str(network.get("source") or ""),
            speaker_volume=get_persisted_speaker_gain(),
            microphone_volume=self._int_setting("microphone_volume", 70, 0, 100),
            display_brightness=self._int_setting("display_brightness", 100, 20, 100),
            idle_timeout_seconds=self._int_setting("idle_timeout_seconds", 90, 0, 3600),
            wifi_ssid=str(network.get("wifi_ssid") or ""),
            sim_connected=bool(network.get("sim_connected")),
            sim_operator=str(network.get("sim_operator") or ""),
            sim_operator_code=str(network.get("sim_operator_code") or ""),
            sim_phone_number=str(network.get("sim_phone_number") or ""),
            microphone_available=self._microphone_available(),
        )
        return BasicSettingsResponse(settings=values)

    def update(self, request: BasicSettingsUpdateRequest) -> BasicSettingsResponse:
        warnings: list[str] = []
        if request.wifi_enabled is not None:
            warning = self._set_wifi(request.wifi_enabled)
            if warning:
                warnings.append(warning)

        if request.sim_enabled is not None:
            warning = self._set_sim(request.sim_enabled)
            if warning:
                warnings.append(warning)

        if request.network_mode is not None:
            mode = request.network_mode.strip().lower()
            if mode not in {"sim", "local", "offline"}:
                warnings.append("运行模式未识别，已保持原设置。")
            else:
                NetworkService().set_mode(mode)

        if request.speaker_volume is not None:
            speaker_gain = save_persisted_speaker_gain(request.speaker_volume)
            warning = self._set_host_speaker_volume(speaker_gain)
            if warning:
                warnings.append(warning)

        if request.microphone_volume is not None:
            db.set_setting("microphone_volume", str(request.microphone_volume))
            result = self._qsm_mic_volume(request.microphone_volume)
            if not result.get("ok"):
                warnings.append(str(result.get("error_message") or "麦克风音量已保存，但外设暂未响应。"))

        if request.display_brightness is not None:
            db.set_setting("display_brightness", str(request.display_brightness))
            warning = self._set_brightness(request.display_brightness)
            if warning:
                warnings.append(warning)

        if request.idle_timeout_seconds is not None:
            db.set_setting("idle_timeout_seconds", str(request.idle_timeout_seconds))

        response = self.get()
        response.warnings = warnings
        return response

    @staticmethod
    def _bool_setting(key: str, default: bool) -> bool:
        value = db.get_setting(key, "true" if default else "false").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _int_setting(key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(db.get_setting(key, str(default)))
        except ValueError:
            value = default
        return max(minimum, min(value, maximum))

    @staticmethod
    def _run(command: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _wifi_radio_enabled(self) -> bool:
        result = self._run(["nmcli", "radio", "wifi"], timeout=2)
        if result and result.returncode == 0:
            return (result.stdout or "").strip().lower() == "enabled"
        result = self._run(["rfkill", "list", "wifi"], timeout=2)
        if not result:
            return True
        return "Soft blocked: yes" not in (result.stdout or "")

    def _set_wifi(self, enabled: bool) -> str:
        if not enabled:
            if settings.network_demo_simulate:
                return "4G 当前为模拟状态，不能作为真实备用网络；Wi-Fi 保持开启。"
            if not self._bool_setting("sim_enabled", True):
                return "请先开启数据网络；为避免失去连接，Wi-Fi 保持开启。"
            sim_result = NetworkService().start_4g()
            if not sim_result.get("ok"):
                detail = str(sim_result.get("message") or "数据网络备用通道未就绪。")
                return f"{detail} 为避免失去连接，Wi-Fi 保持开启。"
        action = "on" if enabled else "off"
        result = self._run(["nmcli", "radio", "wifi", action])
        if result and result.returncode == 0:
            db.set_setting("wifi_enabled", "true" if enabled else "false")
            return ""
        fallback = self._run(["rfkill", "unblock" if enabled else "block", "wifi"])
        if fallback and fallback.returncode == 0:
            db.set_setting("wifi_enabled", "true" if enabled else "false")
            return ""
        detail = ((result.stderr if result else "") or "").strip()
        return f"Wi-Fi 开关未生效。{detail[:120]}".strip()

    def _set_sim(self, enabled: bool) -> str:
        db.set_setting("sim_enabled", "true" if enabled else "false")
        if settings.network_demo_simulate:
            return ""
        if enabled:
            result = NetworkService().start_4g()
            return "" if result.get("ok") else str(result.get("message") or "SIM 网络启动失败，请检查外设连接。")

        tether = NetworkService().disable_host_tether()
        command = (
            "killall udhcpc 2>/dev/null; "
            "route del default dev usb0 2>/dev/null; "
            "ifconfig usb0 down 2>/dev/null"
        )
        adb = ["adb"]
        serial = os.environ.get("ADB_SERIAL", "").strip()
        if serial:
            adb.extend(["-s", serial])
        result = self._run([*adb, "shell", command], timeout=8)
        if result and result.returncode == 0 and tether.get("ok"):
            return ""
        return str(tether.get("message") or "SIM 开关状态已保存，但外设网络接口未能关闭。")

    def _set_host_speaker_volume(self, volume: int) -> str:
        percent = speaker_gain_to_percent(volume)
        result = self._run(["pactl", "set-sink-volume", "qsm_relay", f"{percent}%"], timeout=3)
        if result and result.returncode == 0:
            return ""
        return "外放音量已保存，但本机音频转发暂未就绪。"

    @staticmethod
    def _qsm_mic_volume(volume: int) -> dict[str, object]:
        url = f"{settings.qsm_mic_api_base}{settings.qsm_mic_volume_path}"
        body = json.dumps({"volume": int(volume)}).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=settings.qsm_mic_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {"ok": False, "error_message": "外设返回格式错误。"}
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error_message": f"外设麦克风暂不可用：{exc}"}

    @staticmethod
    def _microphone_available() -> bool:
        url = f"{settings.qsm_mic_api_base}{settings.qsm_mic_status_path}"
        try:
            with urlopen(url, timeout=min(settings.qsm_mic_timeout_seconds, 2)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return bool(isinstance(payload, dict) and payload.get("ok"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
            return False

    def _set_brightness(self, percent: int) -> str:
        output = settings.display_output
        env = os.environ.copy()
        env["DISPLAY"] = settings.display_name
        if settings.display_xauthority:
            env["XAUTHORITY"] = settings.display_xauthority
        if output == "auto":
            result = self._run_xrandr(["xrandr", "--query"], env)
            if result is None:
                return "亮度已保存，但当前显示服务不可访问。"
            match = re.search(r"^(\S+)\s+connected\s+primary\b", result.stdout or "", re.MULTILINE)
            if not match:
                match = re.search(r"^(\S+)\s+connected\b", result.stdout or "", re.MULTILINE)
            output = match.group(1) if match else ""
        if not output:
            return "亮度已保存，但没有检测到显示输出。"
        value = max(0.2, min(percent / 100, 1.0))
        result = self._run_xrandr(["xrandr", "--output", output, "--brightness", f"{value:.2f}"], env)
        if result and result.returncode == 0:
            return ""
        return "亮度已保存，但当前显示输出未能立即应用。"

    @staticmethod
    def _run_xrandr(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=4, check=False, env=env)
        except (OSError, subprocess.TimeoutExpired):
            return None
