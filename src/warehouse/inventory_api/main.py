from aiohttp import web
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from warehouse.core.config import Settings
from warehouse.inventory_api.keys import ENGINE, REDIS, SETTINGS
from warehouse.inventory_api.routes import routes
from warehouse.inventory_api.utils import error_middleware


async def _on_startup(app: web.Application) -> None:
    """Открыть pg и redis при старте."""
    settings = app[SETTINGS]
    app[ENGINE] = create_async_engine(settings.database_url, pool_pre_ping=True)
    app[REDIS] = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=settings.redis_timeout,
        socket_connect_timeout=settings.redis_timeout,
    )


async def _on_cleanup(app: web.Application) -> None:
    """Закрыть pg и redis при выходе."""
    await app[REDIS].aclose()
    await app[ENGINE].dispose()


def create_app(settings: Settings | None = None) -> web.Application:
    """Создает приложение."""
    app = web.Application(middlewares=[error_middleware])
    app[SETTINGS] = settings or Settings()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    app.add_routes(routes)

    return app
