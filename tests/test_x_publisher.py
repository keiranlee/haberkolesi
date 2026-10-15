"""Tests for official X publisher service and endpoint."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app import create_app
from domain import Category, NewsRecord, NewsState, RawNews
from pipeline import NewsPipeline
from repositories import MemoryRepository
from schedule import PublishingSlot
from x_publisher import (
    OfficialXClient,
    XAuthError,
    XNotConfiguredError,
    XPublishError,
    XPublisher,
    XRateLimitedError,
)


class DummyEmptyCollector:
    async def collect(self, category=None):
        from collector import CollectionResult

        return CollectionResult()


class MockTweepyClient:
    def __init__(self, should_fail: Optional[Exception] = None, tweet_id: str = "123456789"):
        self.should_fail = should_fail
        self.tweet_id = tweet_id
        self.called_with = None

    async def post(self, text: str, image_path: Optional[str] = None) -> str:
        if self.should_fail:
            raise self.should_fail
        self.called_with = {"text": text, "image_path": image_path}
        return self.tweet_id

    async def reset_session(self):
        pass


def make_raw_news(category=Category.AI, title="AI News", url: Optional[str] = None) -> RawNews:
    return RawNews(
        url=url or f"https://example.com/news-{title.lower().replace(' ', '-')}",
        title=title,
        summary="Summary",
        content="Content",
        source="Source",
        source_category=category,
        published_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
    )


def test_official_x_client_configuration():
    client = OfficialXClient(
        api_key="key",
        api_key_secret="secret",
        access_token="token",
        access_token_secret="token_secret",
    )
    assert client.configured is True

    unconfigured = OfficialXClient(
        api_key="",
        api_key_secret="secret",
        access_token="token",
        access_token_secret="token_secret",
    )
    assert unconfigured.configured is False


@pytest.mark.asyncio
async def test_x_publisher_publishes_approved_news():
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_raw_news())
    await repo.save_draft(record.id, "Draft text", ["Fact 1"], platform_texts={"x": "X text"})
    await repo.approve(record.id, "Approved X text")

    mock_client = MockTweepyClient(tweet_id="99887766")
    publisher = XPublisher(repo, mock_client, daily_limit=5)

    tweet_id = await publisher.publish_news(record.id)
    assert tweet_id == "99887766"
    assert mock_client.called_with["text"] == "Approved X text"

    updated = await repo.get_news(record.id)
    assert updated.external_post_id == "99887766"
    assert updated.x_published_at is not None

    actions = [a.action for a in repo.editor_actions if a.news_id == record.id]
    assert "publish_x" in actions


@pytest.mark.asyncio
async def test_x_publisher_rejects_unapproved_or_already_published():
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_raw_news())
    await repo.save_draft(record.id, "Draft text", ["Fact 1"])

    mock_client = MockTweepyClient()
    publisher = XPublisher(repo, mock_client)

    # Drafted state (not approved yet)
    with pytest.raises(ValueError, match="Yalnız onaylanmış"):
        await publisher.publish_news(record.id)

    # Approve and publish
    await repo.approve(record.id, "Approved text")
    await publisher.publish_news(record.id)

    # Cannot publish again
    with pytest.raises(ValueError, match="zaten X'te paylaşıldı"):
        await publisher.publish_news(record.id)


@pytest.mark.asyncio
async def test_x_publisher_respects_daily_limit():
    repo = MemoryRepository()
    mock_client = MockTweepyClient()
    publisher = XPublisher(repo, mock_client, daily_limit=1)

    r1 = await repo.insert_news(1, make_raw_news(title="News 1"))
    await repo.save_draft(r1.id, "Draft 1", [])
    await repo.approve(r1.id, "Approve 1")
    await publisher.publish_news(r1.id)

    r2 = await repo.insert_news(1, make_raw_news(title="News 2"))
    await repo.save_draft(r2.id, "Draft 2", [])
    await repo.approve(r2.id, "Approve 2")

    with pytest.raises(XPublishError, match="Günlük X paylaşım limiti doldu"):
        await publisher.publish_news(r2.id)


@pytest.mark.asyncio
async def test_x_publisher_records_failure_on_error():
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_raw_news())
    await repo.save_draft(record.id, "Draft", [])
    await repo.approve(record.id, "Approve")

    mock_client = MockTweepyClient(should_fail=XPublishError("Twitter 500 Server Error"))
    publisher = XPublisher(repo, mock_client)

    with pytest.raises(XPublishError):
        await publisher.publish_news(record.id)

    updated = await repo.get_news(record.id)
    assert updated.x_published_at is None
    assert updated.x_publish_attempts == 1
    assert "Twitter 500" in updated.x_last_error


@pytest.mark.asyncio
async def test_x_publisher_scheduled_picks_candidate_without_raising():
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_raw_news(category=Category.AI))
    await repo.save_draft(record.id, "Draft", [])
    await repo.approve(record.id, "Approve AI")

    mock_client = MockTweepyClient(tweet_id="112233")
    publisher = XPublisher(repo, mock_client, jitter_seconds=(0, 0))

    slot = PublishingSlot(12, Category.AI)
    tweet_id = await publisher.publish_scheduled(slot)
    assert tweet_id == "112233"

    # Running again when no candidates left returns None safely
    tweet_id2 = await publisher.publish_scheduled(slot)
    assert tweet_id2 is None


def test_publish_x_web_endpoint():
    repo = MemoryRepository()
    record = asyncio.run(repo.insert_news(1, make_raw_news()))
    asyncio.run(repo.save_draft(record.id, "Draft", []))
    asyncio.run(repo.approve(record.id, "Approved text"))

    mock_client = MockTweepyClient(tweet_id="554433")
    publisher = XPublisher(repo, mock_client)
    pipeline = NewsPipeline(repo, DummyEmptyCollector())
    settings = SimpleNamespace(
        admin_password="1234",
        session_secret="test-secret-with-enough-length",
        cookie_secure=False,
    )
    app = create_app(settings, repo, pipeline, x_publisher=publisher)
    client = TestClient(app)

    # Login
    client.post("/login", data={"password": "1234"})
    html = client.get("/").text
    import re
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    # Publish via POST
    response = client.post(
        f"/news/{record.id}/publish-x",
        data={"csrf_token": csrf},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "X'te paylaşıldı" in response.text
    assert "554433" in response.text
