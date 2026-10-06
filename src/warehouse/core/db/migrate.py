from pathlib import Path

from alembic import command
from alembic.config import Config

from warehouse.core.config import Settings


def alembic_config(database_url: str | None = None) -> Config:
    """Конфигурация alembic."""
    database_url = database_url or Settings().database_url
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    return config


def migrate_up(database_url: str | None = None) -> None:
    """Применяет миграции."""
    command.upgrade(alembic_config(database_url), "head")
