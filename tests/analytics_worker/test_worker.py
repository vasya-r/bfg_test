import asyncio
from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from warehouse.analytics_worker.aggregates import apply_missed, update_event
from warehouse.core.db.tables import stock_agg
from warehouse.core.schemas import EventType
from warehouse.inventory_api.schemas import Operation
from warehouse.inventory_api.services import record_operation


async def wait_for_agg(
    engine: AsyncEngine, expected: list[tuple[str, str, int]], timeout: float = 5.0
) -> None:
    """Дожидается, пока stock_agg станет равным expected."""
    deadline = asyncio.get_running_loop().time() + timeout
    while await agg_rows(engine) != expected:
        if asyncio.get_running_loop().time() > deadline:
            break
        await asyncio.sleep(0.02)
    assert await agg_rows(engine) == expected


async def agg_rows(engine: AsyncEngine) -> Sequence[sa.Row]:
    """Возвращает строки stock_agg, отсортированные по складу и товару."""
    query = sa.select(stock_agg.c.warehouse, stock_agg.c.sku, stock_agg.c.qty).order_by(
        stock_agg.c.warehouse, stock_agg.c.sku
    )
    async with engine.connect() as conn:
        return (await conn.execute(query)).all()


async def test_events_from_api_update_stock_agg(client, engine, worker):
    """Тест создания операций с последующей агрегацией

    Args:
        client: клиент тестового приложения
        engine: движок тестовой бд
        worker: воркер аналитики
    """
    await client.post("/receipts", json={"sku": "A-100", "qty": 50, "warehouse": "WH-1"})
    await client.post("/issues", json={"sku": "A-100", "qty": 20, "warehouse": "WH-1"})
    await client.post("/receipts", json={"sku": "A-100", "qty": 7, "warehouse": "WH-2"})

    await wait_for_agg(engine, [("WH-1", "A-100", 30), ("WH-2", "A-100", 7)])

    response = await client.get("/stock", params={"warehouse": "WH-1", "sku": "A-100"})
    assert (await response.json())["items"] == [{"warehouse": "WH-1", "sku": "A-100", "qty": 30}]


async def test_event_applied_twice_is_counted_once(engine):
    """Тест повторного обновления одного события.

    Через pub/sub не получится, так как стоит ограничение,
    делаем прямым вызовом update_event().

    Args:
        engine: движок тестовой бд
    """
    operations = [
        (EventType.RECEIPT, Operation(sku="A-100", qty=50, warehouse="WH-1")),
        (EventType.ISSUE, Operation(sku="A-100", qty=20, warehouse="WH-1")),
        (EventType.RECEIPT, Operation(sku="A-100", qty=7, warehouse="WH-2")),
    ]
    events = [await record_operation(engine, event_type, op) for event_type, op in operations]

    for event in events:
        assert await update_event(engine, event)
    for event in events:
        assert not await update_event(engine, event)

    assert await agg_rows(engine) == [("WH-1", "A-100", 30), ("WH-2", "A-100", 7)]
