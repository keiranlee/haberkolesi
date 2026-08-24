"""Runtime assembly for the Devosuit news review service."""

import asyncio
import logging
import uuid

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import create_app
from collector import AioHttpClient, RssCollector
from config import RSS_FEEDS, TIMEZONE, get_settings
from database import close_pool, get_pool, initialize_database
from gemini_service import GeminiService, GoogleGenAITransport
from pipeline import NewsPipeline
from rate_limiter import AsyncRequestGate
from repositories import PostgresRepository
from worker import AiWorker


logger = logging.getLogger("haberkolesi.main")


def create_scheduler(pipeline: NewsPipeline) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        pipeline.start_collection,
        trigger=IntervalTrigger(hours=1, timezone=TIMEZONE),
        id="collector_job",
        name="RSS Haber Toplayıcı",
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
    http_client = AioHttpClient()
    collector = RssCollector(
        feeds=RssCollector.normalized_feeds(RSS_FEEDS),
        http=http_client,
    )
    pipeline = NewsPipeline(
        repository,
        collector,
        per_category=settings.candidate_limit_per_category,
    )
    gate = AsyncRequestGate(settings.gemini_min_interval_seconds)
    gemini = GeminiService(
        transport=GoogleGenAITransport(settings.gemini_api_key),
        gate=gate,
        model=settings.gemini_model,
    )
    worker = AiWorker(
        repository,
        gemini,
        worker_id=f"worker-{uuid.uuid4().hex[:10]}",
    )
    scheduler = create_scheduler(pipeline)

    async def close_resources():
        await http_client.close()
        await close_pool()

    return create_app(
        settings,
        repository,
        pipeline,
        worker=worker,
        scheduler=scheduler,
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
