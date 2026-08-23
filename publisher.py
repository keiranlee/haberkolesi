"""
Haber Kölesi - Paylaşıcı (Publisher) Modülü
=============================================
Haber havuzundan seçilen haberleri X (Twitter) ve Threads'te
otomatik olarak paylaşır. Kota yönetimi ve dinamik kategori
seçimi ile çalışır.
"""

import asyncio
import logging
import random
from datetime import date, datetime
from typing import Optional, Dict, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import (
    DAILY_POST_LIMIT,
    STARTUP_MIN_QUOTA,
    MIN_DELAY,
    MAX_DELAY,
    X_COOKIES_FILE,
    X_USERNAME,
    X_EMAIL,
    X_PASSWORD,
    THREADS_USERNAME,
    THREADS_PASSWORD,
    THREADS_SESSION_FILE,
    TIMEZONE,
)
from database import get_daily_publish_stats, pick_next_news, mark_as_published

logger: logging.Logger = logging.getLogger("haberkolesi.publisher")


# ─────────────────────────────────────────────────────────────
# Kota Yönetimi — Dinamik Kategori Seçimi
# ─────────────────────────────────────────────────────────────
async def _determine_required_category() -> Optional[str]:
    """
    Gün içi kota durumuna göre bir sonraki haberin hangi kategoriden
    olması gerektiğini belirler.

    Mantık:
    - Günde toplam 18 gönderi, EN AZ 10 tanesi 'Startup' olmalı.
    - Kalan slotlar Startup kotasını doldurmaması durumunda
      Startup zorlanır.
    - Günlük limit dolmuşsa None döner (paylaşım yapılmaz).
    """
    import pytz

    tz = pytz.timezone(TIMEZONE)
    today: date = datetime.now(tz).date()

    stats: Dict[str, int] = await get_daily_publish_stats(today)
    total_today: int = stats["total"]
    startup_today: int = stats["Startup"]

    logger.info(
        "Günlük istatistikler ─ toplam=%d/%d, startup=%d/%d",
        total_today,
        DAILY_POST_LIMIT,
        startup_today,
        STARTUP_MIN_QUOTA,
    )

    # Günlük limit dolmuş
    if total_today >= DAILY_POST_LIMIT:
        logger.info("Günlük paylaşım limiti doldu (%d/%d).", total_today, DAILY_POST_LIMIT)
        return "__LIMIT_REACHED__"

    remaining_slots: int = DAILY_POST_LIMIT - total_today
    remaining_startup_quota: int = max(0, STARTUP_MIN_QUOTA - startup_today)

    # Kalan slot sayısı, kalan Startup kotasına eşit veya azsa → Startup zorunlu
    if remaining_startup_quota >= remaining_slots:
        logger.info("Startup kotası zorlanıyor ─ kalan kota=%d, kalan slot=%d",
                    remaining_startup_quota, remaining_slots)
        return "Startup"

    # Startup kotası henüz dolmadıysa, Startup'a öncelik ver (ama zorunlu değil)
    if remaining_startup_quota > 0:
        # %70 ihtimalle Startup, %30 ihtimalle serbest
        if random.random() < 0.7:
            return "Startup"

    # Serbest seçim (herhangi bir kategori)
    return None


# ─────────────────────────────────────────────────────────────
# X (Twitter) Paylaşımı
# ─────────────────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def publish_to_x(text: str, url: str) -> bool:
    """
    X (Twitter)'da tweet paylaşır.
    Metin + kaynak URL birleştirilir.
    """
    from twikit import Client

    try:
        client = Client(language="tr")

        # Oturum yükle
        if X_COOKIES_FILE.exists():
            client.load_cookies(str(X_COOKIES_FILE))
        elif X_USERNAME and X_PASSWORD:
            await client.login(
                auth_info_1=X_USERNAME,
                auth_info_2=X_EMAIL,
                password=X_PASSWORD,
            )
            client.save_cookies(str(X_COOKIES_FILE))
        else:
            logger.error("X kimlik bilgileri yapılandırılmamış.")
            return False

        # Tweet metnini hazırla (280 karakter limiti)
        full_text: str = f"{text}\n\n🔗 {url}"
        if len(full_text) > 280:
            available: int = 280 - len(f"\n\n🔗 {url}") - 3  # "..." için 3 karakter
            full_text = f"{text[:available]}...\n\n🔗 {url}"

        await client.create_tweet(text=full_text)

        # Çerezleri güncelle
        try:
            client.save_cookies(str(X_COOKIES_FILE))
        except Exception:
            pass

        logger.info("X'te paylaşıldı ✓ ─ %s", text[:60])
        return True

    except Exception as exc:
        logger.error("X paylaşım hatası: %s", exc)
        raise


# ─────────────────────────────────────────────────────────────
# Threads Paylaşımı
# ─────────────────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=5, max=60),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def publish_to_threads(text: str, url: str) -> bool:
    """
    Threads'te gönderi paylaşır.
    threads-api kütüphanesi kullanılır.
    """
    try:
        from threads_api import ThreadsAPI

        api = ThreadsAPI()

        # Oturum dosyası varsa yükle
        if THREADS_SESSION_FILE.exists():
            try:
                api.load_session(str(THREADS_SESSION_FILE))
            except Exception:
                pass

        # Oturum yoksa giriş yap
        if not api.is_logged_in:
            if THREADS_USERNAME and THREADS_PASSWORD:
                await api.login(THREADS_USERNAME, THREADS_PASSWORD)
                try:
                    api.save_session(str(THREADS_SESSION_FILE))
                except Exception:
                    pass
            else:
                logger.error("Threads kimlik bilgileri yapılandırılmamış.")
                return False

        # Gönderi metnini hazırla (500 karakter limiti)
        full_text: str = f"{text}\n\n🔗 {url}"
        if len(full_text) > 500:
            available: int = 500 - len(f"\n\n🔗 {url}") - 3
            full_text = f"{text[:available]}...\n\n🔗 {url}"

        await api.publish(text=full_text)

        logger.info("Threads'te paylaşıldı ✓ ─ %s", text[:60])
        return True

    except ImportError:
        logger.warning(
            "threads-api kütüphanesi yüklü değil. "
            "Threads paylaşımı devre dışı."
        )
        return False
    except Exception as exc:
        logger.error("Threads paylaşım hatası: %s", exc)
        raise


# ─────────────────────────────────────────────────────────────
# Ana Paylaşıcı Fonksiyonu (Scheduler tarafından çağrılır)
# ─────────────────────────────────────────────────────────────
async def run_publisher() -> None:
    """
    Ana paylaşıcı görevi. Her saat başı çalışır.
    1. Kota durumunu kontrol eder.
    2. Uygun kategoriyi belirler.
    3. Havuzdan en yeni haberi seçer.
    4. X ve Threads'te paylaşır.
    5. Haberi 'paylaşıldı' olarak işaretler.
    """
    logger.info("═" * 60)
    logger.info("PAYLAŞICI BAŞLADI")
    logger.info("═" * 60)

    try:
        # 1. Kota kontrolü
        required_category: Optional[str] = await _determine_required_category()

        if required_category == "__LIMIT_REACHED__":
            logger.info("Günlük limit doldu, paylaşım atlanıyor.")
            return

        # 2. Haber seç
        news: Optional[Dict[str, Any]] = await pick_next_news(
            force_category=required_category
        )

        # Zorlanan kategori bulunamadıysa, serbest seçim dene
        if news is None and required_category is not None:
            logger.info(
                "'%s' kategorisinde paylaşılacak haber yok, serbest seçim deneniyor.",
                required_category,
            )
            news = await pick_next_news(force_category=None)

        if news is None:
            logger.warning("Paylaşılacak haber bulunamadı. Havuz boş.")
            return

        news_id: int = news["id"]
        text: str = news["sosyal_medya_metni"]
        url: str = news["kaynak_url"]
        kategori: str = news["kategori"]

        logger.info(
            "Paylaşılacak haber ─ id=%d, kategori=%s, url=%s",
            news_id,
            kategori,
            url[:60],
        )

        # 3. X'te paylaş
        x_success: bool = False
        try:
            x_success = await publish_to_x(text, url)
        except Exception as exc:
            logger.error("X paylaşımı başarısız (tüm denemeler tükendi): %s", exc)

        # Platformlar arası gecikme
        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # 4. Threads'te paylaş
        threads_success: bool = False
        try:
            threads_success = await publish_to_threads(text, url)
        except Exception as exc:
            logger.error("Threads paylaşımı başarısız (tüm denemeler tükendi): %s", exc)

        # 5. En az birinde başarılı olduysa, paylaşıldı olarak işaretle
        if x_success or threads_success:
            await mark_as_published(news_id)
            logger.info(
                "Paylaşım tamamlandı ─ id=%d, X=%s, Threads=%s",
                news_id,
                "✓" if x_success else "✗",
                "✓" if threads_success else "✗",
            )
        else:
            logger.error(
                "Her iki platformda da paylaşım başarısız ─ id=%d", news_id
            )

    except Exception as exc:
        logger.error("Paylaşıcıda kritik hata: %s", exc)

    logger.info("═" * 60)
