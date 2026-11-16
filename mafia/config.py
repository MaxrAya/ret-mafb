from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    admin_ids: str = ""
    log_level: str = "INFO"
    db_path: str = "data/mafia.db"

    default_min_players: int = 5
    default_max_players: int = 15
    default_discuss_s: int = 120
    default_vote_s: int = 90
    default_night_s: int = 60
    default_hunter_s: int = 45
    lobby_timeout_s: int = 1800
    media_warn_cooldown_s: int = 30
    dead_warn_cooldown_s: int = 60

    @property
    def admins(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_ids.split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
