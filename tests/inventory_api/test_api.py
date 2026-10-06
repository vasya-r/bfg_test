import json

import pytest
import sqlalchemy as sa

from warehouse.analytics_worker.aggregates import update_event
from warehouse.core.db.tables import stock_agg, stock_events
from warehouse.core.schemas import CHANNELS, EventType
from warehouse.inventory_api.schemas import Operation
from warehouse.inventory_api.services import record_operation

RECEIPT = {"sku": "A-100", "qty": 50, "warehouse": "WH-1"}


async def _get_events(engine):
    """Возвращает все записи stock_events."""
    query = sa.select(
        stock_events.c.event_type,
        stock_events.c.warehouse,
        stock_events.c.sku,
        stock_events.c.qty,
    ).order_by(stock_events.c.id)
    async with engine.connect() as conn:
        return [tuple(row) for row in await conn.execute(query)]


async def test_receipt_is_stored_and_published(client, engine, redis):
    """Тест сохранения поступления и публикации сообщения в канал.

    Args:
        client: клиент тестового приложения
        engine: движок тестовой бд
        redis: клиент redis
    """
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(*CHANNELS)
        for _ in CHANNELS:
            await pubsub.get_message(timeout=2)

        response = await client.post("/receipts", json=RECEIPT)
        assert response.status == 201
        body = await response.json()

        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)

    assert await _get_events(engine) == [("receipt", "WH-1", "A-100", 50)]
    assert message["channel"] == "inventory.receipt"
    assert json.loads(message["data"]) == body
    assert body == {"event_id": 1, "type": "receipt", **RECEIPT}


async def test_issue_is_published_to_its_channel(client, engine, redis):
    """Тест сохранения расхода и публикации сообщения в канал.

    Args:
        client: клиент тестового приложения
        engine: движок тестовой бд
        redis: клиент redis
    """
    await client.post("/receipts", json=RECEIPT)
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe("inventory.issue")
        await pubsub.get_message(timeout=2)
        response = await client.post("/issues", json={**RECEIPT, "qty": 20})
        assert response.status == 201
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)

    assert json.loads(message["data"])["type"] == "issue"
    assert await _get_events(engine) == [
        ("receipt", "WH-1", "A-100", 50),
        ("issue", "WH-1", "A-100", 20),
    ]


async def test_issue_over_available_stock_is_rejected(client, engine):
    """Тест ситуации, когда остаток на складе меньше, чем расход.

    Args:
        client: клиент тестового приложения
        engine: движок тестовой бд
    """
    await client.post("/receipts", json=RECEIPT)

    response = await client.post("/issues", json={**RECEIPT, "qty": 51})

    assert response.status == 409
    assert await response.json() == {
        "error": "not enough stock",
        "available": 50,
        "requested": 51,
    }
    assert await _get_events(engine) == [("receipt", "WH-1", "A-100", 50)]


async def test_stock_reflects_unapplied_events(client):
    """Тест чтения остатков без воркера: события ещё не попали в stock_agg.

    Args:
        client: клиент тестового приложения
    """
    await client.post("/receipts", json=RECEIPT)
    await client.post("/issues", json={**RECEIPT, "qty": 20})

    response = await client.get("/stock", params={"warehouse": "WH-1"})
    assert await response.json() == {"items": [{"warehouse": "WH-1", "sku": "A-100", "qty": 30}]}

    response = await client.get("/stock/summary")
    assert await response.json() == {
        "warehouses": [{"warehouse": "WH-1", "total_qty": 30, "sku_count": 1}],
        "top_skus": [{"sku": "A-100", "total_qty": 30}],
    }


async def test_stock_matches_available_when_partially_applied(client, engine):
    """Тест остатка, когда часть событий применена воркером, а часть нет.

    Args:
        client: клиент тестового приложения
        engine: движок тестовой бд
    """
    receipt = await record_operation(engine, EventType.RECEIPT, Operation(**RECEIPT))
    await record_operation(engine, EventType.ISSUE, Operation(**{**RECEIPT, "qty": 20}))
    assert await update_event(engine, receipt)

    response = await client.get("/stock", params={"warehouse": "WH-1"})
    assert await response.json() == {"items": [{"warehouse": "WH-1", "sku": "A-100", "qty": 30}]}

    response = await client.post("/issues", json={**RECEIPT, "qty": 31})
    assert response.status == 409
    assert (await response.json())["available"] == 30


@pytest.fixture
async def stock(engine):
    """Остатки в stock_agg для тестов чтения.

    Воркера в этих тестах нет, поэтому строки вставляются напрямую.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.insert(stock_agg),
            [
                {"warehouse": "WH-1", "sku": "A-100", "qty": 30},
                {"warehouse": "WH-1", "sku": "B-200", "qty": 5},
                {"warehouse": "WH-1", "sku": "C-300", "qty": 0},
                {"warehouse": "WH-2", "sku": "A-100", "qty": 10},
                {"warehouse": "WH-2", "sku": "D-400", "qty": 35},
            ],
        )


async def test_summary_top_n(client, stock):
    """Тест сводной статистики."""
    response = await client.get("/stock/summary", params={"top_n": 2})
    assert await response.json() == {
        "warehouses": [
            {"warehouse": "WH-1", "total_qty": 35, "sku_count": 2},
            {"warehouse": "WH-2", "total_qty": 45, "sku_count": 2},
        ],
        "top_skus": [
            {"sku": "A-100", "total_qty": 40},
            {"sku": "D-400", "total_qty": 35},
        ],
    }


async def test_summary_skips_empty_warehouse(client):
    """Тест сводной статистики: склад без остатков в неё не попадает.

    Args:
        client: клиент тестового приложения
    """
    await client.post("/receipts", json=RECEIPT)
    await client.post("/issues", json=RECEIPT)

    response = await client.get("/stock/summary")
    assert await response.json() == {"warehouses": [], "top_skus": []}
