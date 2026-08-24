import asyncio
import os
from datetime import datetime, timezone

import pytest

from domain import AiJobState, AiJobType, Category, NewsState, RawNews
from repositories import MemoryRepository, PostgresRepository


def make_news(url="https://source.test/news"):
    return RawNews(
        url=url,
        title="Test news",
        summary="Summary",
        content="Complete source content.",
        source="Source",
        source_category=Category.AI,
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_insert_news_is_idempotent_by_normalized_url():
    repository = MemoryRepository()

    first = await repository.insert_news(1, make_news("https://source.test/news?utm_source=rss"))
    second = await repository.insert_news(2, make_news("https://source.test/news"))

    assert first.id == second.id
    assert await repository.count_news() == 1


@pytest.mark.asyncio
async def test_claim_next_job_gives_job_to_only_one_worker():
    repository = MemoryRepository()
    news = await repository.insert_news(1, make_news())
    await repository.enqueue_job(news.id, AiJobType.SCORE)

    first, second = await asyncio.gather(
        repository.claim_next_job("worker-a"),
        repository.claim_next_job("worker-b"),
    )

    claimed = [job for job in (first, second) if job is not None]
    assert len(claimed) == 1
    assert claimed[0].state is AiJobState.RUNNING


@pytest.mark.asyncio
async def test_approve_records_edited_text_without_publishing():
    repository = MemoryRepository()
    news = await repository.insert_news(1, make_news())
    await repository.save_draft(news.id, "Generated text", ["Fact"])

    await repository.approve(news.id, "Editor text")

    saved = await repository.get_news(news.id)
    assert saved.state is NewsState.APPROVED
    assert saved.draft_text == "Editor text"
    assert saved.external_post_id is None
    assert repository.editor_actions[-1].action == "approve"


@pytest.mark.asyncio
async def test_approve_rejects_undrafted_news_and_oversized_text():
    repository = MemoryRepository()
    news = await repository.insert_news(1, make_news())

    with pytest.raises(ValueError, match="drafted"):
        await repository.approve(news.id, "Text")

    await repository.save_draft(news.id, "Generated text", ["Fact"])
    with pytest.raises(ValueError, match="240"):
        await repository.approve(news.id, "x" * 241)


@pytest.mark.asyncio
async def test_retry_job_becomes_claimable_only_after_next_attempt():
    repository = MemoryRepository()
    news = await repository.insert_news(1, make_news())
    job = await repository.enqueue_job(news.id, AiJobType.SCORE)
    claimed = await repository.claim_next_job("worker")
    retry_at = datetime(2026, 8, 24, 12, 5, tzinfo=timezone.utc)
    await repository.retry_job(claimed.id, retry_at, "rate limited")

    too_early = await repository.claim_next_job(
        "worker", now=datetime(2026, 8, 24, 12, 4, tzinfo=timezone.utc)
    )
    ready = await repository.claim_next_job(
        "worker", now=datetime(2026, 8, 24, 12, 5, tzinfo=timezone.utc)
    )

    assert too_early is None
    assert ready.id == job.id


def test_postgres_row_decodes_jsonb_strings_as_fact_lists():
    raw = make_news()
    row = {
        "id": 1,
        "batch_id": 1,
        "source_url": raw.url,
        "normalized_url": raw.url,
        "title": raw.title,
        "summary": raw.summary,
        "content": raw.content,
        "source": raw.source,
        "source_category": raw.source_category.value,
        "published_at": raw.published_at,
        "state": "scored",
        "score": 9.0,
        "ai_category": "AI",
        "score_reason": "Reason",
        "key_facts": '["Fact one", "Fact two"]',
        "risk_flags": '["Rumor"]',
        "is_publishable": True,
        "draft_text": None,
        "external_post_id": None,
    }

    record = PostgresRepository._news_from_row(row)

    assert record.key_facts == ["Fact one", "Fact two"]
    assert record.risk_flags == ["Rumor"]


@pytest.mark.asyncio
async def test_running_job_is_reclaimed_only_after_lease_expires():
    repository = MemoryRepository()
    news = await repository.insert_news(1, make_news())
    original = await repository.enqueue_job(news.id, AiJobType.SCORE)
    await repository.claim_next_job("worker-a", now=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))

    early = await repository.claim_next_job(
        "worker-b", now=datetime(2026, 8, 24, 12, 4, tzinfo=timezone.utc)
    )
    reclaimed = await repository.claim_next_job(
        "worker-b", now=datetime(2026, 8, 24, 12, 6, tzinfo=timezone.utc)
    )

    assert early is None
    assert reclaimed.id == original.id
    assert reclaimed.worker_id == "worker-b"


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration",
)
@pytest.mark.asyncio
async def test_postgres_insert_is_idempotent_and_job_claim_is_atomic():
    import asyncpg

    from database import CREATE_TABLE_SQL
    from repositories import PostgresRepository

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1)
    try:
        async with pool.acquire() as connection:
            await connection.execute(CREATE_TABLE_SQL)
            await connection.execute(
                "TRUNCATE editor_actions, generation_versions, ai_jobs, "
                "news_items, collection_batches RESTART IDENTITY CASCADE"
            )
            batch_id = await connection.fetchval(
                "INSERT INTO collection_batches (state) VALUES ('running') RETURNING id"
            )
        repository = PostgresRepository(pool)
        first = await repository.insert_news(batch_id, make_news())
        second = await repository.insert_news(batch_id, make_news())
        await repository.enqueue_job(first.id, AiJobType.SCORE)
        claimed = await asyncio.gather(
            repository.claim_next_job("worker-a"),
            repository.claim_next_job("worker-b"),
        )

        assert first.id == second.id
        assert sum(job is not None for job in claimed) == 1
    finally:
        await pool.close()
