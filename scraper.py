"""
Haber Kölesi - Toplayıcı (Scraper) Modülü
==========================================
RSS ve X (Twitter) kaynaklarından haber toplar,
İngilizce içerikleri Türkçe'ye çevirir, Gemini ile skorlar
ve uygun haberleri veritabanına kaydeder.
"""

import asyncio
import json
import logging
import random
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import aiohttp
import feedparser
import trafilatura
from deep_translator import GoogleTranslator
from fake_useragent import UserAgent
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import google.generativeai as genai

from config import (
    RSS_FEEDS,
    X_ACCOUNTS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_MIN_SCORE,
    GEMINI_SYSTEM_PROMPT,
    DEFAULT_HEADERS,
    MIN_DELAY,
    MAX_DELAY,
    TURKISH_DOMAINS,
    X_COOKIES_FILE,
    X_USERNAME,
    X_EMAIL,
    X_PASSWORD,
)
from database import url_exists, insert_news

logger: logging.Logger = logging.getLogger("haberkolesi.scraper")
ua: UserAgent = UserAgent(browsers=["chrome", "firefox", "edge"])

# ─────────────────────────────────────────────────────────────
# Gemini API Yapılandırması
# ─────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
_gemini_model = genai.GenerativeModel(
    model_name=GEMINI_MODEL,
    system_instruction=GEMINI_SYSTEM_PROMPT,
)


# ─────────────────────────────────────────────────────────────
# Yardımcı Fonksiyonlar
# ─────────────────────────────────────────────────────────────
def _get_stealth_headers() -> Dict[str, str]:
    """Her istekte değişen, gerçek tarayıcı User-Agent'ı ile gizli header seti."""
    headers = DEFAULT_HEADERS.copy()
    headers["User-Agent"] = ua.random
    return headers


async def _random_delay() -> None:
    """Anti-bot: İnsan davranışını taklit eden rastgele gecikme."""
    delay: float = random.uniform(MIN_DELAY, MAX_DELAY)
    await asyncio.sleep(delay)


def _is_turkish_source(url: str) -> bool:
    """URL'nin Türkçe bir kaynağa ait olup olmadığını kontrol eder."""
    domain: str = urlparse(url).netloc.lower()
    return any(td in domain for td in TURKISH_DOMAINS)


def _clean_text(text: str) -> str:
    """Metni temizler: fazla boşluklar, HTML kalıntıları vb."""
    text = re.sub(r"<[^>]+>", "", text)  # HTML etiketlerini kaldır
    text = re.sub(r"\s+", " ", text)     # Çoklu boşlukları tek boşluğa indir
    return text.strip()


def _truncate_for_translation(text: str, max_chars: int = 4500) -> str:
    """Deep-translator karakter limitine uygun olarak metni kısaltır."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


# ─────────────────────────────────────────────────────────────
# İçerik Çekme (Trafilatura)
# ─────────────────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def fetch_article_content(url: str) -> Optional[str]:
    """URL'den makale içeriğini trafilatura ile çeker."""
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(
            headers=_get_stealth_headers(), timeout=timeout
        ) as session:
            async with session.get(url, ssl=False) as response:
                if response.status != 200:
                    logger.warning(
                        "HTTP %d ─ İçerik çekilemedi: %s", response.status, url[:80]
                    )
                    return None
                html: str = await response.text()

        content: Optional[str] = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )

        if content and len(content) > 100:
            return _clean_text(content)

        logger.warning("İçerik çok kısa veya boş ─ %s", url[:80])
        return None

    except Exception as exc:
        logger.error("İçerik çekme hatası ─ %s: %s", url[:80], exc)
        raise


# ─────────────────────────────────────────────────────────────
# Çeviri (Deep Translator)
# ─────────────────────────────────────────────────────────────
def translate_to_turkish(text: str) -> str:
    """Metni Türkçe'ye çevirir. Zaten Türkçe ise olduğu gibi döndürür."""
    try:
        truncated: str = _truncate_for_translation(text)
        translated: str = GoogleTranslator(
            source="auto", target="tr"
        ).translate(truncated)
        return translated or text
    except Exception as exc:
        logger.error("Çeviri hatası: %s", exc)
        return text  # Çeviri başarısız olursa orijinali döndür


# ─────────────────────────────────────────────────────────────
# Gemini Skorlama
# ─────────────────────────────────────────────────────────────
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=5, max=120),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def score_with_gemini(text: str) -> Optional[Dict[str, Any]]:
    """
    Gemini API ile haberi skorlar.
    Skor 8+ ise sosyal medya metni ile birlikte sonuç döndürür.
    Rate limit (429) hatalarında exponential backoff ile yeniden dener.
    """
    try:
        response = await asyncio.to_thread(
            _gemini_model.generate_content,
            text[:3000],  # Token limitine uygun kısaltma
        )

        raw_text: str = response.text.strip()

        # JSON bloğunu parse et (```json ... ``` formatını da destekle)
        json_match = re.search(r"\{[^{}]*\}", raw_text, re.DOTALL)
        if not json_match:
            logger.warning("Gemini'den JSON çıktısı alınamadı: %s", raw_text[:200])
            return None

        result: Dict[str, Any] = json.loads(json_match.group())

        skor: float = float(result.get("skor", 0))
        kategori: str = result.get("kategori", "Teknoloji")
        sosyal_medya_metni: str = result.get("sosyal_medya_metni", "")
        neden: str = result.get("neden", "")

        # Kategori doğrulaması
        valid_categories: List[str] = ["Startup", "Teknoloji", "AI", "Yazilim"]
        if kategori not in valid_categories:
            kategori = "Teknoloji"  # Varsayılan

        logger.info(
            "Gemini skorlaması ─ skor=%.1f, kategori=%s, neden=%s",
            skor,
            kategori,
            neden[:80],
        )

        if skor < GEMINI_MIN_SCORE:
            logger.info("Skor düşük (%.1f < %.1f), atlanıyor.", skor, GEMINI_MIN_SCORE)
            return None

        return {
            "skor": skor,
            "kategori": kategori,
            "sosyal_medya_metni": sosyal_medya_metni,
            "neden": neden,
        }

    except json.JSONDecodeError as exc:
        logger.error("Gemini JSON parse hatası: %s", exc)
        return None
    except Exception as exc:
        logger.error("Gemini API hatası: %s", exc)
        raise  # tenacity yeniden deneyecek


# ─────────────────────────────────────────────────────────────
# RSS Toplayıcı
# ─────────────────────────────────────────────────────────────
async def _process_rss_entry(
    entry: Any, category: str
) -> Optional[int]:
    """Tek bir RSS girdisini işler: kontrol → çek → çevir → skorla → kaydet."""
    url: str = entry.get("link", "").strip()
    if not url:
        return None

    # Veritabanı kontrolü — zaten işlenmişse atla
    if await url_exists(url):
        return None

    logger.info("Yeni haber bulundu ─ [%s] %s", category, url[:80])

    # İçerik çek
    content: Optional[str] = await fetch_article_content(url)
    if not content:
        return None

    original_text: str = content

    # Türkçe kaynaksa çeviri yapma
    if _is_turkish_source(url):
        translated_text: str = content
    else:
        translated_text = translate_to_turkish(content)

    # Gemini skorlama
    await _random_delay()  # API rate limit koruması
    result: Optional[Dict[str, Any]] = await score_with_gemini(translated_text)
    if not result:
        return None

    # Veritabanına kaydet
    news_id: Optional[int] = await insert_news(
        kaynak_url=url,
        orjinal_metin=original_text,
        cevrilmis_metin=translated_text,
        sosyal_medya_metni=result["sosyal_medya_metni"],
        kategori=result["kategori"],
        skor=result["skor"],
    )

    return news_id


async def collect_from_rss() -> int:
    """Tüm RSS feed'lerini tarar ve yeni haberleri işler."""
    total_added: int = 0

    for category, feeds in RSS_FEEDS.items():
        for feed_url in feeds:
            try:
                logger.info("RSS taranıyor ─ [%s] %s", category, feed_url[:60])

                # feedparser senkron — thread'de çalıştır
                feed = await asyncio.to_thread(feedparser.parse, feed_url)

                if feed.bozo and not feed.entries:
                    logger.warning(
                        "RSS parse hatası ─ %s: %s",
                        feed_url[:60],
                        feed.bozo_exception,
                    )
                    continue

                entries = feed.entries[:10]  # Her feed'den max 10 girdi
                logger.info(
                    "%d girdi bulundu ─ %s", len(entries), feed_url[:60]
                )

                for entry in entries:
                    try:
                        result = await _process_rss_entry(entry, category)
                        if result:
                            total_added += 1
                        await _random_delay()
                    except Exception as exc:
                        logger.error(
                            "RSS girdi işleme hatası ─ %s: %s",
                            entry.get("link", "?")[:60],
                            exc,
                        )
                        continue

            except Exception as exc:
                logger.error("RSS feed hatası ─ %s: %s", feed_url[:60], exc)
                continue

    return total_added


# ─────────────────────────────────────────────────────────────
# X (Twitter) Toplayıcı
# ─────────────────────────────────────────────────────────────
async def _get_twikit_client():
    """Twikit istemcisini oluşturur ve oturum açar."""
    from twikit import Client

    client = Client(language="tr")

    # Kayıtlı çerezlerden oturum aç
    if X_COOKIES_FILE.exists():
        try:
            client.load_cookies(str(X_COOKIES_FILE))
            logger.info("X oturumu çerezlerden yüklendi.")
            return client
        except Exception as exc:
            logger.warning("Çerez yükleme hatası, yeniden giriş yapılıyor: %s", exc)

    # Kullanıcı adı/şifre ile giriş
    if X_USERNAME and X_PASSWORD:
        try:
            await client.login(
                auth_info_1=X_USERNAME,
                auth_info_2=X_EMAIL,
                password=X_PASSWORD,
            )
            client.save_cookies(str(X_COOKIES_FILE))
            logger.info("X oturumu açıldı ve çerezler kaydedildi.")
            return client
        except Exception as exc:
            logger.error("X giriş hatası: %s", exc)
            return None

    logger.warning("X kimlik bilgileri yapılandırılmamış.")
    return None


async def collect_from_twitter() -> int:
    """X (Twitter) hesaplarından tweet toplar."""
    total_added: int = 0

    client = await _get_twikit_client()
    if client is None:
        logger.warning("X istemcisi oluşturulamadı, Twitter toplama atlanıyor.")
        return 0

    for category, accounts in X_ACCOUNTS.items():
        for username in accounts:
            try:
                logger.info("X hesabı taranıyor ─ [%s] @%s", category, username)

                # Kullanıcıyı bul
                user = await client.get_user_by_screen_name(username)
                if not user:
                    logger.warning("X kullanıcısı bulunamadı: @%s", username)
                    continue

                # Son tweetleri al
                tweets = await user.get_tweets(tweet_type="Tweets", count=10)
                if not tweets:
                    continue

                for tweet in tweets:
                    try:
                        tweet_url: str = f"https://x.com/{username}/status/{tweet.id}"

                        # Veritabanı kontrolü
                        if await url_exists(tweet_url):
                            continue

                        tweet_text: str = tweet.text or ""
                        if len(tweet_text) < 30:  # Çok kısa tweetleri atla
                            continue

                        # RT'leri atla
                        if tweet_text.startswith("RT @"):
                            continue

                        original_text: str = tweet_text

                        # Tweet içindeki URL'leri çek, varsa makale içeriğini al
                        if tweet.urls:
                            for url_data in tweet.urls[:1]:  # İlk URL yeter
                                expanded_url = getattr(url_data, "expanded_url", None) or str(url_data)
                                if expanded_url and not expanded_url.startswith("https://x.com"):
                                    article = await fetch_article_content(expanded_url)
                                    if article:
                                        original_text = article
                                        tweet_url = expanded_url  # Kaynak URL olarak makale URL'sini kullan
                                    break

                        # Veritabanı tekrar kontrolü (URL değişmiş olabilir)
                        if await url_exists(tweet_url):
                            continue

                        logger.info("Yeni tweet bulundu ─ [%s] @%s", category, username)

                        # Çevir
                        translated: str = translate_to_turkish(original_text)

                        # Skorla
                        await _random_delay()
                        result = await score_with_gemini(translated)
                        if not result:
                            continue

                        # Kaydet
                        news_id = await insert_news(
                            kaynak_url=tweet_url,
                            orjinal_metin=original_text,
                            cevrilmis_metin=translated,
                            sosyal_medya_metni=result["sosyal_medya_metni"],
                            kategori=result["kategori"],
                            skor=result["skor"],
                        )
                        if news_id:
                            total_added += 1

                        await _random_delay()

                    except Exception as exc:
                        logger.error("Tweet işleme hatası ─ @%s: %s", username, exc)
                        continue

                await _random_delay()  # Hesaplar arası gecikme

            except Exception as exc:
                logger.error("X hesap tarama hatası ─ @%s: %s", username, exc)
                continue

    # Çerezleri güncelle
    try:
        client.save_cookies(str(X_COOKIES_FILE))
    except Exception:
        pass

    return total_added


# ─────────────────────────────────────────────────────────────
# Ana Toplayıcı Fonksiyonu (Scheduler tarafından çağrılır)
# ─────────────────────────────────────────────────────────────
async def run_collector() -> None:
    """
    Ana toplayıcı görevi. Her çalıştığında:
    1. RSS feed'lerini tarar
    2. X (Twitter) hesaplarını tarar
    Sonuçları loglar.
    """
    logger.info("═" * 60)
    logger.info("TOPLAYICI BAŞLADI")
    logger.info("═" * 60)

    rss_count: int = 0
    twitter_count: int = 0

    try:
        rss_count = await collect_from_rss()
        logger.info("RSS toplama tamamlandı ─ %d yeni haber eklendi.", rss_count)
    except Exception as exc:
        logger.error("RSS toplama sırasında kritik hata: %s", exc)

    try:
        twitter_count = await collect_from_twitter()
        logger.info(
            "X toplama tamamlandı ─ %d yeni haber eklendi.", twitter_count
        )
    except Exception as exc:
        logger.error("X toplama sırasında kritik hata: %s", exc)

    total: int = rss_count + twitter_count
    logger.info(
        "TOPLAYICI TAMAMLANDI ─ Toplam %d yeni haber (RSS: %d, X: %d)",
        total,
        rss_count,
        twitter_count,
    )
    logger.info("═" * 60)
