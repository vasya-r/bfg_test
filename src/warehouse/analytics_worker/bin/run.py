import asyncio
import logging
import signal

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from warehouse.analytics_worker.worker import AnalyticsWorker
from warehouse.core.config import Settings


async def run(settings: Settings) -> None:
    """Запуск воркера с последующей остановкой."""
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    redis = Redis.from_url(settings.redis_url, encoding="utf8", decode_responses=True)

    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, lambda: task.cancel())

    try:
        await AnalyticsWorker(engine, redis).run()
    except asyncio.CancelledError:
        pass
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(run(Settings()))


if __name__ == "__main__":
    main()
