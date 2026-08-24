"""Persistence contracts and an in-memory implementation used by tests."""

import asyncio
import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Optional

from domain import (
    AiJob,
    AiJobState,
    AiJobType,
    Category,
    EditorAction,
    NewsRecord,
    NewsState,
    RawNews,
)
from filtering import normalize_url
from gemini_service import ScoreResult


class MemoryRepository:
    """Reference repository with the same atomic transitions as PostgreSQL."""

    def __init__(self):
        self._news: Dict[int, NewsRecord] = {}
        self._news_by_url: Dict[str, int] = {}
        self._jobs: Dict[int, AiJob] = {}
        self._lock = threading.RLock()
        self._next_news_id = 1
        self._next_job_id = 1
        self._next_batch_id = 1
        self.batches = {}
        self.editor_actions: List[EditorAction] = []
        self.generation_versions: Dict[int, List[str]] = {}

    async def create_batch(self) -> int:
        batch_id = self._next_batch_id
        self._next_batch_id += 1
        self.batches[batch_id] = {"state": "running", "found": 0, "errors": 0}
        return batch_id

    async def finish_batch(
        self,
        batch_id: int,
        *,
        found_count: int,
        error_count: int,
        failed: bool = False,
    ) -> None:
        self.batches[batch_id] = {
            "state": "failed" if failed else "completed",
            "found": found_count,
            "errors": error_count,
        }

    async def insert_news(self, batch_id: int, item: RawNews) -> NewsRecord:
        normalized_url = normalize_url(item.url)
        with self._lock:
            existing_id = self._news_by_url.get(normalized_url)
            if existing_id is not None:
                return deepcopy(self._news[existing_id])
            record = NewsRecord(
                id=self._next_news_id,
                batch_id=batch_id,
                raw=item,
                normalized_url=normalized_url,
            )
            self._next_news_id += 1
            self._news[record.id] = record
            self._news_by_url[normalized_url] = record.id
            return deepcopy(record)

    async def count_news(self) -> int:
        return len(self._news)

    async def health(self) -> None:
        return None

    async def get_news(self, news_id: int) -> NewsRecord:
        return deepcopy(self._news[news_id])

    async def get_job(self, job_id: int) -> AiJob:
        return deepcopy(self._jobs[job_id])

    async def list_news(
        self,
        *,
        category: Optional[Category] = None,
        state: Optional[NewsState] = None,
    ) -> List[NewsRecord]:
        records = list(self._news.values())
        if category is not None:
            records = [
                record
                for record in records
                if (record.ai_category or record.raw.source_category) is category
            ]
        if state is not None:
            records = [record for record in records if record.state is state]
        records.sort(key=lambda record: record.id, reverse=True)
        return deepcopy(records)

    async def save_score(self, news_id: int, result: ScoreResult) -> None:
        with self._lock:
            record = self._news[news_id]
            record.score = result.score
            record.ai_category = result.category
            record.score_reason = result.reason
            record.key_facts = list(result.key_facts)
            record.risk_flags = list(result.risk_flags)
            record.is_publishable = result.is_publishable
            record.state = NewsState.SCORED

    async def save_draft(
        self,
        news_id: int,
        text: str,
        used_facts: List[str],
    ) -> None:
        del used_facts
        with self._lock:
            record = self._news[news_id]
            record.draft_text = text
            record.state = NewsState.DRAFTED
            self.generation_versions.setdefault(news_id, []).append(text)

    async def approve(self, news_id: int, edited_text: Optional[str] = None) -> None:
        with self._lock:
            record = self._news[news_id]
            if edited_text is not None and edited_text.strip():
                record.draft_text = edited_text.strip()
                self.generation_versions.setdefault(news_id, []).append(
                    record.draft_text
                )
            record.state = NewsState.APPROVED
            self.editor_actions.append(
                EditorAction(news_id, "approve", datetime.now(timezone.utc))
            )

    async def reject(self, news_id: int) -> None:
        with self._lock:
            self._news[news_id].state = NewsState.REJECTED
            self.editor_actions.append(
                EditorAction(news_id, "reject", datetime.now(timezone.utc))
            )

    async def enqueue_job(self, news_id: int, job_type: AiJobType) -> AiJob:
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.news_id == news_id
                    and job.job_type is job_type
                    and job.state
                    in {AiJobState.PENDING, AiJobState.RUNNING, AiJobState.RETRY}
                ):
                    return deepcopy(job)
            job = AiJob(
                id=self._next_job_id,
                news_id=news_id,
                job_type=job_type,
                state=AiJobState.PENDING,
            )
            self._next_job_id += 1
            self._jobs[job.id] = job
            return deepcopy(job)

    async def claim_next_job(
        self,
        worker_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[AiJob]:
        current_time = now or datetime.now(timezone.utc)
        with self._lock:
            for job in sorted(self._jobs.values(), key=lambda candidate: candidate.id):
                ready = job.state is AiJobState.PENDING or (
                    job.state is AiJobState.RETRY
                    and job.next_attempt_at is not None
                    and job.next_attempt_at <= current_time
                )
                if not ready:
                    continue
                job.state = AiJobState.RUNNING
                job.worker_id = worker_id
                job.attempts += 1
                return deepcopy(job)
        return None

    async def complete_job(self, job_id: int) -> None:
        with self._lock:
            self._jobs[job_id].state = AiJobState.COMPLETED

    async def retry_job(
        self,
        job_id: int,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = AiJobState.RETRY
            job.next_attempt_at = next_attempt_at
            job.last_error = error
            job.worker_id = None

    async def fail_job(self, job_id: int, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = AiJobState.FAILED
            job.last_error = error
            job.worker_id = None

    async def count_jobs(
        self,
        *,
        job_type: Optional[AiJobType] = None,
        category: Optional[Category] = None,
    ) -> int:
        jobs = list(self._jobs.values())
        if job_type is not None:
            jobs = [job for job in jobs if job.job_type is job_type]
        if category is not None:
            jobs = [
                job
                for job in jobs
                if (
                    self._news[job.news_id].ai_category
                    or self._news[job.news_id].raw.source_category
                )
                is category
            ]
        return len(jobs)

    async def ranked_candidates(
        self,
        category: Category,
    ) -> List[NewsRecord]:
        records = [
            record
            for record in self._news.values()
            if record.ai_category is category
            and record.is_publishable is True
            and record.state is NewsState.SCORED
        ]
        records.sort(key=lambda record: (record.score or 0, -record.id), reverse=True)
        return deepcopy(records)


class PostgresRepository:
    """PostgreSQL implementation used by the running application."""

    def __init__(self, pool):
        self.pool = pool

    @staticmethod
    def _news_from_row(row) -> NewsRecord:
        raw = RawNews(
            url=row["source_url"],
            title=row["title"],
            summary=row["summary"],
            content=row["content"],
            source=row["source"],
            source_category=Category(row["source_category"]),
            published_at=row["published_at"],
        )
        return NewsRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            raw=raw,
            normalized_url=row["normalized_url"],
            state=NewsState(row["state"]),
            score=row["score"],
            ai_category=Category(row["ai_category"]) if row["ai_category"] else None,
            score_reason=row["score_reason"],
            key_facts=list(row["key_facts"] or []),
            risk_flags=list(row["risk_flags"] or []),
            is_publishable=row["is_publishable"],
            draft_text=row["draft_text"],
            external_post_id=row["external_post_id"],
        )

    @staticmethod
    def _job_from_row(row) -> AiJob:
        return AiJob(
            id=row["id"],
            news_id=row["news_id"],
            job_type=AiJobType(row["job_type"]),
            state=AiJobState(row["state"]),
            attempts=row["attempts"],
            next_attempt_at=row["next_attempt_at"],
            worker_id=row["worker_id"],
            last_error=row["last_error"],
        )

    async def create_batch(self) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                "INSERT INTO collection_batches (state) VALUES ('running') RETURNING id"
            )

    async def finish_batch(
        self,
        batch_id: int,
        *,
        found_count: int,
        error_count: int,
        failed: bool = False,
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE collection_batches
                SET state = $2, found_count = $3, error_count = $4,
                    completed_at = NOW()
                WHERE id = $1
                """,
                batch_id,
                "failed" if failed else "completed",
                found_count,
                error_count,
            )

    async def insert_news(self, batch_id: int, item: RawNews) -> NewsRecord:
        normalized_url = normalize_url(item.url)
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO news_items (
                    batch_id, source_url, normalized_url, title, summary, content,
                    source, source_category, published_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (normalized_url) DO NOTHING
                RETURNING *
                """,
                batch_id,
                item.url,
                normalized_url,
                item.title,
                item.summary,
                item.content,
                item.source,
                item.source_category.value,
                item.published_at,
            )
            if row is None:
                row = await connection.fetchrow(
                    "SELECT * FROM news_items WHERE normalized_url = $1",
                    normalized_url,
                )
        return self._news_from_row(row)

    async def count_news(self) -> int:
        async with self.pool.acquire() as connection:
            return await connection.fetchval("SELECT COUNT(*) FROM news_items")

    async def health(self) -> None:
        async with self.pool.acquire() as connection:
            await connection.fetchval("SELECT 1")

    async def get_news(self, news_id: int) -> NewsRecord:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM news_items WHERE id = $1", news_id
            )
        if row is None:
            raise KeyError(news_id)
        return self._news_from_row(row)

    async def get_job(self, job_id: int) -> AiJob:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM ai_jobs WHERE id = $1", job_id
            )
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    async def list_news(
        self,
        *,
        category: Optional[Category] = None,
        state: Optional[NewsState] = None,
    ) -> List[NewsRecord]:
        conditions = []
        values = []
        if category is not None:
            values.append(category.value)
            conditions.append(
                f"COALESCE(ai_category, source_category) = ${len(values)}"
            )
        if state is not None:
            values.append(state.value)
            conditions.append(f"state = ${len(values)}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                f"SELECT * FROM news_items {where} ORDER BY id DESC", *values
            )
        return [self._news_from_row(row) for row in rows]

    async def save_score(self, news_id: int, result: ScoreResult) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE news_items
                SET score = $2, ai_category = $3, score_reason = $4,
                    key_facts = $5::jsonb, risk_flags = $6::jsonb,
                    is_publishable = $7, state = 'scored', updated_at = NOW()
                WHERE id = $1
                """,
                news_id,
                result.score,
                result.category.value,
                result.reason,
                json.dumps(result.key_facts, ensure_ascii=False),
                json.dumps(result.risk_flags, ensure_ascii=False),
                result.is_publishable,
            )

    async def save_draft(
        self,
        news_id: int,
        text: str,
        used_facts: List[str],
    ) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO generation_versions
                        (news_id, generated_text, used_facts)
                    VALUES ($1, $2, $3::jsonb)
                    """,
                    news_id,
                    text,
                    json.dumps(used_facts, ensure_ascii=False),
                )
                await connection.execute(
                    """
                    UPDATE news_items
                    SET draft_text = $2, state = 'drafted', updated_at = NOW()
                    WHERE id = $1
                    """,
                    news_id,
                    text,
                )

    async def approve(self, news_id: int, edited_text: Optional[str] = None) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                if edited_text is not None and edited_text.strip():
                    await connection.execute(
                        """
                        UPDATE news_items
                        SET draft_text = $2, state = 'approved', updated_at = NOW()
                        WHERE id = $1
                        """,
                        news_id,
                        edited_text.strip(),
                    )
                    await connection.execute(
                        "INSERT INTO editor_actions (news_id, action) VALUES ($1, 'edit')",
                        news_id,
                    )
                else:
                    await connection.execute(
                        """
                        UPDATE news_items
                        SET state = 'approved', updated_at = NOW()
                        WHERE id = $1
                        """,
                        news_id,
                    )
                await connection.execute(
                    "INSERT INTO editor_actions (news_id, action) VALUES ($1, 'approve')",
                    news_id,
                )

    async def reject(self, news_id: int) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE news_items
                    SET state = 'rejected', updated_at = NOW()
                    WHERE id = $1
                    """,
                    news_id,
                )
                await connection.execute(
                    "INSERT INTO editor_actions (news_id, action) VALUES ($1, 'reject')",
                    news_id,
                )

    async def enqueue_job(self, news_id: int, job_type: AiJobType) -> AiJob:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO ai_jobs (news_id, job_type)
                VALUES ($1, $2)
                ON CONFLICT (news_id, job_type)
                    WHERE state IN ('pending', 'running', 'retry')
                DO UPDATE SET updated_at = NOW()
                RETURNING *
                """,
                news_id,
                job_type.value,
            )
        return self._job_from_row(row)

    async def claim_next_job(
        self,
        worker_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[AiJob]:
        current_time = now or datetime.now(timezone.utc)
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT * FROM ai_jobs
                    WHERE state = 'pending'
                       OR (state = 'retry' AND next_attempt_at <= $1)
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    current_time,
                )
                if row is None:
                    return None
                row = await connection.fetchrow(
                    """
                    UPDATE ai_jobs
                    SET state = 'running', worker_id = $2,
                        attempts = attempts + 1, updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    row["id"],
                    worker_id,
                )
        return self._job_from_row(row)

    async def complete_job(self, job_id: int) -> None:
        await self._set_job_state(job_id, AiJobState.COMPLETED)

    async def retry_job(
        self,
        job_id: int,
        next_attempt_at: datetime,
        error: str,
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE ai_jobs
                SET state = 'retry', next_attempt_at = $2, last_error = $3,
                    worker_id = NULL, updated_at = NOW()
                WHERE id = $1
                """,
                job_id,
                next_attempt_at,
                error,
            )

    async def fail_job(self, job_id: int, error: str) -> None:
        await self._set_job_state(job_id, AiJobState.FAILED, error)

    async def _set_job_state(
        self,
        job_id: int,
        state: AiJobState,
        error: Optional[str] = None,
    ) -> None:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                UPDATE ai_jobs
                SET state = $2, last_error = $3, worker_id = NULL,
                    updated_at = NOW()
                WHERE id = $1
                """,
                job_id,
                state.value,
                error,
            )

    async def count_jobs(
        self,
        *,
        job_type: Optional[AiJobType] = None,
        category: Optional[Category] = None,
    ) -> int:
        conditions = []
        values = []
        if job_type is not None:
            values.append(job_type.value)
            conditions.append(f"jobs.job_type = ${len(values)}")
        if category is not None:
            values.append(category.value)
            conditions.append(
                f"COALESCE(news.ai_category, news.source_category) = ${len(values)}"
            )
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        async with self.pool.acquire() as connection:
            return await connection.fetchval(
                f"""
                SELECT COUNT(*)
                FROM ai_jobs jobs
                JOIN news_items news ON news.id = jobs.news_id
                {where}
                """,
                *values,
            )

    async def ranked_candidates(self, category: Category) -> List[NewsRecord]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT * FROM news_items
                WHERE ai_category = $1 AND is_publishable = TRUE
                  AND state = 'scored'
                ORDER BY score DESC, id ASC
                """,
                category.value,
            )
        return [self._news_from_row(row) for row in rows]
