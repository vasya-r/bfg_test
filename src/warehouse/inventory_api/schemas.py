from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class Operation(BaseModel):
    """Тело запроса POST /receipts и POST /issues."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sku: Annotated[str, Field(min_length=1, max_length=64)]
    warehouse: Annotated[str, Field(min_length=1, max_length=64)]
    qty: int = Field(gt=0, le=1_000_000_000, strict=True)


class StockModel(BaseModel):
    """Параметры запроса GET /stock."""

    model_config = ConfigDict(str_strip_whitespace=True)

    warehouse: Annotated[str, Field(min_length=1, max_length=64)]
    sku: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class SummaryModel(BaseModel):
    """Параметры запроса GET /stock/summary."""

    model_config = ConfigDict(str_strip_whitespace=True)

    top_n: int = Field(default=5, ge=1, le=100)
    warehouse: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    sku: Annotated[str, Field(min_length=1, max_length=64)] | None = None
