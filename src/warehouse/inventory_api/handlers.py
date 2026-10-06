import json

from aiohttp import web

from warehouse.core.schemas import EventType
from warehouse.inventory_api import services
from warehouse.inventory_api.keys import ENGINE, REDIS
from warehouse.inventory_api.schemas import Operation
from warehouse.inventory_api.utils import json_error, log, validate


async def handle_operation(request: web.Request, event_type: EventType) -> web.Response:
    """Обработка операции расхода или поступления."""
    try:
        op = validate(Operation, await request.json())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise json_error(web.HTTPBadRequest, "request body must be valid JSON") from exc
    # записать событие в базу
    try:
        event = await services.record_operation(request.app[ENGINE], event_type, op)
    except services.NotEnoughStock as exc:
        raise json_error(
            web.HTTPConflict, "not enough stock", available=exc.available, requested=exc.requested
        ) from exc
    # отправить событие в редис
    # TODO: событие может быть записано в базу, но не отправлено
    try:
        await request.app[REDIS].publish(event.channel, event.model_dump_json())
    except Exception:
        log.exception("publish failed for event %s", event.event_id)

    return web.json_response(event.model_dump(mode="json"), status=201)
