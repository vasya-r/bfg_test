import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from warehouse.core.db.tables import current_stock, stock_events
from warehouse.core.schemas import Event, EventType
from warehouse.inventory_api.schemas import Operation


class NotEnoughStock(Exception):
    """Ошибка операции - расход превышает доступный остаток."""

    def __init__(self, available: int, requested: int) -> None:
        super().__init__(f"not enough stock: available {available}, requested {requested}")
        self.available = available
        self.requested = requested


async def _get_rows(conn: AsyncConnection, query: sa.Select) -> list[dict]:
    """Запрос на чтение в соединении и возврат строки в виде словаря."""
    result = await conn.execute(query)
    return [dict(row) for row in result.mappings()]


async def _fetch_all(engine: AsyncEngine, query: sa.Select) -> list[dict]:
    """Выполняет запрос на чтение и возвращает строку в виде словаря."""
    async with engine.connect() as conn:
        return await _get_rows(conn, query)


async def _lock_pair(conn: AsyncConnection, warehouse: str, sku: str) -> None:
    """Блокировка пары (warehouse, sku) до конца транзакции."""
    key = sa.func.hashtextextended(f"{warehouse}:{sku}", 0)
    await conn.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))


async def _get_available(conn: AsyncConnection, warehouse: str, sku: str) -> int:
    """
    Возвращает текущий остаток пары (warehouse, sku)

    Args:
        conn: открытое подключение к бд
        warehouse: склад
        sku: товар
    """
    stock = current_stock()
    query = sa.select(stock.c.qty).where(stock.c.warehouse == warehouse, stock.c.sku == sku)

    return (await conn.execute(query)).scalar_one_or_none() or 0


async def record_operation(engine: AsyncEngine, event_type: EventType, op: Operation) -> Event:
    """
    Записывает событие и возвращает его для публикации

    Args:
        engine: движок бд
        event_type: тип операции (приход/расход)
        op: тело запроса
    """
    fields = op.model_dump()
    insert = (
        sa.insert(stock_events).values(event_type=event_type, **fields).returning(stock_events.c.id)
    )
    async with engine.begin() as conn:
        if event_type == EventType.ISSUE:
            await _lock_pair(conn, op.warehouse, op.sku)
            available = await _get_available(conn, op.warehouse, op.sku)
            if available < op.qty:
                raise NotEnoughStock(available, op.qty)
        row = (await conn.execute(insert)).one()

    return Event(event_id=row.id, type=event_type, **fields)


async def get_stock(engine: AsyncEngine, warehouse: str, sku: str | None = None) -> list[dict]:
    """
    Возвращает остатки на складе

    Args:
        engine: движок бд
        warehouse: склад
        sku: товар
    """
    stock = current_stock()
    # (товар с нулевым остатком не считается лежащим на складе)
    query = (
        sa.select(stock.c.warehouse, stock.c.sku, stock.c.qty)
        .where(stock.c.warehouse == warehouse, stock.c.qty > 0)
        .order_by(stock.c.sku)
    )
    if sku is not None:
        query = query.where(stock.c.sku == sku)

    return await _fetch_all(engine, query)


async def get_summary(
    engine: AsyncEngine, top_n: int, warehouse: str | None = None, sku: str | None = None
) -> dict:
    """
    Возвращает сводную статистику по складам

    Args:
        engine: движок бд
        top_n: максимальный размер списка товаров с наибольшим остатком)
        warehouse: склад
        sku: товар
    """
    stock = current_stock()
    # товар с нулевым остатком не удаляется из истории, но не считается лежащим на складе
    filters = [stock.c.qty > 0]
    if warehouse is not None:
        filters.append(stock.c.warehouse == warehouse)
    if sku is not None:
        filters.append(stock.c.sku == sku)

    # приводим numeric к bigint
    total_qty = sa.cast(sa.func.sum(stock.c.qty), sa.BigInteger).label("total_qty")
    sku_count = sa.func.count().label("sku_count")

    # считаем по всем складам: суммарный остаток и число SKU в наличии.
    warehouses = (
        sa.select(stock.c.warehouse, total_qty, sku_count)
        .where(*filters)
        .group_by(stock.c.warehouse)
        .order_by(stock.c.warehouse)
    )
    # получаем суммарный остаток каждого товара на выбранных складах
    per_sku = (
        sa.select(stock.c.sku, total_qty).where(*filters).group_by(stock.c.sku).subquery("per_sku")
    )
    # выборка из TOP_N товаров с наибольшим остатком
    top_skus = sa.select(per_sku).order_by(per_sku.c.total_qty.desc(), per_sku.c.sku).limit(top_n)
    # изменим уровень изоляции, чтобы оба запроса видели склад в один момент времени
    snapshot = engine.execution_options(isolation_level="REPEATABLE READ")
    async with snapshot.connect() as conn:
        return {
            "warehouses": await _get_rows(conn, warehouses),
            "top_skus": await _get_rows(conn, top_skus),
        }
