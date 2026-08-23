"""
Haber Kölesi — Ana Modül
=========================
Asenkron zamanlayıcı ile toplayıcı ve paylaşıcı görevlerini
yöneten ana giriş noktası.

Mimari:
  - APScheduler (AsyncIOScheduler) ile görev zamanlaması
  - UTC+3 (Europe/Istanbul) saat diliminde çalışma
  - Graceful shutdown desteği
"""

import asyncio
import signal
import sys
import logging
from typing import NoReturn

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import (
    setup_logging,
    TIMEZONE,
    PUBLISH_START_HOUR,
    PUBLISH_END_HOUR,
    DATA_DIR,
)
from database import initialize_database, close_pool, get_pool_stats
from scraper import run_collector
from publisher import run_publisher

logger: logging.Logger = logging.getLogger("haberkolesi.main")


# ─────────────────────────────────────────────────────────────
# Zamanlayıcı Yapılandırması
# ─────────────────────────────────────────────────────────────
def create_scheduler() -> AsyncIOScheduler:
    """
    APScheduler AsyncIOScheduler oluşturur.

    Görevler:
    1. Toplayıcı (Collector): Her 1 saatte bir çalışır.
    2. Paylaşıcı (Publisher): 07:00-00:00 arası her tam saat başı çalışır.
    """
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # ── GÖREV 1: Toplayıcı — Her 1 saatte bir ──
    scheduler.add_job(
        run_collector,
        trigger=IntervalTrigger(hours=1, timezone=TIMEZONE),
        id="collector_job",
        name="Haber Toplayıcı",
        max_instances=1,
        misfire_grace_time=300,  # 5 dakika tolerans
        replace_existing=True,
    )

    # ── GÖREV 2: Paylaşıcı — 07:00-23:59 arası her saat başı ──
    # 07:00'den 23:00'e kadar (dahil) + 00:00
    # CronTrigger ile: saat 7-23 ve 0
    scheduler.add_job(
        run_publisher,
        trigger=CronTrigger(
            hour="0,7-23",
            minute=0,
            timezone=TIMEZONE,
        ),
        id="publisher_job",
        name="Haber Paylaşıcı",
        max_instances=1,
        misfire_grace_time=300,
        replace_existing=True,
    )

    logger.info("Zamanlayıcı yapılandırıldı ─ Timezone: %s", TIMEZONE)
    logger.info(
        "  → Toplayıcı: Her 1 saatte bir"
    )
    logger.info(
        "  → Paylaşıcı: %02d:00 - %02d:00 arası, her saat başı",
        PUBLISH_START_HOUR,
        PUBLISH_END_HOUR,
    )

    return scheduler


# ─────────────────────────────────────────────────────────────
# Graceful Shutdown
# ─────────────────────────────────────────────────────────────
async def shutdown(
    scheduler: AsyncIOScheduler,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Uygulamayı düzgün bir şekilde kapatır."""
    logger.info("Kapatma sinyali alındı. Uygulama durduruluyor...")

    # Zamanlayıcıyı durdur
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Zamanlayıcı durduruldu.")

    # Veritabanı bağlantı havuzunu kapat
    await close_pool()

    # Bekleyen görevleri iptal et
    tasks = [
        t for t in asyncio.all_tasks(loop)
        if t is not asyncio.current_task()
    ]
    for task in tasks:
        task.cancel()

    logger.info("Uygulama başarıyla kapatıldı.")


# ─────────────────────────────────────────────────────────────
# Ana Giriş Noktası
# ─────────────────────────────────────────────────────────────
async def main() -> None:
    """Uygulamanın ana asenkron fonksiyonu."""
    # Banner
    logger.info("╔" + "═" * 58 + "╗")
    logger.info("║" + " HABER KÖLESİ — Otomatik Haber Botu ".center(58) + "║")
    logger.info("║" + " v1.0.0 ".center(58) + "║")
    logger.info("╚" + "═" * 58 + "╝")

    # Veri dizini kontrolü
    logger.info("Veri dizini: %s", DATA_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Veritabanını başlat
    try:
        await initialize_database()
        stats = await get_pool_stats()
        logger.info(
            "Havuz durumu ─ toplam=%d, yayınlanmamış=%d, yayınlanmış=%d",
            stats["total"],
            stats["unpublished"],
            stats["published"],
        )
    except Exception as exc:
        logger.critical("Veritabanı başlatılamadı: %s", exc)
        sys.exit(1)

    # Zamanlayıcıyı oluştur ve başlat
    scheduler: AsyncIOScheduler = create_scheduler()

    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()

    # Sinyal işleyicileri (graceful shutdown)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown(scheduler, loop)),
            )
        except NotImplementedError:
            # Windows'ta signal handler desteği sınırlı
            signal.signal(sig, lambda s, f: asyncio.create_task(shutdown(scheduler, loop)))

    # İlk çalıştırmada toplayıcıyı hemen tetikle
    logger.info("İlk toplayıcı çalıştırılıyor...")
    try:
        await run_collector()
    except Exception as exc:
        logger.error("İlk toplayıcı çalışmasında hata: %s", exc)

    # Zamanlayıcıyı başlat
    scheduler.start()
    logger.info("Zamanlayıcı başlatıldı. Bot aktif.")

    # Sonsuz döngü — scheduler çalışmaya devam etsin
    try:
        while True:
            await asyncio.sleep(3600)  # 1 saat
    except (KeyboardInterrupt, asyncio.CancelledError):
        await shutdown(scheduler, loop)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Uygulama kullanıcı tarafından durduruldu.")
    except Exception as exc:
        logger.critical("Beklenmeyen hata: %s", exc, exc_info=True)
        sys.exit(1)
