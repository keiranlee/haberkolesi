import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from pipeline import NewsPipeline
from repositories import MemoryRepository
from tests.test_app import EmptyCollector, login


@pytest.mark.asyncio
async def test_provider_selection_survives_controller_recreation_and_pins_bundle():
    from ai_providers import AiProviders, ProviderBundle
    repo = MemoryRepository()
    gemini = ProviderBundle("gemini", object(), object())
    openai = ProviderBundle("openai", object(), object())
    providers = AiProviders(repo, gemini=gemini, openai=openai)
    pinned = await providers.snapshot()
    await providers.select("gemini")
    recreated = AiProviders(repo, gemini=gemini, openai=openai)
    assert (await recreated.snapshot()).name == "gemini"
    assert pinned.name == "openai"
    assert pinned.text is openai.text
    await recreated.select("openai")
    assert (await providers.snapshot()).name == "openai"


@pytest.mark.asyncio
async def test_unavailable_and_unknown_providers_do_not_change_selection():
    from ai_providers import AiProviders, ProviderBundle
    repo = MemoryRepository()
    providers = AiProviders(repo, gemini=ProviderBundle("gemini", object(), object()))
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await providers.snapshot()
    await repo.set_ai_provider("gemini")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await providers.select("openai")
    with pytest.raises(ValueError):
        await providers.select("other")
    assert (await providers.snapshot()).name == "gemini"
    await repo.set_ai_provider("openai")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        await providers.snapshot()  # Never silently fall back after restart without key.


@pytest.mark.asyncio
async def test_job_keeps_provider_across_retries_and_controller_restart():
    from ai_providers import AiProviders, ProviderBundle
    from domain import AiJobType
    from tests.test_app import make_news
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_news())
    job = await repo.enqueue_job(record.id, AiJobType.GENERATE)
    bundles = dict(gemini=ProviderBundle("gemini", object(), object()), openai=ProviderBundle("openai", object(), object()))
    providers = AiProviders(repo, **bundles)
    await providers.select("openai")
    assert (await providers.snapshot_for_job(job.id)).name == "openai"
    await providers.select("gemini")
    restarted = AiProviders(repo, **bundles)
    assert (await restarted.snapshot_for_job(job.id)).name == "openai"


def panel(openai_available=True):
    from ai_providers import AiProviders, ProviderBundle
    repo = MemoryRepository()
    providers = AiProviders(
        repo, gemini=ProviderBundle("gemini", object(), object()),
        openai=ProviderBundle("openai", object(), object()) if openai_available else None,
    )
    settings = SimpleNamespace(admin_password="1234", session_secret="test-secret", cookie_secure=False)
    app = create_app(settings, repo, NewsPipeline(repo, EmptyCollector()), ai_providers=providers)
    return TestClient(app), repo


def test_panel_provider_switch_requires_login_csrf_and_persists():
    client, repo = panel()
    with client:
        response = client.post("/settings/ai-provider", data={"provider": "openai"}, follow_redirects=False)
        assert response.status_code in (303, 401, 403)
        csrf = login(client)
        assert client.post("/settings/ai-provider", data={"provider": "openai"}).status_code == 403
        response = client.post("/settings/ai-provider", data={"provider": "openai", "csrf_token": csrf})
        assert response.status_code == 200
        assert 'value="openai"' in response.text
        assert "OpenAI (ChatGPT)" in response.text
    assert asyncio.run(repo.get_ai_provider()) == "openai"


def test_panel_missing_key_shows_error_without_changing_provider():
    client, repo = panel(False)
    asyncio.run(repo.set_ai_provider("gemini"))
    with client:
        csrf = login(client)
        response = client.post("/settings/ai-provider", data={"provider": "openai", "csrf_token": csrf})
        assert "OPENAI_API_KEY" in response.text
    assert asyncio.run(repo.get_ai_provider()) == "gemini"


@pytest.mark.asyncio
async def test_openai_default_can_run_without_gemini_credentials():
    from ai_providers import AiProviders, ProviderBundle
    repo = MemoryRepository()
    bundle = ProviderBundle("openai", object(), object())
    providers = AiProviders(repo, openai=bundle)
    assert await providers.snapshot() is bundle
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        await providers.select("gemini")
    assert (await providers.status())["selected"] == "openai"


@pytest.mark.asyncio
async def test_worker_pins_openai_images_when_selection_changes_during_text(tmp_path):
    from ai_providers import AiProviders, ProviderBundle
    from domain import AiJobType
    from tests.test_app import make_news
    from worker import AiWorker
    repo = MemoryRepository()
    news = await repo.insert_news(1, make_news())
    from gemini_service import ScoreResult
    await repo.save_score(news.id, ScoreResult(score=8, category=news.raw.source_category, reason="Relevant", key_facts=["Approved fact"], is_publishable=True))
    await repo.save_draft(news.id, "Old copy", ["Approved fact"])
    await repo.enqueue_job(news.id, AiJobType.GENERATE)
    class Text:
        async def regenerate_content(self, record):
            await providers.select("gemini")
            return SimpleNamespace(text="OpenAI copy", threads_text="Threads copy", instagram_text="Instagram copy", used_facts=["Approved fact"], image_title="Chip", image_fact="Approved fact")
    class Images:
        def generate_card(self, *args):
            return tmp_path / "openai.png"
    providers = AiProviders(repo, gemini=ProviderBundle("gemini", object(), object()), openai=ProviderBundle("openai", Text(), Images()))
    await providers.select("openai")
    worker = AiWorker(repo, object(), worker_id="test", image_service=object(), ai_providers=providers)
    assert await worker.run_once()
    saved = await repo.get_news(news.id)
    assert saved.draft_text == "OpenAI copy"
    assert saved.image_path == str(tmp_path / "openai.png")
    assert saved.platform_texts["threads"] == "Threads copy"
    assert (await providers.snapshot()).name == "gemini"


@pytest.mark.asyncio
async def test_scheduled_run_pins_provider_before_collection(tmp_path):
    from ai_providers import AiProviders, ProviderBundle
    from domain import Category, ContentRunState
    from schedule import PublishingSlot
    from scheduled_content import ScheduledContentRunner
    from tests.test_scheduled_content import NOW, RecordingCollector, RecordingGemini, RecordingImageService, make_news
    repo = MemoryRepository()
    text = RecordingGemini()
    images = RecordingImageService(tmp_path)
    providers = AiProviders(repo, gemini=ProviderBundle("gemini", object(), object()), openai=ProviderBundle("openai", text, images))
    await providers.select("openai")
    class Collector(RecordingCollector):
        async def collect(self, category=None):
            await providers.select("gemini")
            return await super().collect(category)
    runner = ScheduledContentRunner(repo, Collector([make_news(1)]), object(), object(), now=lambda: NOW, ai_providers=providers)
    run = await runner.run_slot(PublishingSlot(12, Category.AI))
    assert run.state == ContentRunState.READY
    saved = await repo.get_news(run.selected_news_id)
    assert saved.image_path is not None
    assert saved.draft_text
    assert text.calls == 1


@pytest.mark.asyncio
async def test_failed_openai_image_does_not_publish_new_copy_with_old_gemini_card(tmp_path):
    from ai_providers import AiProviders, ProviderBundle
    from domain import AiJobType
    from gemini_service import ScoreResult
    from tests.test_app import make_news
    from worker import AiWorker
    repo = MemoryRepository()
    news = await repo.insert_news(1, make_news())
    await repo.save_score(news.id, ScoreResult(score=8, category=news.raw.source_category, reason="Relevant", key_facts=["Approved fact"], is_publishable=True))
    await repo.save_draft(news.id, "Old copy", ["Approved fact"])
    await repo.save_image(news.id, str(tmp_path / "gemini.png"))
    await repo.enqueue_job(news.id, AiJobType.GENERATE)
    class Text:
        async def regenerate_content(self, record):
            return SimpleNamespace(text="New copy", threads_text="Threads copy", instagram_text="Instagram copy", used_facts=["Approved fact"])
    class Images:
        def generate_card(self, *args):
            raise ValueError("OpenAI image failed")
    providers = AiProviders(repo, gemini=ProviderBundle("gemini", object(), object()), openai=ProviderBundle("openai", Text(), Images()))
    await providers.select("openai")
    worker = AiWorker(repo, object(), worker_id="test", ai_providers=providers)
    await worker.run_once()
    assert (await repo.get_news(news.id)).draft_text == "Old copy"
    assert (await repo.job_counts())["failed"] == 1
