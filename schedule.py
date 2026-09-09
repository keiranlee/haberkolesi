"""Single source of truth for Istanbul-time content preparation slots."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from domain import Category


ISTANBUL = ZoneInfo("Europe/Istanbul")


@dataclass(frozen=True)
class PublishingSlot:
    hour: int
    category: Category


PUBLISHING_SLOTS: Tuple[PublishingSlot, ...] = (
    PublishingSlot(10, Category.GIRISIM),
    PublishingSlot(12, Category.AI),
    PublishingSlot(14, Category.TEKNOLOJI),
    PublishingSlot(16, Category.AI),
    PublishingSlot(18, Category.YAZILIM),
    PublishingSlot(20, Category.GIRISIM),
)


def slot_for(hour: int) -> Optional[PublishingSlot]:
    return next((slot for slot in PUBLISHING_SLOTS if slot.hour == hour), None)


def next_slot(now: datetime) -> PublishingSlot:
    if now.tzinfo is None:
        raise ValueError("next_slot requires a timezone-aware datetime")
    local_now = now.astimezone(ISTANBUL)
    for slot in PUBLISHING_SLOTS:
        scheduled_today = local_now.replace(
            hour=slot.hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if local_now < scheduled_today:
            return slot
    return PUBLISHING_SLOTS[0]
