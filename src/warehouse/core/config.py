import os
from pathlib import Path
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# пути к переменным окружения
ENV_FILE = Path(os.environ.get("WAREHOUSE_ENV_FILE", ".env"))
SECRETS_DIR = Path(os.environ.get("WAREHOUSE_SECRETS_DIR", "secrets"))


class Settings(BaseSettings):
    """Общие настройки сервисов."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,
        extra="ignore",
    )

    database_url: str
    redis_url: str
    postgres_password: str
    redis_password: str
    api_host: str
    api_port: int
    redis_timeout: float = 2.0

    @model_validator(mode="after")
    def insert_passwords(self) -> "Settings":
        """Подставляет пароли в адреса."""
        self.database_url = self.database_url.replace(
            "{password}", quote(self.postgres_password, safe="")
        )
        self.redis_url = self.redis_url.replace("{password}", quote(self.redis_password, safe=""))

        return self
