import asyncio
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import create_app
from collector import CollectionResult
from domain import Category, RawNews
from pipeline import NewsPipeline
from repositories import MemoryRepository
from schedule import PublishingSlot


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


def make_panel(content_runner=None):
    repository = MemoryRepository()
    record = asyncio.run(repository.insert_news(1, make_news()))
    asyncio.run(repository.save_draft(record.id, "Generated text", ["Fact"]))
    pipeline = NewsPipeline(repository, EmptyCollector())
    settings = SimpleNamespace(
        admin_password="1234",
        session_secret="test-secret-with-enough-length",
        cookie_secure=False,
    )
    return (
        TestClient(
            create_app(
                settings,
                repository,
                pipeline,
                content_runner=content_runner,
            )
        ),
        repository,
        record.id,
    )


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


def test_dashboard_offers_immediate_test_for_the_next_scheduled_category():
    runner = RecordingContentRunner()
    client, _, _ = make_panel(content_runner=runner)

    with client:
        login(client)
        html = client.get("/").text

    assert 'action="/content/test-next-slot"' in html
    assert "Sıradaki kategoriyi şimdi test et" in html
    assert "1 Gemini isteği" in html


def test_next_slot_test_route_requires_csrf_and_starts_runner():
    runner = RecordingContentRunner()
    client, _, _ = make_panel(content_runner=runner)

    with client:
        login(client)
        forbidden = client.post("/content/test-next-slot")
        csrf_token = login(client)
        accepted = client.post(
            "/content/test-next-slot",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )

    assert forbidden.status_code == 403
    assert accepted.status_code == 303
    assert len(runner.slots) == 1
    assert isinstance(runner.slots[0], PublishingSlot)


def test_manual_test_run_does_not_change_scheduled_timeline_state():
    client, repository, _ = make_panel(content_runner=RecordingContentRunner())
    local_now = datetime.now(ZoneInfo("Europe/Istanbul")).replace(
        hour=20, minute=30, second=0, microsecond=0
    )
    run = asyncio.run(
        repository.claim_content_run(
            "test:manual:Girisim",
            local_now,
            Category.GIRISIM,
        )
    )
    asyncio.run(repository.complete_content_run(run.id, None))

    with client:
        login(client)
        html = client.get("/").text

    assert re.search(
        r'<li class="slot-pending"><time>20:00</time>.*?<strong>Girişim</strong>',
        html,
    )


class RecordingContentRunner:
    def __init__(self):
        self.slots = []

    async def run_test_slot(self, slot):
        self.slots.append(slot)


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


def test_regenerate_ajax_returns_job_status_without_immediate_page_redirect():
    client, _, news_id = make_panel()

    with client:
        csrf_token = login(client)
        response = client.post(
            f"/news/{news_id}/regenerate",
            data={"csrf_token": csrf_token},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        payload = response.json()
        status = client.get(f"/ai-jobs/{payload['job_id']}")

    assert response.status_code == 202
    assert payload["news_id"] == news_id
    assert status.status_code == 200
    assert status.json()["state"] == "pending"


def test_detail_loads_regeneration_progress_script():
    client, _, news_id = make_panel()

    with client:
        login(client)
        html = client.get(f"/news/{news_id}").text
        script = client.get("/static/news_detail.js")

    assert 'class="regenerate-form"' in html
    assert "/static/news_detail.js" in html
    assert script.status_code == 200
    assert "Yeni metin hazırlanıyor" in script.text


def test_dashboard_includes_live_update_client_script_and_containers():
    client, _, _ = make_panel()

    with client:
        login(client)
        html = client.get("/").text
        js = client.get("/static/dashboard.js")

    assert 'id="live-state"' in html
    assert 'id="news-container"' in html
    assert "/static/dashboard.js" in html
    assert js.status_code == 200
    assert "applyUpdate" in js.text
    assert "bindCollectForm" in js.text


def test_dashboard_lists_ready_copy_and_image_before_collected_candidates():
    client, repository, ready_id = make_panel()
    asyncio.run(repository.save_image(ready_id, "/tmp/devosuit-ready.png"))
    asyncio.run(
        repository.insert_news(
            2,
            RawNews(
                url="https://source.test/newer-collected",
                title="Collected candidate",
                summary="Summary",
                content="Complete source content.",
                source="Source",
                source_category=Category.AI,
                published_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            ),
        )
    )

    with client:
        login(client)
        html = client.get("/").text

    assert "Paylaşıma hazır" in html
    assert f'src="/news/{ready_id}/image"' in html
    assert html.index("Generated text") < html.index("Collected candidate")


def test_dashboard_renders_clear_pool_form():
    client, _, _ = make_panel()

    with client:
        login(client)
        html = client.get("/").text

    assert 'action="/news/clear-unready"' in html
    assert "Havuzu Temizle" in html


def test_clear_unready_news_endpoint():
    client, repository, ready_id = make_panel()
    # ready_id has draft_text from make_panel, add image_path so it is fully ready
    asyncio.run(repository.save_image(ready_id, "/tmp/ready.png"))

    # Add an unready collected candidate
    asyncio.run(
        repository.insert_news(
            2,
            RawNews(
                url="https://source.test/unready",
                title="Unready candidate",
                summary="Summary",
                content="Content",
                source="Source",
                source_category=Category.AI,
                published_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            ),
        )
    )

    with client:
        csrf_token = login(client)
        response = client.post(
            "/news/clear-unready",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert asyncio.run(repository.count_news()) == 1
    assert asyncio.run(repository.get_news(ready_id)) is not None

