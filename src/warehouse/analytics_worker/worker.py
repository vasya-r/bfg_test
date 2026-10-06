import asyncio
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from warehouse.analytics_worker.aggregates import apply_missed, update_event
from warehouse.core.schemas import CHANNELS, Event

log = logging.getLogger(__name__)

DB_ERRORS = (SQLAlchemyError, OSError)
RETRY_TIMEOUT = 1.0


class AnalyticsWorker:
    """Воркер аналитики с подпиской на каналы событий для обновления stock_agg."""

    def __init__(self, engine: AsyncEngine, redis: Redis) -> None:
        self._engine = engine
        self._redis = redis
        self.ready = asyncio.Event()

    async def run(self) -> None:
        while True:
            try:
                await self._consume()
            except (RedisConnectionError, RedisTimeoutError):
                log.warning("lost Redis connection, retrying in %ss", RETRY_TIMEOUT)
            except DB_ERRORS:
                log.exception("db error on catch-up, retrying in %ss", RETRY_TIMEOUT)
            finally:
                self.ready.clear()
            await asyncio.sleep(RETRY_TIMEOUT)

    async def _consume(self) -> None:
        """Подписаться и обрабатывать сообщения до обрыва связи."""
        async with self._redis.pubsub() as pubsub:
            await pubsub.subscribe(*CHANNELS)
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await self.handle_message(message["data"])
                elif message["type"] == "subscribe" and message["data"] == len(CHANNELS):
                    log.info("applied missed events: %s", await apply_missed(self._engine))
                    self.ready.set()
                    log.info("subscribed to %s", ", ".join(CHANNELS))

    async def handle_message(self, data: str) -> None:
        """Провалидировать и применить одно сообщение pub/sub."""
        try:
            event = Event.model_validate_json(data)
            if not await update_event(self._engine, event):
                log.info("event %s: already applied or does not match stock_events", event.event_id)
        except ValidationError as exc:
            log.warning("invalid event: %s", exc)
        except DB_ERRORS:
            # при ошибке базы теряется сообщение
            # TODO: нужен алгоритм доставки необработанных событий
            log.exception("db error while sending event %s", data)
