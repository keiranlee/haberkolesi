import asyncio
import re
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
    html = client.get("/").text
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


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
    assert "Panel news" in authenticated.text


def test_dashboard_shows_queue_filters_and_schedule():
    client, _, _ = make_panel()
    with client:
        login(client)
        html = client.get("/").text

    assert "Gemini kuyruğu" in html
    assert "Sonraki istek" in html
    assert 'name="category"' in html
    assert "10:00" in html
    assert "20:00" in html


def test_detail_shows_original_and_generated_text():
    client, _, news_id = make_panel()
    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text

    assert "Orijinal haber" in html
    assert "Devosuit metni" in html
    assert "Generated text" in html
    assert "Görsel sonraki aşamada" in html
    assert "X yayını kapalı" in html


def test_dashboard_shows_running_collection_without_stealing_focus():
    client, repository, _ = make_panel()
    asyncio.run(repository.create_batch())

    with client:
        login(client)
        html = client.get("/").text

    assert "Haberler çekiliyor" in html
    assert 'http-equiv="refresh"' not in html
    assert "Durumu yenile" in html
    assert "disabled" in html


def test_dashboard_exposes_command_center_navigation_and_operational_summary():
    client, _, _ = make_panel()

    with client:
        login(client)
        html = client.get("/").text

    assert 'aria-label="Ana navigasyon"' in html
    assert "Operasyon özeti" in html
    assert "Aktif AI kuyruğu" in html
    assert "Hazır taslak" in html
    assert "Yayın akışı" in html


def test_dashboard_uses_localized_editorial_state_labels():
    client, _, _ = make_panel()

    with client:
        login(client)
        html = client.get("/").text

    assert "Taslak hazır" in html
    assert ">drafted<" not in html


def test_detail_is_an_editorial_workspace_with_bounded_composer():
    client, _, news_id = make_panel()

    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text

    assert "İçerik istihbaratı" in html
    assert 'aria-label="Haber işlem adımları"' in html
    assert 'maxlength="240"' in html
    assert "Yayın taslağı" in html
    assert 'href="/#news" aria-current="page"' in html


def test_login_explains_the_editorial_workflow():
    client, _, _ = make_panel()

    with client:
        html = client.get("/login").text

    assert "Haberden yayına" in html
    assert "Topla" in html
    assert "Puanla" in html
    assert "Hazırla" in html


def test_unscored_news_does_not_offer_a_broken_prepare_action():
    client, repository, _ = make_panel()
    unscored = asyncio.run(
        repository.insert_news(
            2,
            RawNews(
                url="https://source.test/unscored",
                title="Unscored news",
                summary="Summary",
                content="Complete unscored source content.",
                source="Source",
                source_category=Category.AI,
                published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            ),
        )
    )

    with client:
        login(client)
        html = client.get(f"/news/{unscored.id}").text

    assert "Puanlama tamamlanınca metin hazırlanabilir" in html
    assert f'action="/news/{unscored.id}/prepare"' not in html


def test_finalized_news_is_read_only():
    client, repository, news_id = make_panel()
    asyncio.run(repository.approve(news_id, "Approved editor text"))

    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text

    assert "Onaylanmış metin" in html
    assert f'action="/news/{news_id}/regenerate"' not in html
    assert f'action="/news/{news_id}/reject"' not in html
    assert f'action="/news/{news_id}/approve"' not in html


def test_dashboard_and_detail_expose_mobile_and_keyboard_context():
    client, _, news_id = make_panel()

    with client:
        login(client)
        dashboard = client.get("/").text
        detail = client.get(f"/news/{news_id}").text

    assert 'data-label="Kategori"' in dashboard
    assert 'data-label="AI puanı"' in dashboard
    assert 'tabindex="0" aria-label="Orijinal haber metni"' in detail


def test_detail_displays_source_time_in_istanbul_timezone():
    client, _, news_id = make_panel()

    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text

    assert "24.08.2026 · 03:00" in html


def test_draft_actions_explain_quota_and_confirm_rejection():
    client, _, news_id = make_panel()

    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text

    assert "Yeniden üretmek 1 Gemini isteği kullanır" in html
    assert 'onsubmit="return confirm(' in html
