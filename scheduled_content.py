"""Cost-bounded orchestration for one scheduled editorial content slot."""

import asyncio
import re
import uuid
from datetime import datetime, timedelta
from typing import Awaitable, Callable, List, Optional
from zoneinfo import ZoneInfo

from domain import Category, ContentRun, ContentRunState, NewsRecord, NewsState, RawNews
from filtering import select_candidates
from gemini_service import (
    InvalidGeminiResponse,
    ScoreResult,
    UnsafeDraftError,
)
from schedule import PublishingSlot


ISTANBUL = ZoneInfo("Europe/Istanbul")


def select_slot_candidates(
    items: List[RawNews],
    *,
    category: Category,
    now: datetime,
    max_age: timedelta,
    limit: int = 3,
) -> List[RawNews]:
    category_items = [item for item in items if item.source_category is category]
    return select_candidates(
        category_items,
        now=now,
        max_age=max_age,
        per_category=limit,
    )[:limit]


class ScheduledContentRunner:
    def __init__(
        self,
        repository,
        collector,
        gemini,
        image_service,
        *,
        now: Callable[[], datetime],
        max_age: timedelta = timedelta(hours=48),
        candidate_limit: int = 3,
        min_score: float = 7.5,
        sleeper: Optional[Callable[[float], Awaitable[None]]] = None,
    ):
        self.repository = repository
        self.collector = collector
        self.gemini = gemini
        self.image_service = image_service
        self.now = now
        self.max_age = max_age
        self.candidate_limit = candidate_limit
        self.min_score = min_score
        self.sleeper = sleeper or asyncio.sleep
        self._manual_test_lock = asyncio.Lock()

    async def run_slot(
        self,
        slot: PublishingSlot,
        scheduled_for: Optional[datetime] = None,
    ) -> Optional[ContentRun]:
        scheduled_for = scheduled_for or self.now()
        local_time = scheduled_for.astimezone(ISTANBUL)
        slot_key = f"{local_time.date().isoformat()}T{slot.hour:02d}:{slot.category.value}"
        return await self._run_slot(slot, scheduled_for, slot_key)

    async def run_test_slot(
        self,
        slot: PublishingSlot,
    ) -> Optional[ContentRun]:
        if self._manual_test_lock.locked():
            return None
        async with self._manual_test_lock:
            started_at = self.now()
            slot_key = (
                f"test:{started_at.isoformat()}:{slot.category.value}:"
                f"{uuid.uuid4().hex}"
            )
            return await self._run_slot(slot, started_at, slot_key)

    async def _run_slot(
        self,
        slot: PublishingSlot,
        scheduled_for: datetime,
        slot_key: str,
    ) -> Optional[ContentRun]:
        run = await self.repository.claim_content_run(
            slot_key,
            scheduled_for,
            slot.category,
        )
        if run is None:
            return None

        batch_id = await self.repository.create_batch()
        collection = None
        try:
            collection = await self.collector.collect(slot.category)
            raw_candidates = select_slot_candidates(
                collection.items,
                category=slot.category,
                now=self.now(),
                max_age=self.max_age,
                limit=max(self.candidate_limit, len(collection.items)),
            )
            candidates = []
            for raw in raw_candidates:
                record = await self.repository.insert_news(batch_id, raw)
                if record.state is NewsState.COLLECTED:
                    candidates.append(record)
                if len(candidates) == self.candidate_limit:
                    break

            if not candidates:
                await self.repository.finish_batch(
                    batch_id,
                    found_count=0,
                    error_count=len(collection.errors),
                )
                await self.repository.complete_content_run(run.id, None)
                run.state = ContentRunState.SKIPPED
                return run

            editorial = await self._evaluate_with_retry(candidates)
            for evaluation in editorial.evaluations:
                await self.repository.save_score(
                    evaluation.news_id,
                    ScoreResult(
                        score=evaluation.score,
                        category=evaluation.category,
                        reason=evaluation.reason,
                        key_facts=evaluation.key_facts,
                        risk_flags=(
                            evaluation.risk_flags
                            if evaluation.topic_relevant
                            else evaluation.risk_flags + ["Planlanan kategoriyle ilgisiz"]
                        ),
                        is_publishable=(
                            evaluation.is_publishable and evaluation.topic_relevant
                        ),
                    ),
                )

            selected_evaluation = next(
                (
                    evaluation
                    for evaluation in editorial.evaluations
                    if evaluation.news_id == editorial.selected_news_id
                ),
                None,
            )
            if (
                editorial.selected_news_id is None
                or selected_evaluation is None
                or selected_evaluation.score < self.min_score
            ):
                await self.repository.finish_batch(
                    batch_id,
                    found_count=len(candidates),
                    error_count=len(collection.errors),
                )
                await self.repository.complete_content_run(run.id, None)
                run.state = ContentRunState.SKIPPED
                return run

            winner = next(
                candidate
                for candidate in candidates
                if candidate.id == editorial.selected_news_id
            )
            await self.repository.save_draft(
                winner.id,
                editorial.text,
                editorial.used_facts,
                platform_texts={"x": editorial.text, "threads": editorial.threads_text, "instagram": editorial.instagram_text},
            )
            run.selected_news_id = winner.id
            image_path = await asyncio.to_thread(
                self.image_service.generate_card,
                winner.id,
                editorial.image_title,
                slot.category,
                winner.raw.source,
                winner.raw.published_at,
                editorial.image_fact,
            )
            await self.repository.save_image(winner.id, str(image_path))
            await self.repository.finish_batch(
                batch_id,
                found_count=len(candidates),
                error_count=len(collection.errors),
            )
            await self.repository.complete_content_run(run.id, winner.id)
            run.state = ContentRunState.READY
            return run
        except Exception as exc:
            await self.repository.finish_batch(
                batch_id,
                found_count=0,
                error_count=len(collection.errors) if collection is not None else 1,
                failed=True,
            )
            await self.repository.fail_content_run(run.id, str(exc))
            run.state = ContentRunState.FAILED
            run.error = str(exc)
            return run

    async def _evaluate_with_retry(
        self,
        candidates: List[NewsRecord],
    ):
        try:
            return await self.gemini.evaluate_candidates(candidates)
        except Exception as exc:
            if not self._is_retryable(exc):
                raise
            await self.sleeper(self._retry_delay(exc))
            return await self.gemini.evaluate_candidates(candidates)

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
        return (
            status_code == 429
            or isinstance(error, (InvalidGeminiResponse, UnsafeDraftError))
        )

    @staticmethod
    def _retry_delay(error: Exception) -> float:
        value = getattr(error, "retry_after", None) or getattr(error, "retry_delay", None)
        if isinstance(value, timedelta):
            return max(0.0, value.total_seconds())
        if isinstance(value, (int, float)):
            return max(0.0, float(value))
        match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", str(error), re.I)
        return float(match.group(1)) if match else 60.0
