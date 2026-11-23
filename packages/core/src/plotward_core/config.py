from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLOTWARD_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://plotward:plotward@localhost:5432/plotward"
    data_dir: Path = Path("./data")
    api_key: str = ""
    max_upload_mb: int = 50
    garden_name: str = "My garden"
    garden_timezone: str = "America/Los_Angeles"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
