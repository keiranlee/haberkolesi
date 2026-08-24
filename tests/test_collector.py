import asyncio
from pathlib import Path

import pytest

from collector import FetchError, FetchResponse, RssCollector
from domain import Category


RSS_FIXTURE = Path("tests/fixtures/rss_sample.xml").read_bytes()


class FakeHttpClient:
    def __init__(self):
        self.responses = {}
        self.calls = []

    def add(self, url, body, status=200, final_url=None):
        self.responses[url] = FetchResponse(
            status=status,
            body=body,
            final_url=final_url or url,
        )

    def fail(self, url, status):
        self.responses[url] = FetchError(url=url, status_code=status, message="failed")

    async def get(self, url):
        self.calls.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def extract_article(html):
    text = html.decode("utf-8")
    return text.replace("<article><p>", "").replace("</p></article>", "")


class ConcurrentFeedHttp(FakeHttpClient):
    def __init__(self):
        super().__init__()
        self.feed_started = 0
        self.both_feeds_started = asyncio.Event()

    async def get(self, url):
        if url.endswith("/feed"):
            self.feed_started += 1
            if self.feed_started == 2:
                self.both_feeds_started.set()
            await asyncio.wait_for(self.both_feeds_started.wait(), timeout=0.2)
        return await super().get(url)


@pytest.mark.asyncio
async def test_collect_parses_feed_and_extracts_article():
    http = FakeHttpClient()
    http.add("https://source.test/feed", RSS_FIXTURE)
    http.add(
        "https://source.test/news",
        b"<article><p>Long source content.</p></article>",
    )
    collector = RssCollector(
        feeds={Category.AI: ["https://source.test/feed"]},
        http=http,
        article_extractor=extract_article,
    )

    result = await collector.collect()

    assert result.errors == []
    assert result.items[0].title == "Sample AI news"
    assert result.items[0].content == "Long source content."
    assert result.items[0].source_category is Category.AI


@pytest.mark.asyncio
async def test_collect_fetches_independent_feeds_concurrently():
    http = ConcurrentFeedHttp()
    for category in ("ai", "tech"):
        http.add(f"https://{category}.test/feed", RSS_FIXTURE)
    http.add(
        "https://source.test/news",
        b"<article><p>Long source content.</p></article>",
    )
    collector = RssCollector(
        feeds={
            Category.AI: ["https://ai.test/feed"],
            Category.TEKNOLOJI: ["https://tech.test/feed"],
        },
        http=http,
        article_extractor=extract_article,
    )

    result = await collector.collect()

    assert len(result.items) == 2
    assert http.feed_started == 2


@pytest.mark.asyncio
async def test_one_broken_source_does_not_stop_other_sources():
    http = FakeHttpClient()
    http.fail("https://broken.test/feed", 403)
    http.add("https://source.test/feed", RSS_FIXTURE)
    http.add(
        "https://source.test/news",
        b"<article><p>Long source content.</p></article>",
    )
    collector = RssCollector(
        feeds={
            Category.AI: ["https://broken.test/feed", "https://source.test/feed"]
        },
        http=http,
        article_extractor=extract_article,
    )

    result = await collector.collect()

    assert len(result.items) == 1
    assert result.errors[0].status_code == 403
    assert result.errors[0].url == "https://broken.test/feed"


@pytest.mark.asyncio
async def test_article_failure_skips_item_and_records_error():
    http = FakeHttpClient()
    http.add("https://source.test/feed", RSS_FIXTURE)
    http.fail("https://source.test/news", 503)
    collector = RssCollector(
        feeds={Category.AI: ["https://source.test/feed"]},
        http=http,
        article_extractor=extract_article,
    )

    result = await collector.collect()

    assert result.items == []
    assert result.errors[0].status_code == 503


@pytest.mark.asyncio
async def test_article_extractor_failure_isolated_to_entry():
    http = FakeHttpClient()
    http.add("https://source.test/feed", RSS_FIXTURE)
    http.add("https://source.test/news", b"broken article")

    def broken_extractor(_):
        raise ValueError("parser crashed")

    collector = RssCollector(
        feeds={Category.AI: ["https://source.test/feed"]},
        http=http,
        article_extractor=broken_extractor,
    )

    result = await collector.collect()

    assert result.items == []
    assert result.errors[0].url == "https://source.test/news"
    assert "parser crashed" in result.errors[0].message


def test_default_feed_mapping_converts_legacy_category_names():
    feeds = RssCollector.normalized_feeds(
        {
            "Startup": ["https://startup.test/feed"],
            "AI": ["https://ai.test/feed"],
            "Teknoloji": ["https://tech.test/feed"],
            "Yazilim": ["https://software.test/feed"],
        }
    )

    assert set(feeds) == {
        Category.GIRISIM,
        Category.AI,
        Category.TEKNOLOJI,
        Category.YAZILIM,
    }
