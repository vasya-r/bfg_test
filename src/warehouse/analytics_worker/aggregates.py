import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from warehouse.core.db.tables import signed_qty, stock_agg, stock_events
from warehouse.core.schemas import Event


async def update_event(engine: AsyncEngine, event: Event) -> bool:
    """Обновляет записи в stock_agg."""

    mark_applied = (
        sa.update(stock_events)
        .where(
            stock_events.c.id == event.event_id,
            stock_events.c.event_type == event.type,
            stock_events.c.warehouse == event.warehouse,
            stock_events.c.sku == event.sku,
            stock_events.c.qty == event.qty,
            ~stock_events.c.applied,
        )
        .values(applied=True)
        .returning(
            stock_events.c.warehouse,
            stock_events.c.sku,
            signed_qty().label("delta"),
        )
    )
    async with engine.begin() as conn:
        row = (await conn.execute(mark_applied)).one_or_none()
        if row is None:
            return False
        upsert = (
            pg_insert(stock_agg)
            .values(warehouse=row.warehouse, sku=row.sku, qty=row.delta)
            .on_conflict_do_update(
                index_elements=[stock_agg.c.warehouse, stock_agg.c.sku],
                set_={"qty": stock_agg.c.qty + row.delta, "updated_at": sa.func.now()},
            )
        )
        await conn.execute(upsert)

    return True


async def apply_missed(engine: AsyncEngine) -> int:
    """Применяет все события с applied = false, возвращает их количество."""
    query = sa.select(
        stock_events.c.id.label("event_id"),
        stock_events.c.event_type.label("type"),
        stock_events.c["warehouse", "sku", "qty"],
    ).where(~stock_events.c.applied)
    async with engine.connect() as conn:
        events = [Event(**row) for row in (await conn.execute(query)).mappings()]
    for event in events:
        await update_event(engine, event)

    return len(events)
