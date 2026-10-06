import sqlalchemy as sa

from warehouse.core.schemas import EventType

metadata = sa.MetaData()

stock_events = sa.Table(
    "stock_events",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("warehouse", sa.String(64), nullable=False),
    sa.Column("sku", sa.String(64), nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column(
        "event_type",
        sa.Enum(EventType, name="event_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    ),
    sa.Column("applied", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("qty > 0", name="qty_positive"),
    # индекс событий, ещё не попавших в агрегацию
    sa.Index(
        "ix_stock_events_unapplied",
        "warehouse",
        "sku",
        postgresql_where=sa.text("NOT applied"),
    ),
)

stock_agg = sa.Table(
    "stock_agg",
    metadata,
    sa.Column("warehouse", sa.String(64), primary_key=True),
    sa.Column("sku", sa.String(64), primary_key=True),
    sa.Column("qty", sa.BigInteger, nullable=False),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)


def signed_qty(events: sa.FromClause = stock_events) -> sa.ColumnElement[int]:
    """Знак qty в зависимости от операции: поступление с плюсом, расход с минусом."""

    return sa.case(
        (events.c.event_type == EventType.RECEIPT, events.c.qty),
        else_=-events.c.qty,
    )


def current_stock() -> sa.Subquery:
    """Текущий остаток по парам (склад, товар)."""
    applied = sa.select(stock_agg.c["warehouse", "sku", "qty"])
    pending = sa.select(stock_events.c["warehouse", "sku"], signed_qty().label("qty")).where(
        ~stock_events.c.applied
    )
    parts = sa.union_all(applied, pending).subquery("parts")
    qty = sa.cast(sa.func.sum(parts.c.qty), sa.BigInteger).label("qty")

    return (
        sa.select(parts.c["warehouse", "sku"], qty)
        .group_by(*parts.c["warehouse", "sku"])
        .subquery("stock")
    )
