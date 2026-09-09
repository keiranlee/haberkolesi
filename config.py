"""
Haber Kölesi - Yapılandırma Modülü
===================================
Tüm sabitler, haber kaynakları ve çevre değişkenleri burada tanımlanır.
"""

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Dizin Yapılandırması
# ─────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE: Path = DATA_DIR / "app.log"
X_COOKIES_FILE: Path = DATA_DIR / "x_cookies.json"
THREADS_SESSION_FILE: Path = DATA_DIR / "threads_session.json"

# ─────────────────────────────────────────────────────────────
# Loglama Yapılandırması
# ─────────────────────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    """Profesyonel loglama yapılandırması. Konsol + dosya çıktısı."""
    logger = logging.getLogger("haberkolesi")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Konsol handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Dosya handler
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger


logger: logging.Logger = setup_logging()

# ─────────────────────────────────────────────────────────────
# Veritabanı
# ─────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgres://postgres:password@localhost:5432/havuz",
)
DB_MIN_POOL: int = int(os.getenv("DB_MIN_POOL", "2"))
DB_MAX_POOL: int = int(os.getenv("DB_MAX_POOL", "10"))

# ─────────────────────────────────────────────────────────────
# Gemini API
# ─────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_MIN_SCORE: float = float(os.getenv("GEMINI_MIN_SCORE", "8.0"))
GEMINI_MIN_INTERVAL_SECONDS: float = float(
    os.getenv("GEMINI_MIN_INTERVAL_SECONDS", "15")
)
CANDIDATE_LIMIT_PER_CATEGORY: int = int(
    os.getenv("CANDIDATE_LIMIT_PER_CATEGORY", "3")
)

GEMINI_SYSTEM_PROMPT: str = """Sen objektif ve tecrübeli bir teknoloji/girişim editörüsün. \
Sana verilen Türkçe metni 10 üzerinden skorla. Startup, girişimcilik ve yapay zeka \
haberlerine her zaman ÖNCELİK ver. Skoru 8 ve üzeriyse, bunu X ve Threads'te \
paylaşılacak şekilde, akıcı, dikkat çekici, Türkçe dil kurallarına uygun, ilgili \
hashtagleri barındıran YENİ BİR METİN olarak yaz. Link için cümlenin sonunda yer bırak. \
Çıktıyı SADECE şu JSON formatında ver:
{
  "skor": 8.5,
  "kategori": "Startup",
  "neden": "Neden bu puanı aldı?",
  "sosyal_medya_metni": "Hazırlanan metin..."
}
Kategori değeri SADECE 'Startup', 'Teknoloji', 'AI' veya 'Yazilim' olmalıdır."""

# ─────────────────────────────────────────────────────────────
# X (Twitter) Kimlik Bilgileri
# ─────────────────────────────────────────────────────────────
X_USERNAME: str = os.getenv("X_USERNAME", "")
X_EMAIL: str = os.getenv("X_EMAIL", "")
X_PASSWORD: str = os.getenv("X_PASSWORD", "")

# ─────────────────────────────────────────────────────────────
# Threads Kimlik Bilgileri
# ─────────────────────────────────────────────────────────────
THREADS_USERNAME: str = os.getenv("THREADS_USERNAME", "")
THREADS_PASSWORD: str = os.getenv("THREADS_PASSWORD", "")

# ─────────────────────────────────────────────────────────────
# Zamanlama Yapılandırması
# ─────────────────────────────────────────────────────────────
TIMEZONE: str = "Europe/Istanbul"
PUBLISH_START_HOUR: int = 7   # 07:00 TR
PUBLISH_END_HOUR: int = 0     # 00:00 TR (gece yarısı)
DAILY_POST_LIMIT: int = 18
STARTUP_MIN_QUOTA: int = 10

# ─────────────────────────────────────────────────────────────
# Anti-Bot / Stealth Yapılandırması
# ─────────────────────────────────────────────────────────────
MIN_DELAY: float = float(os.getenv("MIN_DELAY", "2.0"))
MAX_DELAY: float = float(os.getenv("MAX_DELAY", "7.0"))

DEFAULT_HEADERS: Dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

# ─────────────────────────────────────────────────────────────
# Haber Kaynakları — RSS Feed'leri
# ─────────────────────────────────────────────────────────────
RSS_FEEDS: Dict[str, List[str]] = {
    "Startup": [
        "https://swipeline.co/feed/",
        "https://egirisim.com/feed/",
        "https://foundern.com/feed/",
        "https://www.entrepreneur.com/latest.rss",
        "https://www.forbes.com/innovation/feed/",
    ],
    "Teknoloji": [
        "https://www.donanimhaber.com/rss/tum/",
        "https://shiftdelete.net/feed/",
        "https://www.technopat.net/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
    ],
    "AI": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://www.marktechpost.com/feed/",
        "https://www.artificialintelligence-news.com/feed/",
        "https://news.mit.edu/rss/topic/artificial-intelligence2",
        "https://arstechnica.com/tag/ai/feed/",
    ],
    "Yazilim": [
        "https://feed.infoq.com/",
        "https://github.blog/feed/",
    ],
}

# ─────────────────────────────────────────────────────────────
# Haber Kaynakları — X (Twitter) Hesapları
# ─────────────────────────────────────────────────────────────
X_ACCOUNTS: Dict[str, List[str]] = {
    "Startup": [
        "Swipeline_tr",
        "webrazzi",
        "egirisim",
        "TechCrunch",
        "Entrepreneur",
    ],
    "Teknoloji": [
        "donanimhaber",
        "shiftdeletenet",
        "teknoblog",
        "verge",
        "WIRED",
    ],
    "AI": [
        "turkiyeai",
        "yapayzekakafasi",
        "YapayZekaAI_",
        "AI_TechNews",
        "VentureBeat",
    ],
    "Yazilim": [
        "oncekiyazilimci",
        "teknoblog",
        "3rdemayaz",
        "github",
        "fireship_dev",
    ],
}

# ─────────────────────────────────────────────────────────────
# Türkçe Kaynak Domain'leri (çeviri atlanacaklar)
# ─────────────────────────────────────────────────────────────
TURKISH_DOMAINS: List[str] = [
    "donanimhaber.com",
    "shiftdelete.net",
    "technopat.net",
    "chip.com.tr",
    "egirisim.com",
    "swipeline.co",
    "foundern.com",
]


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def _environment_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    database_url: str
    gemini_api_key: str
    admin_password: str
    session_secret: str
    gemini_model: str
    gemini_min_score: float
    gemini_min_interval_seconds: float
    candidate_limit_per_category: int
    cookie_secure: bool
    data_dir: Path
    max_news_age_hours: int = 48

    @classmethod
    def from_env(cls) -> "Settings":
        interval = float(os.getenv("GEMINI_MIN_INTERVAL_SECONDS", "15"))
        if interval < 15:
            raise ValueError("GEMINI_MIN_INTERVAL_SECONDS must be at least 15")

        candidate_limit = int(os.getenv("CANDIDATE_LIMIT_PER_CATEGORY", "3"))
        if candidate_limit < 1:
            raise ValueError("CANDIDATE_LIMIT_PER_CATEGORY must be at least 1")

        return cls(
            database_url=_required_environment("DATABASE_URL"),
            gemini_api_key=_required_environment("GEMINI_API_KEY"),
            admin_password=_required_environment("ADMIN_PASSWORD"),
            session_secret=_required_environment("SESSION_SECRET"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
            gemini_min_score=float(os.getenv("GEMINI_MIN_SCORE", "8.0")),
            gemini_min_interval_seconds=interval,
            candidate_limit_per_category=candidate_limit,
            cookie_secure=_environment_bool("COOKIE_SECURE"),
            data_dir=Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))),
            max_news_age_hours=int(os.getenv("MAX_NEWS_AGE_HOURS", "48")),
        )


def get_settings() -> Settings:
    return Settings.from_env()
