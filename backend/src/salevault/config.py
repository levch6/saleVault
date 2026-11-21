"""Application settings, overridable through SALEVAULT_* environment variables or `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/salevault/config.py -> repository root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SALEVAULT_",
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    data_dir: Path = PROJECT_ROOT / "data"
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    """Host names the API answers to. Anything else is refused, so a web page that points its
    own domain at 127.0.0.1 (DNS rebinding) cannot use the local API."""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "salevault.db"

    def browser_profile_dir(self, site: str) -> Path:
        return self.data_dir / "browser" / site

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
