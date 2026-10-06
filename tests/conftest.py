import asyncio
from typing import AsyncIterator

import asyncpg
import pytest
import sqlalchemy as sa
from aiohttp.test_utils import TestClient, TestServer
from pydantic import Field
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from warehouse.analytics_worker.worker import AnalyticsWorker
from warehouse.core.config import Settings
from warehouse.core.db.migrate import migrate_up
from warehouse.inventory_api.main import create_app


class TestSettings(Settings):
    """Настройки тестов."""

    database_url: str = Field(validation_alias="TEST_DATABASE_URL")
    redis_url: str = Field(validation_alias="TEST_REDIS_URL")


async def _init_database(database_url: str) -> None:
    """Создает тестовую базу при отсутствии."""
    url = make_url(database_url)
    conn = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", url.database)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Настройки базы."""
    settings = TestSettings()
    asyncio.run(_init_database(settings.database_url))
    migrate_up(settings.database_url)

    return settings


async def _truncate(engine: AsyncEngine) -> None:
    """Очищает таблицы."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE stock_events, stock_agg RESTART IDENTITY"))


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Движок с таблицами."""
    engine = create_async_engine(settings.database_url)
    await _truncate(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def redis(settings: Settings) -> AsyncIterator[Redis]:
    """Клиент redis."""
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
async def client(settings: Settings, engine: AsyncEngine) -> AsyncIterator[TestClient]:
    """Тестовый HTTP-клиент приложения inventory_api."""
    async with TestClient(TestServer(create_app(settings))) as client:
        yield client


@pytest.fixture
async def worker(engine: AsyncEngine, redis: Redis) -> AsyncIterator[AnalyticsWorker]:
    """Воркер аналитики с подпиской на каналы."""
    worker = AnalyticsWorker(engine, redis)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(worker.ready.wait(), timeout=5)
    yield worker
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
