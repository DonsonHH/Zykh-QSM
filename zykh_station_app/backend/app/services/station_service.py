from __future__ import annotations

from ..core.constants import DEFAULT_SITE
from ..repositories.settings_repository import SettingsRepository
from ..schemas.site import SiteProfile, SiteUpdate


OLD_DEFAULT_STATION_NAMES = {"偏远社区康护站", "智药康护终端"}
OLD_DEFAULT_SERVICE_NAMES = {"村镇智慧用药服务点", "偏远社区康护站 · 村镇智慧用药服务点"}


class StationService:
    def __init__(self, repo: SettingsRepository | None = None) -> None:
        self.repo = repo or SettingsRepository()

    def get_site(self) -> SiteProfile:
        value = self.repo.get_json("site_profile", DEFAULT_SITE)
        if value.get("station_name") in OLD_DEFAULT_STATION_NAMES and value.get("service_name") in OLD_DEFAULT_SERVICE_NAMES:
            value = {**value, **DEFAULT_SITE}
            self.repo.set_json("site_profile", value)
        return SiteProfile(**value)

    def save_site(self, update: SiteUpdate) -> SiteProfile:
        current = self.get_site().model_dump()
        for key, value in update.model_dump(exclude_none=True).items():
            current[key] = value
        profile = SiteProfile(**current)
        self.repo.set_json("site_profile", profile.model_dump())
        return profile
