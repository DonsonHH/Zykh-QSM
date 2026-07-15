from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import settings


class LocalAiClient:
    def __init__(
        self,
        base_url: str | None = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = (base_url or settings.local_ai_base_url).rstrip("/")
        self.opener = opener or urlopen

    def status(self) -> dict[str, Any]:
        url = self._url(settings.local_ai_health_path)
        request = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with self.opener(request, timeout=settings.local_ai_health_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._unavailable(f"HTTP {exc.code}")
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return self._unavailable(str(exc))

        server_status = str(data.get("status") or "").strip().lower()
        ready = server_status in {"ok", "ready"}
        return {
            "ok": ready,
            "ready": ready,
            "status": "ready" if ready else server_status or "loading",
            "base_url": self.base_url,
            "model": settings.local_ai_model,
            "error_message": "" if ready else "离线模型仍在载入。",
            "raw": data,
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 320,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": settings.local_ai_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "cache_prompt": True,
        }
        if response_format:
            payload["response_format"] = response_format
        request = Request(
            self._url(settings.local_ai_chat_path),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.opener(request, timeout=settings.local_ai_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = self._http_error_detail(exc)
            return {"ok": False, "error_message": f"离线模型 HTTP {exc.code}: {detail}".rstrip()}
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error_message": f"离线模型请求失败：{exc}"}

        reply = self.extract_text(data)
        if not reply:
            return {"ok": False, "error_message": "离线模型未返回有效内容。", "raw": data}
        return {
            "ok": True,
            "source": "local_llm",
            "model": settings.local_ai_model,
            "reply": reply,
            "offline": True,
            "raw": data,
        }

    @staticmethod
    def extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        message = message if isinstance(message, dict) else {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                str(item.get("text") or item.get("content") or "") if isinstance(item, dict) else str(item)
                for item in content
            )
        text = str(content or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return text

    def _url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"

    def _unavailable(self, detail: str) -> dict[str, Any]:
        return {
            "ok": False,
            "ready": False,
            "status": "unavailable",
            "base_url": self.base_url,
            "model": settings.local_ai_model,
            "error_message": detail or "离线模型不可用。",
        }

    @staticmethod
    def _http_error_detail(exc: HTTPError) -> str:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body[:240]
        return str(data.get("error", {}).get("message") or data.get("detail") or body[:240])
