from datetime import datetime, timedelta, timezone

import pytest

from collector import CollectionResult
from domain import AiJobState, AiJobType, Category, NewsState, RawNews
from gemini_service import DraftResult, ScoreResult
from pipeline import NewsPipeline
from repositories import MemoryRepository
from worker import AiWorker, RetryableAiError


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def make_news(category, index):
    return RawNews(
        url=f"https://source.test/{category.value}/{index}",
        title=f"{category.value} news {index}",
        summary="Summary",
        content=f"Complete source content {index}.",
        source="Source",
        source_category=category,
        published_at=NOW - timedelta(minutes=index),
    )


class FakeCollector:
    def __init__(self, items):
        self.result = CollectionResult(items=items)

    async def collect(self):
        return self.result


class FakeGemini:
    def __init__(self):
        self.fail_with = None

    async def score_news(self, news):
        if self.fail_with:
            raise self.fail_with
        return ScoreResult(
            score=8.8,
            category=news.source_category,
            reason="Güncel ve somut.",
            key_facts=["Somut bilgi."],
            risk_flags=[],
            is_publishable=True,
        )

    async def generate_draft(self, news, score):
        if self.fail_with:
            raise self.fail_with
        return DraftResult(text="Devosuit haber metni #AI", used_facts=["Somut bilgi."])


class HttpError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.asyncio
async def test_manual_collection_stores_news_without_enqueuing_gemini_scores():
    repository = MemoryRepository()
    collector = FakeCollector(
        [make_news(Category.AI, i) for i in range(7)]
        + [make_news(Category.GIRISIM, i) for i in range(6)]
    )
    pipeline = NewsPipeline(repository, collector, now=lambda: NOW)

    await pipeline.start_collection()

    assert await repository.count_news() == 10
    assert await repository.count_jobs(job_type=AiJobType.SCORE) == 0


@pytest.mark.asyncio
async def test_prepare_generates_only_highest_scored_candidate():
    repository = MemoryRepository()
    scores = [9.1, 8.8, 8.2]
    for index, score in enumerate(scores):
        record = await repository.insert_news(1, make_news(Category.AI, index))
        await repository.save_score(
            record.id,
            ScoreResult(
                score=score,
                category=Category.AI,
                reason="Güncel.",
                key_facts=["Somut bilgi."],
                risk_flags=[],
                is_publishable=True,
            ),
        )
    pipeline = NewsPipeline(repository, FakeCollector([]), now=lambda: NOW)

    selected = await pipeline.prepare_candidate(Category.AI)

    assert selected.score == 9.1
    assert await repository.count_jobs(job_type=AiJobType.GENERATE, category=Category.AI) == 1


@pytest.mark.asyncio
async def test_prepare_skips_candidate_with_risk_flags():
    repository = MemoryRepository()
    records = []
    for index, (score, risks) in enumerate([(9.8, ["Unverified"]), (9.1, [])]):
        record = await repository.insert_news(1, make_news(Category.AI, index))
        await repository.save_score(
            record.id,
            ScoreResult(
                score=score,
                category=Category.AI,
                reason="Güncel.",
                key_facts=["Somut bilgi."],
                risk_flags=risks,
                is_publishable=True,
            ),
        )
        records.append(record)
    pipeline = NewsPipeline(repository, FakeCollector([]), now=lambda: NOW)

    selected = await pipeline.prepare_candidate(Category.AI)

    assert selected.id == records[1].id


@pytest.mark.asyncio
async def test_prepare_by_news_id_still_selects_highest_scored_candidate():
    repository = MemoryRepository()
    records = []
    for index, score in enumerate([9.4, 8.1]):
        record = await repository.insert_news(1, make_news(Category.AI, index))
        await repository.save_score(
            record.id,
            ScoreResult(
                score=score,
                category=Category.AI,
                reason="Güncel.",
                key_facts=["Somut bilgi."],
                risk_flags=[],
                is_publishable=True,
            ),
        )
        records.append(record)
    pipeline = NewsPipeline(repository, FakeCollector([]), now=lambda: NOW)

    selected = await pipeline.prepare_news_candidate(records[1].id)

    assert selected.id == records[0].id


@pytest.mark.asyncio
async def test_regenerate_requires_an_existing_draft():
    repository = MemoryRepository()
    record = await repository.insert_news(1, make_news(Category.AI, 1))
    pipeline = NewsPipeline(repository, FakeCollector([]), now=lambda: NOW)

    with pytest.raises(ValueError, match="drafted"):
        await pipeline.regenerate_candidate(record.id)


@pytest.mark.asyncio
async def test_regenerate_worker_uses_new_editorial_batch_prompt_for_same_news():
    repository = MemoryRepository()
    record = await repository.insert_news(1, make_news(Category.AI, 1))
    await repository.save_score(
        record.id,
        ScoreResult(
            score=8.8,
            category=Category.AI,
            reason="İlk puan.",
            key_facts=["Somut bilgi."],
            risk_flags=[],
            is_publishable=True,
        ),
    )
    await repository.save_draft(record.id, "Eski metin", ["Somut bilgi."])
    job = await repository.enqueue_job(record.id, AiJobType.GENERATE)

    class EditorialGemini:
        def __init__(self):
            self.candidates = []

        async def evaluate_candidates(self, candidates):
            raise AssertionError("batch selection prompt must not be used")

        async def regenerate_content(self, candidate):
            self.candidates = [candidate]
            fact = "Somut bilgi."
            return DraftResult(
                text="Yeni SEO ve sosyal medya metni.",
                used_facts=[fact],
            )

    gemini = EditorialGemini()
    worker = AiWorker(repository, gemini, worker_id="test", now=lambda: NOW)

    await worker.run_once()

    saved = await repository.get_news(record.id)
    saved_job = await repository.get_job(job.id)
    assert [candidate.id for candidate in gemini.candidates] == [record.id]
    assert saved.draft_text == "Yeni SEO ve sosyal medya metni."
    assert saved.score == 8.8
    assert saved_job.state is AiJobState.COMPLETED


@pytest.mark.asyncio
async def test_reject_enqueues_exactly_one_next_candidate():
    repository = MemoryRepository()
    records = []
    for index, score in enumerate([9.1, 8.8]):
        record = await repository.insert_news(1, make_news(Category.AI, index))
        await repository.save_score(
            record.id,
            ScoreResult(
                score=score,
                category=Category.AI,
                reason="Güncel.",
                key_facts=["Somut bilgi."],
                risk_flags=[],
                is_publishable=True,
            ),
        )
        records.append(record)
    await repository.save_draft(records[0].id, "First draft", ["Somut bilgi."])
    pipeline = NewsPipeline(repository, FakeCollector([]), now=lambda: NOW)

    next_candidate = await pipeline.reject_candidate(records[0].id)

    assert next_candidate.id == records[1].id
    assert await repository.count_jobs(job_type=AiJobType.GENERATE, category=Category.AI) == 1


@pytest.mark.asyncio
async def test_worker_scores_news_and_completes_job():
    repository = MemoryRepository()
    record = await repository.insert_news(1, make_news(Category.AI, 1))
    job = await repository.enqueue_job(record.id, AiJobType.SCORE)
    worker = AiWorker(repository, FakeGemini(), worker_id="test", now=lambda: NOW)

    worked = await worker.run_once()

    saved = await repository.get_news(record.id)
    saved_job = await repository.get_job(job.id)
    assert worked is True
    assert saved.state is NewsState.SCORED
    assert saved.score == 8.8
    assert saved_job.state is AiJobState.COMPLETED


@pytest.mark.asyncio
async def test_worker_retries_temporary_failure_with_backoff():
    repository = MemoryRepository()
    record = await repository.insert_news(1, make_news(Category.AI, 1))
    job = await repository.enqueue_job(record.id, AiJobType.SCORE)
    gemini = FakeGemini()
    gemini.fail_with = RetryableAiError("rate limited")
    worker = AiWorker(repository, gemini, worker_id="test", now=lambda: NOW)

    await worker.run_once()

    saved_job = await repository.get_job(job.id)
    assert saved_job.state is AiJobState.RETRY
    assert saved_job.next_attempt_at == NOW + timedelta(seconds=30)


@pytest.mark.asyncio
async def test_worker_stops_retrying_http_429_after_max_attempts():
    repository = MemoryRepository()
    record = await repository.insert_news(1, make_news(Category.AI, 1))
    job = await repository.enqueue_job(record.id, AiJobType.SCORE)
    gemini = FakeGemini()
    gemini.fail_with = HttpError(429)
    worker = AiWorker(
        repository,
        gemini,
        worker_id="test",
        now=lambda: NOW,
        max_attempts=1,
    )

    await worker.run_once()

    saved_job = await repository.get_job(job.id)
    assert saved_job.state is AiJobState.FAILED
