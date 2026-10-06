import enum

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, enum.Enum):
    """Тип события."""

    RECEIPT = "receipt"  # поступление
    ISSUE = "issue"  # расход


# каналы для pub/sub
CHANNEL_RECEIPT = "inventory.receipt"
CHANNEL_ISSUE = "inventory.issue"
CHANNELS = (CHANNEL_RECEIPT, CHANNEL_ISSUE)

_CHANNEL_BY_TYPE = {
    EventType.RECEIPT: CHANNEL_RECEIPT,
    EventType.ISSUE: CHANNEL_ISSUE,
}


class Event(BaseModel):
    """Схема сообщения, отправляемого в redis."""

    model_config = ConfigDict(extra="ignore")

    event_id: int = Field(gt=0)
    type: EventType
    warehouse: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(gt=0)

    @property
    def channel(self) -> str:
        """Канал redis, соответствующий типу события."""
        return _CHANNEL_BY_TYPE[self.type]
