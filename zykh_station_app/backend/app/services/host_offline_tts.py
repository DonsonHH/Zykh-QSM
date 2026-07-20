from __future__ import annotations

import asyncio
import importlib.util
import re
import subprocess
import sys
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import Any

from ..config import settings
from .qsm_client import QsmClient


_HOST_TTS: HostOfflineTts | None = None


class HostOfflineTts:
    """Generate offline speech on the host and stream PCM to the QSM speaker.

    QSM is deliberately used only as a playback endpoint here. The Sherpa model
    is loaded by this FastAPI process, so the board does not spend CPU and RAM
    on a second TTS model alongside ASR and the local inquiry model.
    """

    _model_lock = threading.Lock()
    _speak_lock = asyncio.Lock()
    _loaded_model: Any | None = None
    _loaded_root: str = ""

    def __init__(self, qsm_client: QsmClient | None = None) -> None:
        self.qsm_client = qsm_client or QsmClient()

    @property
    def model_root(self) -> Path:
        return Path(settings.host_offline_tts_model_root)

    def status(self) -> dict[str, Any]:
        cls = type(self)
        model_dir = self.model_root / "models" / "tts"
        required = {
            "model": model_dir / "zh_CN-xiao_ya-medium.onnx",
            "lexicon": model_dir / "lexicon.txt",
            "tokens": model_dir / "tokens.txt",
        }
        missing = [name for name, path in required.items() if not path.is_file() or path.stat().st_size == 0]
        package_available = importlib.util.find_spec("sherpa_onnx") is not None
        ready = package_available and not missing
        return {
            "ok": ready,
            "ready": ready,
            "source": "host-local-sherpa-onnx",
            "engine": "host-offline-sherpa-onnx",
            "model_loaded": cls._loaded_model is not None and cls._loaded_root == str(self.model_root),
            "model_root": str(self.model_root),
            "package_available": package_available,
            "missing": missing,
            "output": settings.host_offline_tts_output,
            "qsm_playback": settings.host_offline_tts_output in {"qsm", "auto"},
        }

    async def warmup(self) -> dict[str, Any]:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._load_model),
                timeout=settings.host_offline_tts_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error_message": "主机离线语音模型加载超时。", **self.status()}
        except Exception as exc:
            return {"ok": False, "error_message": str(exc), **self.status()}
        return {"ok": True, **self.status()}

    async def speak(
        self,
        text: str,
        *,
        volume: int | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        async with self._speak_lock:
            clean = _clean_text(text, settings.host_offline_tts_max_chars)
            if not clean:
                return {"ok": False, "error_message": "播报文本为空。", "offline": True}

            started_at = time.monotonic()
            try:
                pcm, sample_rate = await asyncio.wait_for(
                    asyncio.to_thread(self._synthesize, clean, speed),
                    timeout=settings.host_offline_tts_timeout_seconds,
                )
            except asyncio.TimeoutError:
                return {
                    "ok": False,
                    "offline": True,
                    "mode": "host-offline-sherpa-onnx",
                    "error_message": "主机离线语音合成超时。",
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "offline": True,
                    "mode": "host-offline-sherpa-onnx",
                    "error_message": f"主机离线语音合成失败：{exc}",
                }
            synthesis_ms = round((time.monotonic() - started_at) * 1000)

            output = (settings.host_offline_tts_output or "qsm").strip().lower()
            if output not in {"qsm", "host", "auto"}:
                output = "qsm"
            if output in {"qsm", "auto"}:
                qsm_result = await self._play_qsm(pcm, sample_rate, volume)
                if qsm_result.get("ok"):
                    return {
                        **qsm_result,
                        "offline": True,
                        "mode": "host-offline-sherpa-onnx-pcm",
                        "engine": "host-offline-sherpa-onnx",
                        "sample_rate": sample_rate,
                        "audio_bytes": len(pcm),
                        "first_audio_ms": synthesis_ms,
                    }
                if output == "qsm":
                    return {
                        "ok": False,
                        "offline": True,
                        "mode": "host-offline-sherpa-onnx",
                        "engine": "host-offline-sherpa-onnx",
                        "error_message": qsm_result.get("error_message") or "QSM 喇叭播放失败。",
                        "raw": qsm_result,
                    }

            host_result = await asyncio.to_thread(self._play_host, pcm, sample_rate, volume)
            return {
                **host_result,
                "offline": True,
                "mode": "host-offline-sherpa-onnx-host-playback",
                "engine": "host-offline-sherpa-onnx",
                "sample_rate": sample_rate,
                "audio_bytes": len(pcm),
                "first_audio_ms": synthesis_ms,
            }

    def speak_sync(
        self,
        text: str,
        *,
        volume: int | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        """Synchronous bridge for the background cloud-sync worker."""
        return asyncio.run(self.speak(text, volume=volume, speed=speed))

    def _load_model(self) -> Any:
        cls = type(self)
        with cls._model_lock:
            root = self.model_root
            root_key = str(root)
            if cls._loaded_model is not None and cls._loaded_root == root_key:
                return cls._loaded_model

            import sherpa_onnx

            model_dir = root / "models" / "tts"
            model = model_dir / "zh_CN-xiao_ya-medium.onnx"
            lexicon = model_dir / "lexicon.txt"
            tokens = model_dir / "tokens.txt"
            for path in (model, lexicon, tokens):
                if not path.is_file() or path.stat().st_size == 0:
                    raise FileNotFoundError(f"主机离线语音资源不存在：{path}")

            vits = sherpa_onnx.OfflineTtsVitsModelConfig()
            vits.model = str(model)
            vits.lexicon = str(lexicon)
            vits.tokens = str(tokens)
            vits.noise_scale = 0.667
            vits.noise_scale_w = 0.8
            vits.length_scale = 1.0

            model_config = sherpa_onnx.OfflineTtsModelConfig()
            model_config.vits = vits
            model_config.num_threads = settings.host_offline_tts_threads
            model_config.provider = "cpu"

            config = sherpa_onnx.OfflineTtsConfig()
            config.model = model_config
            config.rule_fsts = ",".join(
                str(model_dir / name) for name in ("phone.fst", "date.fst", "number.fst")
                if (model_dir / name).is_file()
            )
            config.max_num_sentences = 1
            config.silence_scale = 0.03
            if not config.validate():
                raise RuntimeError("主机离线语音模型配置无效。")

            loaded = sherpa_onnx.OfflineTts(config)
            cls._loaded_model = loaded
            cls._loaded_root = root_key
            return loaded

    def _synthesize(self, text: str, speed: float | None) -> tuple[bytes, int]:
        model = self._load_model()
        speech_speed = max(0.75, min(float(speed if speed is not None else 1.0), 1.8))
        audio = model.generate(text, sid=0, speed=speech_speed)
        samples = audio.samples
        if samples is None or len(samples) == 0:
            raise RuntimeError("主机离线语音模型没有生成音频。")
        pcm = array("h")
        for sample in samples:
            value = max(-1.0, min(1.0, float(sample)))
            pcm.append(round(value * 32767.0))
        if sys.byteorder != "little":
            pcm.byteswap()
        return pcm.tobytes(), int(audio.sample_rate)

    async def _play_qsm(self, pcm: bytes, sample_rate: int, volume: int | None) -> dict[str, Any]:
        await asyncio.to_thread(self.qsm_client.audio_stream_stop)
        started = await asyncio.to_thread(
            self.qsm_client.audio_stream_start,
            port=settings.qsm_audio_stream_port,
            volume=volume if volume is not None else 230,
            rate=sample_rate,
            channels=1,
        )
        if not started.get("ok"):
            return {
                "ok": False,
                "error_message": started.get("error_message") or started.get("detail") or "外设 PCM 播放流启动失败。",
                "raw": started,
            }

        writer: asyncio.StreamWriter | None = None
        try:
            writer = await self._open_output()
            first_audio_at = time.monotonic()
            for offset in range(0, len(pcm), 64 * 1024):
                writer.write(pcm[offset : offset + 64 * 1024])
                await writer.drain()
            writer.close()
            await writer.wait_closed()
            writer = None
            duration = len(pcm) / max(1, sample_rate * 2)
            elapsed = time.monotonic() - first_audio_at
            await asyncio.sleep(max(0.35, min(settings.qwen_realtime_tts_max_drain_seconds, duration - elapsed + 0.45)))
            return {"ok": True, "detail": "主机离线语音已发送到外设喇叭。", "total_ms": round((time.monotonic() - first_audio_at) * 1000)}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return {"ok": False, "error_message": f"外设 PCM 播放失败：{exc}"}
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            await asyncio.to_thread(self.qsm_client.audio_stream_stop)

    async def _open_output(self) -> asyncio.StreamWriter:
        last_error: Exception | None = None
        for _ in range(12):
            try:
                _reader, writer = await asyncio.open_connection(
                    settings.qsm_audio_stream_host,
                    settings.qsm_audio_stream_port,
                )
                return writer
            except OSError as exc:
                last_error = exc
                await asyncio.sleep(0.1)
        raise RuntimeError(f"无法连接外设 PCM 播放端口：{last_error}")

    @staticmethod
    def _play_host(pcm: bytes, sample_rate: int, volume: int | None) -> dict[str, Any]:
        output_dir = Path(settings.host_offline_tts_model_root).parent / "audio"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "host-offline-tts.wav"
        with wave.open(str(output_file), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(sample_rate)
            stream.writeframes(pcm)

        commands: list[list[str]] = []
        if _which("paplay"):
            commands.append(["paplay", str(output_file)])
        if _which("aplay"):
            commands.append(["aplay", "-q", str(output_file)])
        if _which("ffplay"):
            commands.append(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(output_file)])
        if not commands:
            return {"ok": False, "error_message": "主机没有可用的本地音频播放命令。"}
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=settings.host_offline_tts_timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
                continue
            if result.returncode == 0:
                return {"ok": True, "detail": "主机离线语音已通过本机声卡播放。", "output_file": str(output_file)}
            last_error = (result.stderr or result.stdout or f"exit={result.returncode}").strip()
        return {"ok": False, "error_message": f"主机声卡播放失败：{last_error}"}


def get_host_offline_tts(qsm_client: QsmClient | None = None) -> HostOfflineTts:
    global _HOST_TTS
    if _HOST_TTS is None:
        _HOST_TTS = HostOfflineTts(qsm_client)
    elif qsm_client is not None:
        _HOST_TTS.qsm_client = qsm_client
    return _HOST_TTS


def _clean_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:max_chars]


def _which(command: str) -> str:
    from shutil import which

    return which(command) or ""
