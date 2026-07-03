from __future__ import annotations

from ..core.constants import DEFAULT_SITE
from ..repositories.settings_repository import SettingsRepository
from ..schemas.site import SiteProfile, SiteUpdate


class StationService:
    def __init__(self, repo: SettingsRepository | None = None) -> None:
        self.repo = repo or SettingsRepository()

    def get_site(self) -> SiteProfile:
        return SiteProfile(**self.repo.get_json("site_profile", DEFAULT_SITE))

    def save_site(self, update: SiteUpdate) -> SiteProfile:
        current = self.get_site().model_dump()
        for key, value in update.model_dump(exclude_none=True).items():
            current[key] = value
        profile = SiteProfile(**current)
        self.repo.set_json("site_profile", profile.model_dump())
        return profile
