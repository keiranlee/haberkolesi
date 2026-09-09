import pytest
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

from domain import AiJobType, Category, NewsState, RawNews
from image_service import ImageService, _truncate_lines
from repositories import MemoryRepository
from worker import AiWorker
from gemini_service import ScoreResult, DraftResult


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


class FakeGeminiAuto:
    async def score_news(self, news):
        return ScoreResult(
            score=8.5,
            category=Category.AI,
            reason="Yüksek potansiyelli yapay zeka haberi.",
            key_facts=["Önemli model tanıtımı yapıldı."],
            risk_flags=[],
            is_publishable=True,
        )

    async def generate_draft(self, news, score):
        return DraftResult(
            text="Devosuit ile yapay zekanın yeni çağı başlıyor! #AI #Girişim",
            used_facts=["Önemli model tanıtımı yapıldı."],
        )


def make_test_news():
    return RawNews(
        url="https://example.com/test-news",
        title="Yapay Zeka Dünyasında Büyük Gelişme: Yeni Model Çıktı",
        summary="Model tüm testlerde rekor kırdı.",
        content="Detaylı içerik burada yer alıyor.",
        source="TechCrunch",
        source_category=Category.AI,
        published_at=NOW,
    )


def test_image_service_generates_valid_png(tmp_path):
    service = ImageService(output_dir=tmp_path)
    file_path = service.generate_card(
        news_id=42,
        title="Test Haber Başlığı",
        category=Category.GIRISIM,
        source="Swipeline",
        published_at=NOW,
        key_fact="Önemli bir gerçek.",
    )

    assert file_path.exists()
    assert file_path.suffix == ".png"

    with Image.open(file_path) as img:
        assert img.size == (1200, 675)
        assert img.format == "PNG"


def test_overflowing_card_lines_are_truncated_with_an_ellipsis():
    assert _truncate_lines(["bir", "iki", "üç"], 2) == ["bir", "iki…"]
    assert _truncate_lines(["bir"], 2) == ["bir"]


@pytest.mark.asyncio
async def test_worker_auto_generates_draft_and_image_for_high_score(tmp_path):
    repo = MemoryRepository()
    record = await repo.insert_news(1, make_test_news())
    job = await repo.enqueue_job(record.id, AiJobType.SCORE)
    image_service = ImageService(output_dir=tmp_path)

    worker = AiWorker(
        repo,
        FakeGeminiAuto(),
        worker_id="test-worker",
        image_service=image_service,
        min_score=8.0,
        auto_generate=True,
        now=lambda: NOW,
    )

    worked = await worker.run_once()

    assert worked is True
    updated = await repo.get_news(record.id)
    assert updated.state is NewsState.DRAFTED
    assert updated.score == 8.5
    assert updated.draft_text is not None
    assert "Devosuit" in updated.draft_text
    assert updated.image_path is not None
    assert Path(updated.image_path).exists()
