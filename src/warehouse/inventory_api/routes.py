from aiohttp import web

from warehouse.core.schemas import EventType
from warehouse.inventory_api import services
from warehouse.inventory_api.handlers import handle_operation
from warehouse.inventory_api.keys import ENGINE
from warehouse.inventory_api.schemas import StockModel, SummaryModel
from warehouse.inventory_api.utils import validate

routes = web.RouteTableDef()


@routes.post("/receipts")
async def post_receipt(request: web.Request) -> web.Response:
    """Добавить поступление."""
    return await handle_operation(request, EventType.RECEIPT)


@routes.post("/issues")
async def post_issue(request: web.Request) -> web.Response:
    """Добавить расход."""
    return await handle_operation(request, EventType.ISSUE)


@routes.get("/stock")
async def get_stock(request: web.Request) -> web.Response:
    """Получить остатки на складе."""
    params = validate(StockModel, dict(request.query))
    items = await services.get_stock(request.app[ENGINE], params.warehouse, params.sku)

    return web.json_response({"items": items})


@routes.get("/stock/summary")
async def get_stock_summary(request: web.Request) -> web.Response:
    """Получить сводную статистику по складам и топ sku."""
    params = validate(SummaryModel, dict(request.query))
    summary = await services.get_summary(
        request.app[ENGINE], params.top_n, params.warehouse, params.sku
    )

    return web.json_response(summary)


@routes.get("/health")
async def health(request: web.Request) -> web.Response:
    """healthcheck."""
    return web.json_response({"status": "ok"})
