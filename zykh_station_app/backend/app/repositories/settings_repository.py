from __future__ import annotations

import json
from typing import Any

from .. import db


class SettingsRepository:
    def get_json(self, key: str, default: dict[str, Any]) -> dict[str, Any]:
        raw = db.get_setting(key)
        if not raw:
            return dict(default)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return dict(default)
        return value if isinstance(value, dict) else dict(default)

    def set_json(self, key: str, value: dict[str, Any]) -> None:
        db.set_setting(key, json.dumps(value, ensure_ascii=False))
