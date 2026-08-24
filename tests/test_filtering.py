from datetime import datetime, timedelta, timezone

from domain import Category, RawNews
from filtering import normalize_url, select_candidates


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def make_news(
    index: int,
    category: Category = Category.AI,
    *,
    published_at: datetime = NOW,
    url: str = "",
    title: str = "",
) -> RawNews:
    return RawNews(
        url=url or f"https://source.test/news-{category.value}-{index}",
        title=title or f"{category.value} story {index}",
        summary=f"Summary {index}",
        content=f"Full source content {index}",
        source="Source",
        source_category=category,
        published_at=published_at,
    )


def test_normalize_url_removes_tracking_fragment_and_extra_slash():
    url = "https://Example.com/a/?utm_source=rss&x=1&fbclid=nope#top"

    assert normalize_url(url) == "https://example.com/a?x=1"


def test_select_candidates_deduplicates_and_caps_each_category():
    items = [make_news(i, Category.AI) for i in range(7)]
    items += [make_news(i, Category.GIRISIM) for i in range(6)]

    selected = select_candidates(
        items,
        now=NOW,
        max_age=timedelta(hours=24),
        per_category=5,
    )

    assert sum(item.source_category is Category.AI for item in selected) == 5
    assert sum(item.source_category is Category.GIRISIM for item in selected) == 5


def test_select_candidates_discards_old_and_undated_news():
    items = [
        make_news(1, published_at=NOW - timedelta(hours=24, seconds=1)),
        make_news(2, published_at=None),
        make_news(3, published_at=NOW - timedelta(hours=23)),
    ]

    selected = select_candidates(items, now=NOW, max_age=timedelta(hours=24))

    assert [item.title for item in selected] == ["AI story 3"]


def test_select_candidates_deduplicates_normalized_url_and_title():
    items = [
        make_news(1, url="https://source.test/story?utm_campaign=rss", title="Big AI News"),
        make_news(2, url="https://source.test/story", title="Different title"),
        make_news(3, url="https://other.test/story", title="  BIG   ai news "),
    ]

    selected = select_candidates(items, now=NOW, max_age=timedelta(hours=24))

    assert len(selected) == 1
    assert selected[0].title == "Big AI News"


def test_select_candidates_orders_newest_first_deterministically():
    items = [
        make_news(1, published_at=NOW - timedelta(hours=2)),
        make_news(2, published_at=NOW - timedelta(hours=1)),
    ]

    selected = select_candidates(items, now=NOW, max_age=timedelta(hours=24))

    assert [item.title for item in selected] == ["AI story 2", "AI story 1"]
