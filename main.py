"""Runtime assembly for the Devosuit news review service."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Optional
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
from ai_providers import AiProviders, ProviderBundle
from openai_service import OpenAITransport, OpenAIImageService
from pipeline import NewsPipeline
from rate_limiter import AsyncRequestGate
from repositories import PostgresRepository
from schedule import PUBLISHING_SLOTS
from scheduled_content import ScheduledContentRunner
from worker import AiWorker
from x_publisher import OfficialXClient, TwikitXClient, XPublisher


logger = logging.getLogger("haberkolesi.main")


def create_scheduler(
    runner: ScheduledContentRunner,
    x_publisher: Optional[XPublisher] = None,
) -> AsyncIOScheduler:
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
        if x_publisher is not None:
            scheduler.add_job(
                x_publisher.publish_scheduled,
                trigger=CronTrigger(hour=slot.hour, minute=0, timezone=TIMEZONE),
                args=[slot],
                id=f"x_publish_{slot.hour:02d}",
                name=f"{slot.hour:02d}:00 X paylaşımı",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
                replace_existing=True,
            )
    return scheduler


def build_x_publisher(settings, repository) -> Optional[XPublisher]:
    if not settings.x_enabled:
        logger.info("X paylaşımı kapalı (X_ENABLED=false)")
        return None

    backend = getattr(settings, "x_backend", "official")
    if backend == "twikit":
        client = TwikitXClient(
            cookies_file=Path(settings.data_dir) / "x_cookies.json",
            username=settings.x_username,
            email=settings.x_email,
            password=settings.x_password,
            totp_secret=settings.x_totp_secret,
            auth_token=settings.x_auth_token,
            ct0=settings.x_ct0,
            proxy=settings.x_proxy,
        )
    else:
        client = OfficialXClient(
            api_key=settings.x_api_key,
            api_key_secret=settings.x_api_key_secret,
            access_token=settings.x_access_token,
            access_token_secret=settings.x_access_token_secret,
        )

    if not client.configured:
        logger.warning(
            "X_ENABLED=true ama %s kimlik bilgileri eksik; X paylaşımı devre dışı bırakıldı",
            backend,
        )
        return None

    logger.info(
        "X paylaşımı aktif (backend=%s, otomatik=%s, günlük limit=%d)",
        backend,
        settings.x_auto_publish,
        settings.x_daily_limit,
    )
    return XPublisher(repository, client, daily_limit=settings.x_daily_limit)


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
    gemini = None
    if settings.gemini_api_key:
        gemini = GeminiService(
            transport=GoogleGenAITransport(settings.gemini_api_key),
            gate=gate,
            model=settings.gemini_model,
        )
    image_service = ImageService(settings.data_dir)
    openai_text = None
    openai_images = None
    if settings.openai_api_key:
        openai_text = GeminiService(
            transport=OpenAITransport(settings.openai_api_key),
            gate=AsyncRequestGate(1),
            model=settings.openai_model,
        )
        openai_images = OpenAIImageService(
            settings.openai_api_key, settings.data_dir,
            model=settings.openai_image_model, quality=settings.openai_image_quality,
        )
    ai_providers = AiProviders(
        repository,
        gemini=ProviderBundle("gemini", gemini, image_service) if gemini is not None else None,
        openai=ProviderBundle("openai", openai_text, openai_images) if openai_text is not None else None,
    )
    worker = AiWorker(
        repository,
        gemini,
        worker_id=f"worker-{uuid.uuid4().hex[:10]}",
        image_service=image_service,
        min_score=settings.gemini_min_score,
        auto_generate=False,
        ai_providers=ai_providers,
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
        ai_providers=ai_providers,
    )
    x_publisher = build_x_publisher(settings, repository)
    scheduler = create_scheduler(
        content_runner,
        x_publisher if settings.x_auto_publish else None,
    )

    async def close_resources():
        if gemini is not None:
            await gemini.close()
        if openai_text is not None:
            await openai_text.close()
        if openai_images is not None:
            openai_images.close()
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
        x_publisher=x_publisher,
        ai_providers=ai_providers,
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
