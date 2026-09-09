from datetime import datetime, timezone

from domain import Category
from schedule import PUBLISHING_SLOTS, PublishingSlot, next_slot, slot_for


def test_schedule_maps_only_the_six_daily_publishing_hours():
    assert [(slot.hour, slot.category) for slot in PUBLISHING_SLOTS] == [
        (10, Category.GIRISIM),
        (12, Category.AI),
        (14, Category.TEKNOLOJI),
        (16, Category.AI),
        (18, Category.YAZILIM),
        (20, Category.GIRISIM),
    ]
    assert slot_for(12).category is Category.AI
    assert slot_for(11) is None


def test_next_slot_uses_istanbul_time_and_wraps_after_last_daily_slot():
    before_first = datetime(2026, 9, 9, 6, 30, tzinfo=timezone.utc)  # 09:30 Istanbul
    between_slots = datetime(2026, 9, 9, 10, 30, tzinfo=timezone.utc)  # 13:30 Istanbul
    after_last = datetime(2026, 9, 9, 18, 30, tzinfo=timezone.utc)  # 21:30 Istanbul

    assert next_slot(before_first) == PublishingSlot(10, Category.GIRISIM)
    assert next_slot(between_slots) == PublishingSlot(14, Category.TEKNOLOJI)
    assert next_slot(after_last) == PublishingSlot(10, Category.GIRISIM)
