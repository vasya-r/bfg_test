import json
import logging
from typing import TypeVar

from aiohttp import web
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__package__)

Model = TypeVar("Model", bound=BaseModel)


def json_error(error_type: type[web.HTTPError], message: str, **extra: object) -> web.HTTPError:
    """HTTP-ошибка с JSON-телом (код, сообщение) и доп. полями."""
    body = {"code": error_type.status_code, "error": message, **extra}
    return error_type(text=json.dumps(body), content_type="application/json")


@web.middleware
async def error_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Обработка ошибок."""
    try:
        return await handler(request)
    except web.HTTPError as exc:
        if exc.content_type == "application/json":
            raise
        error = exc
    except Exception:
        log.exception("unhandled error")
        error = web.HTTPInternalServerError()
    # сохраняем заголовки исходной ошибки
    headers = {
        name: value
        for name, value in error.headers.items()
        if name.lower() not in ("content-type", "content-length")
    }
    body = {"code": error.status, "error": error.reason.lower()}
    return web.json_response(body, status=error.status, headers=headers)


def validate(model: type[Model], data: object) -> Model:
    """Валидация данных модели."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = exc.errors(include_url=False, include_context=False, include_input=False)
        raise json_error(web.HTTPUnprocessableEntity, "validation error", details=details) from exc
