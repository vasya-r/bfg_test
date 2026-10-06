from aiohttp import web
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from warehouse.core.config import Settings

SETTINGS = web.AppKey("settings", Settings)
ENGINE = web.AppKey("engine", AsyncEngine)
REDIS = web.AppKey("redis", Redis)
