"""Runtime assembly for the Devosuit news review service."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import create_app
from collector import AioHttpClient, RssCollector
from config import RSS_FEEDS, TIMEZONE, get_settings
from database import close_pool, get_pool, initialize_database
from gemini_service import GeminiService, GoogleGenAITransport
from image_service import ImageService
from pipeline import NewsPipeline
from rate_limiter import AsyncRequestGate
from repositories import PostgresRepository
from schedule import PUBLISHING_SLOTS
from scheduled_content import ScheduledContentRunner
from worker import AiWorker


logger = logging.getLogger("haberkolesi.main")


def create_scheduler(runner: ScheduledContentRunner) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    for slot in PUBLISHING_SLOTS:
        scheduler.add_job(
            runner.run_slot,
            trigger=CronTrigger(hour=slot.hour, minute=0, timezone=TIMEZONE),
            args=[slot],
            id=f"content_{slot.hour:02d}_{slot.category.value.lower()}",
            name=f"{slot.hour:02d}:00 {slot.category.value} içerik hazırlığı",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
            replace_existing=True,
        )
    return scheduler


async def build_app():
    settings = get_settings()
    await initialize_database()
    pool = await get_pool()
    repository = PostgresRepository(pool)
    disabled_jobs = await repository.disable_active_score_jobs(
        "Saat bazlı tek-çağrı içerik akışı etkinleştirildi"
    )
    if disabled_jobs:
        logger.info("Eski puanlama kuyruğundaki %d iş devre dışı bırakıldı", disabled_jobs)
    http_client = AioHttpClient()
    collector = RssCollector(
        feeds=RssCollector.normalized_feeds(RSS_FEEDS),
        http=http_client,
    )
    pipeline = NewsPipeline(
        repository,
        collector,
        per_category=settings.candidate_limit_per_category,
        max_age=timedelta(hours=settings.max_news_age_hours),
    )
    gate = AsyncRequestGate(settings.gemini_min_interval_seconds)
    gemini = GeminiService(
        transport=GoogleGenAITransport(settings.gemini_api_key),
        gate=gate,
        model=settings.gemini_model,
    )
    image_service = ImageService(settings.data_dir)
    worker = AiWorker(
        repository,
        gemini,
        worker_id=f"worker-{uuid.uuid4().hex[:10]}",
        image_service=image_service,
        min_score=settings.gemini_min_score,
        auto_generate=False,
    )
    content_runner = ScheduledContentRunner(
        repository,
        collector,
        gemini,
        image_service,
        now=lambda: datetime.now(timezone.utc),
        max_age=timedelta(hours=settings.max_news_age_hours),
        candidate_limit=settings.candidate_limit_per_category,
        min_score=settings.gemini_min_score,
    )
    scheduler = create_scheduler(content_runner)

    async def close_resources():
        await gemini.close()
        await http_client.close()
        await close_pool()

    return create_app(
        settings,
        repository,
        pipeline,
        worker=worker,
        scheduler=scheduler,
        rate_gate=gate,
        content_runner=content_runner,
        close_callback=close_resources,
    )


async def serve() -> None:
    application = await build_app()
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True,
        )
    )
    await server.serve()


if __name__ == "__main__":
    asyncio.run(serve())
