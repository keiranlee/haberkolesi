"""Durable worker for queued Gemini score and draft jobs."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from domain import AiJobType
from gemini_service import InvalidGeminiResponse, ScoreResult, UnsafeDraftError


logger = logging.getLogger(__name__)


class RetryableAiError(RuntimeError):
    pass


class AiWorker:
    def __init__(
        self,
        repository,
        gemini,
        *,
        worker_id: str,
        image_service=None,
        min_score: float = 8.0,
        auto_generate: bool = False,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_attempts: int = 5,
        idle_seconds: float = 2,
    ):
        self.repository = repository
        self.gemini = gemini
        self.worker_id = worker_id
        self.image_service = image_service
        self.min_score = min_score
        self.auto_generate = auto_generate
        self.now = now
        self.max_attempts = max_attempts
        self.idle_seconds = idle_seconds
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def run_once(self) -> bool:
        job = await self.repository.claim_next_job(self.worker_id, now=self.now())
        if job is None:
            return False
        try:
            news = await self.repository.get_news(job.news_id)
            if job.job_type is AiJobType.SCORE:
                result = await self.gemini.score_news(news.raw)
                await self.repository.save_score(news.id, result)
                if self.auto_generate and result.score >= self.min_score and result.is_publishable:
                    draft_result = await self.gemini.generate_draft(news.raw, result)
                    await self.repository.save_draft(
                        news.id,
                        draft_result.text,
                        draft_result.used_facts,
                    )
                    if self.image_service is not None:
                        category = result.category or news.raw.source_category
                        key_fact = result.key_facts[0] if result.key_facts else None
                        image_path = await asyncio.to_thread(
                            self.image_service.generate_card,
                            news.id,
                            news.raw.title,
                            category,
                            news.raw.source,
                            news.raw.published_at,
                            key_fact,
                        )
                        await self.repository.save_image(news.id, str(image_path))
            else:
                result = await self.gemini.regenerate_content(news)
                await self.repository.save_draft(
                    news.id,
                    result.text,
                    result.used_facts,
                    platform_texts={"x": result.text, "threads": getattr(result, "threads_text", None), "instagram": getattr(result, "instagram_text", None)},
                )
                if self.image_service is not None:
                    category = news.ai_category or news.raw.source_category
                    image_title = getattr(result, "image_title", news.raw.title)
                    image_fact = getattr(
                        result,
                        "image_fact",
                        result.used_facts[0] if result.used_facts else None,
                    )
                    image_path = await asyncio.to_thread(
                        self.image_service.generate_card,
                        news.id,
                        image_title,
                        category,
                        news.raw.source,
                        news.raw.published_at,
                        image_fact,
                    )
                    await self.repository.save_image(news.id, str(image_path))
            await self.repository.complete_job(job.id)
        except RetryableAiError as exc:
            await self._retry_or_fail(job, exc)
        except (InvalidGeminiResponse, UnsafeDraftError, ValueError) as exc:
            await self.repository.fail_job(job.id, str(exc))
        except Exception as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                exc, "code", None
            )
            if status_code == 429 or (
                isinstance(status_code, int) and 500 <= status_code < 600
            ):
                await self._retry_or_fail(job, exc)
            else:
                await self.repository.fail_job(job.id, str(exc))
        return True

    async def _retry_or_fail(self, job, error: Exception) -> None:
        if job.attempts >= self.max_attempts:
            await self.repository.fail_job(job.id, str(error))
            return
        delay = min(300, 15 * (2 ** job.attempts))
        await self.repository.retry_job(
            job.id,
            self.now() + timedelta(seconds=delay),
            str(error),
        )

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("AI worker iteration failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.idle_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
