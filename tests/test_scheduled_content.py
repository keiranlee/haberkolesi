from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from collector import CollectionResult
from domain import Category, ContentRunState, NewsState, RawNews
from gemini_service import CandidateScore, ContentType, EditorialBatchResult
from repositories import MemoryRepository
from schedule import PublishingSlot
from scheduled_content import ScheduledContentRunner, select_slot_candidates


NOW = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
VALID_SOCIAL_TEXT = (
    "Yapay zeka aracı, yazılım ekiplerinin günlük iş akışını daha verimli "
    "yönetmesini sağlıyor. Yeni çözüm, tekrar eden görevleri azaltarak ekiplerin "
    "ürün geliştirmeye odaklanmasına yardımcı oluyor. #AI #Yazılım"
)


def make_news(index):
    return RawNews(
        url=f"https://source.test/ai/{index}",
        title=f"Yapay zeka haberi {index}",
        summary=f"Doğrulanmış özet {index}",
        content=(f"Doğrulanmış ayrıntı {index}. " * (index + 2)).strip(),
        source="Source",
        source_category=Category.AI,
        published_at=NOW - timedelta(minutes=index),
    )


def test_slot_preselection_prefers_richer_content_when_recency_is_equal():
    short = replace(
        make_news(1),
        url="https://source.test/z-short",
        content="Kısa içerik.",
    )
    rich = replace(
        make_news(1),
        url="https://source.test/a-rich",
        content="Doğrulanmış ve ayrıntılı kaynak içeriği. " * 20,
    )

    selected = select_slot_candidates(
        [short, rich],
        category=Category.AI,
        now=NOW,
        max_age=timedelta(hours=48),
        limit=1,
    )

    assert selected == [rich]


class RecordingCollector:
    def __init__(self, items):
        self.items = items
        self.categories = []

    async def collect(self, category=None):
        self.categories.append(category)
        return CollectionResult(items=list(self.items))


class RecordingGemini:
    def __init__(self):
        self.calls = 0
        self.received_candidates = []
        self.failures = []

    async def evaluate_candidates(self, candidates):
        self.calls += 1
        self.received_candidates = list(candidates)
        if self.failures:
            raise self.failures.pop(0)
        evaluations = [
            CandidateScore(
                news_id=candidate.id,
                score=8.0 + position / 10,
                category=Category.AI,
                reason="Güncel ve somut.",
                key_facts=[f"Doğrulanmış bilgi {candidate.id}."],
                risk_flags=[],
                is_publishable=True,
                topic_relevant=True,
                content_type=ContentType.NEWS,
            )
            for position, candidate in enumerate(candidates)
        ]
        winner = evaluations[-1]
        return EditorialBatchResult(
            evaluations=evaluations,
            selected_news_id=winner.news_id,
            text=VALID_SOCIAL_TEXT,
            image_title="Ekipler için yeni yapay zeka aracı",
            image_fact=winner.key_facts[0],
            used_facts=[winner.key_facts[0]],
            primary_keyword="yapay zeka aracı",
            secondary_keywords=["yazılım ekipleri"],
        )


class RecordingImageService:
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.calls = []

    def generate_card(self, *args):
        self.calls.append(args)
        path = self.output_dir / f"{args[0]}.png"
        path.write_bytes(b"png")
        return path


class RateLimitError(RuntimeError):
    status_code = 429
    retry_after = 17


class LowScoreGemini(RecordingGemini):
    async def evaluate_candidates(self, candidates):
        self.calls += 1
        self.received_candidates = list(candidates)
        candidate = candidates[0]
        fact = "Doğrulanmış düşük öncelikli bilgi."
        return EditorialBatchResult(
            evaluations=[
                CandidateScore(
                    news_id=candidate.id,
                    score=6.5,
                    category=Category.AI,
                    reason="Konu uygun fakat haber değeri düşük.",
                    key_facts=[fact],
                    risk_flags=[],
                    is_publishable=True,
                    topic_relevant=True,
                    content_type=ContentType.NEWS,
                )
            ],
            selected_news_id=candidate.id,
            text=VALID_SOCIAL_TEXT,
            image_title="Düşük öncelikli gelişme",
            image_fact=fact,
            used_facts=[fact],
            primary_keyword="yapay zeka aracı",
            secondary_keywords=["yazılım ekipleri"],
        )


def make_runner(tmp_path, items, gemini=None, sleeper=None):
    repository = MemoryRepository()
    collector = RecordingCollector(items)
    gemini = gemini or RecordingGemini()
    image_service = RecordingImageService(tmp_path)
    runner = ScheduledContentRunner(
        repository,
        collector,
        gemini,
        image_service,
        now=lambda: NOW,
        sleeper=sleeper,
    )
    return runner, repository, collector, gemini, image_service


@pytest.mark.asyncio
async def test_slot_uses_one_batch_call_and_prepares_only_the_winner(tmp_path):
    runner, repository, collector, gemini, image_service = make_runner(
        tmp_path, [make_news(index) for index in range(5)]
    )

    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)

    assert run.state is ContentRunState.READY
    assert collector.categories == [Category.AI]
    assert gemini.calls == 1
    assert len(gemini.received_candidates) == 3
    records = await repository.list_news()
    drafted = [record for record in records if record.state is NewsState.DRAFTED]
    assert [record.id for record in drafted] == [run.selected_news_id]
    assert drafted[0].image_path is not None
    assert len(image_service.calls) == 1


@pytest.mark.asyncio
async def test_manual_test_run_uses_isolated_key_and_prepares_next_slot_winner(tmp_path):
    runner, repository, collector, gemini, image_service = make_runner(
        tmp_path, [make_news(index) for index in range(3)]
    )
    slot = PublishingSlot(12, Category.AI)

    run = await runner.run_test_slot(slot)

    assert run.state is ContentRunState.READY
    assert run.slot_key.startswith("test:")
    assert "2026-09-08T12:AI" not in repository._content_run_by_key
    assert collector.categories == [Category.AI]
    assert gemini.calls == 1
    assert len(image_service.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_slot_does_not_collect_or_call_gemini_twice(tmp_path):
    runner, _, collector, gemini, _ = make_runner(tmp_path, [make_news(1)])
    slot = PublishingSlot(12, Category.AI)

    first = await runner.run_slot(slot, NOW)
    second = await runner.run_slot(slot, NOW)

    assert first is not None
    assert second is None
    assert collector.categories == [Category.AI]
    assert gemini.calls == 1


@pytest.mark.asyncio
async def test_previously_drafted_news_does_not_consume_a_candidate_slot(tmp_path):
    items = [make_news(index) for index in range(4)]
    runner, repository, _, gemini, _ = make_runner(tmp_path, items)
    existing = await repository.insert_news(99, items[0])
    await repository.save_draft(existing.id, "Önceden hazırlanmış metin", ["Bilgi"])

    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)

    assert run.state is ContentRunState.READY
    assert len(gemini.received_candidates) == 3
    assert existing.id not in {record.id for record in gemini.received_candidates}


@pytest.mark.asyncio
async def test_empty_slot_skips_without_calling_gemini(tmp_path):
    runner, _, collector, gemini, image_service = make_runner(tmp_path, [])

    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)

    assert run.state is ContentRunState.SKIPPED
    assert collector.categories == [Category.AI]
    assert gemini.calls == 0
    assert image_service.calls == []


@pytest.mark.asyncio
async def test_winner_below_minimum_score_is_saved_but_not_drafted(tmp_path):
    gemini = LowScoreGemini()
    runner, repository, _, _, image_service = make_runner(
        tmp_path, [make_news(1)], gemini=gemini
    )

    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)

    saved = (await repository.list_news())[0]
    assert run.state is ContentRunState.SKIPPED
    assert saved.score == 6.5
    assert saved.state is NewsState.SCORED
    assert saved.draft_text is None
    assert image_service.calls == []


@pytest.mark.asyncio
async def test_rate_limit_waits_for_retry_after_and_retries_only_once(tmp_path):
    delays = []

    async def record_sleep(seconds):
        delays.append(seconds)

    gemini = RecordingGemini()
    gemini.failures = [RateLimitError("quota")]
    runner, _, _, _, _ = make_runner(
        tmp_path, [make_news(1)], gemini=gemini, sleeper=record_sleep
    )

    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)

    assert run.state is ContentRunState.READY
    assert gemini.calls == 2
    assert delays == [17]
