import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from collector import CollectionResult
from domain import Category, RawNews
from pipeline import NewsPipeline
from repositories import MemoryRepository


class EmptyCollector:
    async def collect(self):
        return CollectionResult()


def make_news():
    return RawNews(
        url="https://source.test/news",
        title="Panel news",
        summary="Summary",
        content="Complete source content.",
        source="Source",
        source_category=Category.AI,
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )


def make_panel():
    repository = MemoryRepository()
    record = asyncio.run(repository.insert_news(1, make_news()))
    asyncio.run(repository.save_draft(record.id, "Generated text", ["Fact"]))
    pipeline = NewsPipeline(repository, EmptyCollector())
    settings = SimpleNamespace(
        admin_password="1234",
        session_secret="test-secret-with-enough-length",
        cookie_secure=False,
    )
    return TestClient(create_app(settings, repository, pipeline)), repository, record.id


def login(client):
    client.post("/login", data={"password": "1234"})
    return client.get("/").json()["csrf_token"]


def test_state_changing_route_rejects_missing_csrf():
    client, _, _ = make_panel()
    with client:
        login(client)
        response = client.post("/collect")

    assert response.status_code == 403


def test_approve_changes_state_without_external_publish():
    client, repository, news_id = make_panel()
    with client:
        csrf_token = login(client)
        response = client.post(
            f"/news/{news_id}/approve",
            data={"csrf_token": csrf_token, "edited_text": "Editor text"},
            follow_redirects=False,
        )

    saved = asyncio.run(repository.get_news(news_id))
    assert response.status_code == 303
    assert saved.draft_text == "Editor text"
    assert saved.external_post_id is None


def test_news_detail_requires_login_and_returns_record():
    client, _, news_id = make_panel()
    with client:
        anonymous = client.get(f"/news/{news_id}", follow_redirects=False)
        login(client)
        authenticated = client.get(f"/news/{news_id}")

    assert anonymous.status_code == 303
    assert authenticated.json()["title"] == "Panel news"
