"""Application orchestration for collection and editor actions."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from domain import AiJob, AiJobType, Category, NewsRecord, NewsState
from filtering import select_candidates


class CollectionInProgress(RuntimeError):
    pass


class NewsPipeline:
    def __init__(
        self,
        repository,
        collector,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_age: timedelta = timedelta(hours=24),
        per_category: int = 5,
    ):
        self.repository = repository
        self.collector = collector
        self.now = now
        self.max_age = max_age
        self.per_category = per_category
        self._collection_lock = None

    async def start_collection(self) -> int:
        if self._collection_lock is None:
            self._collection_lock = asyncio.Lock()
        if self._collection_lock.locked():
            raise CollectionInProgress("A collection is already running")
        async with self._collection_lock:
            batch_id = await self.repository.create_batch()
            try:
                result = await self.collector.collect()
                candidates = select_candidates(
                    result.items,
                    now=self.now(),
                    max_age=self.max_age,
                    per_category=self.per_category,
                )
                inserted = 0
                for item in candidates:
                    record = await self.repository.insert_news(batch_id, item)
                    if record.state is NewsState.COLLECTED:
                        inserted += 1
                await self.repository.finish_batch(
                    batch_id,
                    found_count=len(candidates),
                    error_count=len(result.errors),
                )
                return inserted
            except Exception:
                await self.repository.finish_batch(
                    batch_id,
                    found_count=0,
                    error_count=1,
                    failed=True,
                )
                raise

    async def prepare_candidate(
        self,
        category: Category,
    ) -> Optional[NewsRecord]:
        candidates = await self.repository.ranked_candidates(category)
        if not candidates:
            return None
        selected = candidates[0]
        await self.repository.enqueue_job(selected.id, AiJobType.GENERATE)
        return selected

    async def prepare_news_candidate(self, news_id: int) -> Optional[NewsRecord]:
        """Prepare the highest-ranked safe candidate in the requested item's category."""
        record = await self.repository.get_news(news_id)
        category = record.ai_category or record.raw.source_category
        return await self.prepare_candidate(category)

    async def reject_candidate(self, news_id: int) -> Optional[NewsRecord]:
        record = await self.repository.get_news(news_id)
        category = record.ai_category or record.raw.source_category
        await self.repository.reject(news_id)
        return await self.prepare_candidate(category)

    async def approve_candidate(
        self,
        news_id: int,
        edited_text: Optional[str] = None,
        platform_texts=None,
    ) -> None:
        await self.repository.approve(news_id, edited_text, platform_texts=platform_texts)

    async def regenerate_candidate(self, news_id: int) -> AiJob:
        record = await self.repository.get_news(news_id)
        if record.state is not NewsState.DRAFTED:
            raise ValueError("Only a drafted candidate can be regenerated")
        return await self.repository.enqueue_job(record.id, AiJobType.GENERATE)
