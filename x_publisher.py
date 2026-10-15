"""X (Twitter) paylaşım servisi — Resmi X API v2 ve twikit desteği ile.

İki katmandan oluşur:

* İstemci katmanı:
  - ``OfficialXClient``: Resmi X API v2 (OAuth 1.0a User Context ile, tweepy tabanlı).
    Tweet atma: POST /2/tweets
    Görsel yükleme: POST /1.1/media/upload.json
  - ``TwikitXClient``: Gayriresmi (çerez tabanlı) istemci.
* ``XPublisher``: İş kuralları katmanı. Yalnız onaylı ve henüz paylaşılmamış haberleri
  paylaşır, günlük limiti uygular, hataları kaydeder ve zamanlanmış dilimlerde
  kuyruktaki en uygun haberi seçer.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Tuple
from zoneinfo import ZoneInfo

from domain import NewsRecord, NewsState


logger = logging.getLogger("haberkolesi.x_publisher")

ISTANBUL = ZoneInfo("Europe/Istanbul")
X_MAX_CHARS = 280


# ─────────────────────────────────────────────────────────────
# Hatalar
# ─────────────────────────────────────────────────────────────
class XPublishError(RuntimeError):
    """X paylaşımı başarısız oldu."""


class XNotConfiguredError(XPublishError):
    """X kimlik bilgileri tanımlı değil."""


class XAuthError(XPublishError):
    """Oturum veya kimlik doğrulama geçersiz."""

    def __init__(self, message: str, *, reauthable: bool = False):
        super().__init__(message)
        self.reauthable = reauthable


class XRateLimitedError(XPublishError):
    """X istek limiti aşıldı (429)."""

    def __init__(self, message: str, *, reset_at: Optional[datetime] = None):
        super().__init__(message)
        self.reset_at = reset_at


def _translate_tweepy_error(exc: Exception) -> XPublishError:
    """Tweepy istisnalarını açıklayıcı uygulama hatalarına çevirir."""
    name = type(exc).__name__
    detail = str(exc) or name

    if name == "Unauthorized":
        return XAuthError(
            f"X API kimlik doğrulama başarısız (401 Unauthorized). "
            f"API Key / Secret ve Access Token / Secret değerlerini kontrol edin: {detail}"
        )
    if name == "Forbidden":
        return XPublishError(
            f"X API yetki hatası (403 Forbidden). "
            f"Developer Portal'da App Permissions ayarının 'Read and Write' olduğundan "
            f"ve Access Token'ın bu ayar yapıldıktan SONRA üretildiğinden emin olun: {detail}"
        )
    if name == "TooManyRequests":
        return XRateLimitedError(
            f"X API istek limiti aşıldı (429 Too Many Requests): {detail}"
        )
    return XPublishError(f"Resmi X API paylaşım hatası ({name}): {detail}")


def _translate_twikit_error(exc: Exception) -> XPublishError:
    """twikit istisnalarını sınıf adına göre eşler (sürüm farklarına dayanıklı)."""
    name = type(exc).__name__
    detail = str(exc) or name
    if name == "Unauthorized":
        return XAuthError(f"X oturumu geçersiz: {detail}", reauthable=True)
    if name in {"AccountLocked", "AccountSuspended"}:
        return XAuthError(
            f"X hesabı kilitli veya askıya alınmış: {detail}", reauthable=False
        )
    if name == "TooManyRequests":
        reset = getattr(exc, "rate_limit_reset", None)
        reset_at = (
            datetime.fromtimestamp(int(reset), tz=timezone.utc) if reset else None
        )
        return XRateLimitedError(f"X istek limiti aşıldı: {detail}", reset_at=reset_at)
    if name == "DuplicateTweet":
        return XPublishError("X bu metni daha önce paylaşılmış bir tweetle aynı buldu")
    if name == "Forbidden":
        return XPublishError(
            f"X isteği reddetti (403). Hesap otomasyon kontrolüne takılmış olabilir: {detail}"
        )
    return XPublishError(f"X paylaşım hatası ({name}): {detail}")


# ─────────────────────────────────────────────────────────────
# 1. Resmi X API v2 İstemcisi (Tweepy / OAuth 1.0a)
# ─────────────────────────────────────────────────────────────
class OfficialXClient:
    """Resmi X API v2 istemcisi (OAuth 1.0a User Context ile).

    Tweet atma: POST /2/tweets
    Görsel yükleme: POST /1.1/media/upload.json
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_key_secret: str,
        access_token: str,
        access_token_secret: str,
    ):
        self.api_key = api_key.strip()
        self.api_key_secret = api_key_secret.strip()
        self.access_token = access_token.strip()
        self.access_token_secret = access_token_secret.strip()

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key
            and self.api_key_secret
            and self.access_token
            and self.access_token_secret
        )

    async def reset_session(self) -> None:
        """Resmi API için oturum sıfırlama no-op'tur (statik anahtarlar)."""
        pass

    async def post(self, text: str, image_path: Optional[str] = None) -> str:
        if not self.configured:
            raise XNotConfiguredError(
                "Resmi X API kimlik bilgileri eksik. "
                "X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN ve X_ACCESS_TOKEN_SECRET tanımlanmalıdır."
            )
        return await asyncio.to_thread(self._sync_post, text, image_path)

    def _sync_post(self, text: str, image_path: Optional[str] = None) -> str:
        import tweepy

        media_ids = None
        if image_path and Path(image_path).is_file():
            try:
                auth = tweepy.OAuth1UserHandler(
                    self.api_key,
                    self.api_key_secret,
                    self.access_token,
                    self.access_token_secret,
                )
                v1_api = tweepy.API(auth)
                media = v1_api.media_upload(filename=str(image_path))
                media_ids = [media.media_id]
                logger.info("X görseli yüklendi (media_id=%s)", media.media_id)
            except Exception as exc:
                logger.error("Görsel yüklenirken hata oluştu: %s", exc)
                raise _translate_tweepy_error(exc) from exc
        elif image_path:
            logger.warning("Görsel dosyası bulunamadı, tweet görselsiz atılacak: %s", image_path)

        try:
            client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_key_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
            )
            response = client.create_tweet(text=text, media_ids=media_ids)
            if not response or not response.data or "id" not in response.data:
                raise XPublishError("X API yanıtında tweet kimliği (id) bulunamadı")
            tweet_id = str(response.data["id"])
            logger.info("Resmi X API ile tweet paylaşıldı (id=%s)", tweet_id)
            return tweet_id
        except Exception as exc:
            raise _translate_tweepy_error(exc) from exc


# ─────────────────────────────────────────────────────────────
# 2. Alternatif / Gayriresmi twikit İstemcisi
# ─────────────────────────────────────────────────────────────
class TwikitXClient:
    def __init__(
        self,
        *,
        cookies_file: Path,
        username: str = "",
        email: str = "",
        password: str = "",
        totp_secret: str = "",
        auth_token: str = "",
        ct0: str = "",
        proxy: str = "",
        language: str = "tr-TR",
        client_factory: Optional[Callable[..., Any]] = None,
    ):
        self.cookies_file = Path(cookies_file)
        self.username = username
        self.email = email
        self.password = password
        self.totp_secret = totp_secret
        self.auth_token = auth_token
        self.ct0 = ct0
        self.proxy = proxy
        self.language = language
        self._client_factory = client_factory
        self._client: Any = None
        self._session_source: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(
            (self.auth_token and self.ct0)
            or self.cookies_file.exists()
            or (self.username and self.password)
        )

    def _new_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        from twikit import Client

        kwargs = {"language": self.language}
        if self.proxy:
            kwargs["proxy"] = self.proxy
        return Client(**kwargs)

    async def _ensure_client(self) -> Any:
        async with self._lock:
            if self._client is not None:
                return self._client
            client = self._new_client()
            if self.auth_token and self.ct0:
                client.set_cookies({"auth_token": self.auth_token, "ct0": self.ct0})
                self._session_source = "env"
                logger.info("X oturumu ortam değişkenindeki çerezlerle açıldı")
            elif self.cookies_file.exists():
                client.load_cookies(str(self.cookies_file))
                self._session_source = "file"
                logger.info("X oturumu kayıtlı çerez dosyasından yüklendi")
            elif self.username and self.password:
                self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    await client.login(
                        auth_info_1=self.username,
                        auth_info_2=self.email or None,
                        password=self.password,
                        totp_secret=self.totp_secret or None,
                        cookies_file=str(self.cookies_file),
                    )
                except Exception as exc:
                    raise XAuthError(
                        f"X girişi başarısız: {exc}", reauthable=False
                    ) from exc
                self._session_source = "login"
                logger.info("X'e kullanıcı adı/şifre ile giriş yapıldı, çerezler kaydedildi")
            else:
                raise XNotConfiguredError(
                    "X kimlik bilgileri tanımlı değil"
                )
            self._client = client
            return client

    async def reset_session(self) -> None:
        """Geçersiz oturumu bırakır. Çerez dosyası bozuksa siler."""
        async with self._lock:
            self._client = None
            if self._session_source in {"file", "login"} and self.cookies_file.exists():
                try:
                    self.cookies_file.unlink()
                    logger.warning("Geçersiz X çerez dosyası silindi")
                except OSError:
                    logger.exception("X çerez dosyası silinemedi")
            self._session_source = None

    def _persist_cookies(self, client: Any) -> None:
        if self._session_source == "env":
            return
        try:
            client.save_cookies(str(self.cookies_file))
        except Exception:
            logger.debug("X çerezleri kaydedilemedi", exc_info=True)

    async def post(self, text: str, image_path: Optional[str] = None) -> str:
        client = await self._ensure_client()
        try:
            media_ids = None
            if image_path and Path(image_path).is_file():
                media_id = await client.upload_media(image_path)
                media_ids = [media_id]
            elif image_path:
                logger.warning("Görsel bulunamadı, tweet görselsiz atılacak: %s", image_path)
            tweet = await client.create_tweet(text=text, media_ids=media_ids)
        except XPublishError:
            raise
        except Exception as exc:
            raise _translate_twikit_error(exc) from exc
        self._persist_cookies(client)
        tweet_id = getattr(tweet, "id", None)
        if not tweet_id:
            raise XPublishError("X tweet kimliği döndürmedi")
        return str(tweet_id)


# ─────────────────────────────────────────────────────────────
# 3. İş Kuralları Katmanı (XPublisher)
# ─────────────────────────────────────────────────────────────
def istanbul_day_start(moment: datetime) -> datetime:
    local = moment.astimezone(ISTANBUL)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def tweet_text_for(record: NewsRecord) -> str:
    text = ((record.platform_texts or {}).get("x") or record.draft_text or "").strip()
    if not text:
        raise ValueError("Bu haber için X metni yok")
    if len(text) > X_MAX_CHARS:
        raise ValueError(f"X metni {X_MAX_CHARS} karakteri aşıyor")
    return text


class XPublisher:
    def __init__(
        self,
        repository,
        client,
        *,
        daily_limit: int = 8,
        max_attempts: int = 3,
        approval_window: timedelta = timedelta(hours=48),
        jitter_seconds: Tuple[float, float] = (30.0, 420.0),
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleeper: Optional[Callable[[float], Awaitable[None]]] = None,
        rng: Optional[random.Random] = None,
    ):
        self.repository = repository
        self.client = client
        self.daily_limit = daily_limit
        self.max_attempts = max_attempts
        self.approval_window = approval_window
        self.jitter_seconds = jitter_seconds
        self.now = now
        self.sleeper = sleeper or asyncio.sleep
        self.rng = rng or random.Random()
        self._lock = asyncio.Lock()

    async def publish_news(self, news_id: int) -> str:
        """Tek bir onaylı haberi X'te paylaşır ve tweet kimliğini döndürür."""
        async with self._lock:
            record = await self.repository.get_news(news_id)
            if record.x_published_at is not None:
                raise ValueError("Bu haber zaten X'te paylaşıldı")
            if record.state is not NewsState.APPROVED:
                raise ValueError("Yalnız onaylanmış haberler X'te paylaşılabilir")
            text = tweet_text_for(record)

            published_today = await self.repository.count_x_published_since(
                istanbul_day_start(self.now())
            )
            if published_today >= self.daily_limit:
                raise XPublishError(
                    f"Günlük X paylaşım limiti doldu ({published_today}/{self.daily_limit})"
                )

            try:
                tweet_id = await self._post_with_reauth(text, record.image_path)
            except XRateLimitedError as exc:
                logger.warning("X limitine takıldı — haber #%d: %s", news_id, exc)
                raise
            except XPublishError as exc:
                await self.repository.record_x_failure(news_id, str(exc))
                logger.error("X paylaşımı başarısız — haber #%d: %s", news_id, exc)
                raise

            await self.repository.mark_x_published(news_id, tweet_id, self.now())
            logger.info("X'te paylaşıldı — haber #%d, tweet %s", news_id, tweet_id)
            return tweet_id

    async def _post_with_reauth(self, text: str, image_path: Optional[str]) -> str:
        try:
            return await self.client.post(text, image_path)
        except XAuthError as exc:
            if not exc.reauthable:
                raise
            logger.warning("X oturumu düştü, yeniden deneniyor: %s", exc)
            await self.client.reset_session()
            return await self.client.post(text, image_path)

    async def publish_scheduled(self, slot) -> Optional[str]:
        """Yayın diliminde kuyruktaki en uygun onaylı haberi paylaşır."""
        low, high = self.jitter_seconds
        if high > 0:
            await self.sleeper(self.rng.uniform(low, high))
        try:
            candidate = await self.repository.next_x_candidate(
                preferred_category=slot.category,
                approved_since=self.now() - self.approval_window,
                max_attempts=self.max_attempts,
            )
            if candidate is None:
                logger.info(
                    "%02d:00 X dilimi: paylaşılacak onaylı haber yok", slot.hour
                )
                return None
            return await self.publish_news(candidate.id)
        except Exception:
            logger.exception("%02d:00 X dilimi paylaşımı başarısız", slot.hour)
            return None
