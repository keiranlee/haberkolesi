"""Durable worker for queued Gemini score and draft jobs."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from domain import AiJobType
from gemini_service import InvalidGeminiResponse, ScoreResult, UnsafeDraftError


class RetryableAiError(RuntimeError):
    pass


class AiWorker:
    def __init__(
        self,
        repository,
        gemini,
        *,
        worker_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_attempts: int = 5,
        idle_seconds: float = 2,
    ):
        self.repository = repository
        self.gemini = gemini
        self.worker_id = worker_id
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
            else:
                score = ScoreResult(
                    score=news.score,
                    category=news.ai_category,
                    reason=news.score_reason,
                    key_facts=news.key_facts,
                    risk_flags=news.risk_flags or [],
                    is_publishable=news.is_publishable,
                )
                result = await self.gemini.generate_draft(news.raw, score)
                await self.repository.save_draft(
                    news.id,
                    result.text,
                    result.used_facts,
                )
            await self.repository.complete_job(job.id)
        except RetryableAiError as exc:
            if job.attempts >= self.max_attempts:
                await self.repository.fail_job(job.id, str(exc))
            else:
                delay = min(300, 15 * (2 ** job.attempts))
                await self.repository.retry_job(
                    job.id,
                    self.now() + timedelta(seconds=delay),
                    str(exc),
                )
        except (InvalidGeminiResponse, UnsafeDraftError, ValueError) as exc:
            await self.repository.fail_job(job.id, str(exc))
        except Exception as exc:
            status_code = getattr(exc, "status_code", None) or getattr(
                exc, "code", None
            )
            if status_code == 429 or (
                isinstance(status_code, int) and 500 <= status_code < 600
            ):
                delay = min(300, 15 * (2 ** job.attempts))
                await self.repository.retry_job(
                    job.id,
                    self.now() + timedelta(seconds=delay),
                    str(exc),
                )
            else:
                await self.repository.fail_job(job.id, str(exc))
        return True

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
            worked = await self.run_once()
            if not worked:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.idle_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
