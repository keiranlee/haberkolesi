"""
Haber Kölesi - Veritabanı Modülü
=================================
PostgreSQL bağlantı havuzu yönetimi ve CRUD işlemleri.
asyncpg ile asenkron connection pooling.

Not: İleride FastAPI REST API'ye dönüştürülmeye uygun,
modüler ve genişletilebilir şekilde tasarlanmıştır.
"""

import asyncpg
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

from config import DATABASE_URL, DB_MIN_POOL, DB_MAX_POOL

logger: logging.Logger = logging.getLogger("haberkolesi.database")

# ─────────────────────────────────────────────────────────────
# Bağlantı Havuzu (Connection Pool) — Singleton
# ─────────────────────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Veritabanı bağlantı havuzunu döndürür. Yoksa oluşturur (Singleton)."""
    global _pool
    if _pool is None:
        logger.info("PostgreSQL bağlantı havuzu oluşturuluyor...")
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=DB_MIN_POOL,
            max_size=DB_MAX_POOL,
            command_timeout=30,
        )
        logger.info(
            "Bağlantı havuzu oluşturuldu (min=%d, max=%d)",
            DB_MIN_POOL,
            DB_MAX_POOL,
        )
    return _pool


async def close_pool() -> None:
    """Bağlantı havuzunu kapatır. Uygulama kapatılırken çağrılmalıdır."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL bağlantı havuzu kapatıldı.")


# ─────────────────────────────────────────────────────────────
# Tablo Oluşturma (Migration)
# ─────────────────────────────────────────────────────────────
CREATE_TABLE_SQL: str = """
CREATE TABLE IF NOT EXISTS haber_havuzu (
    id                SERIAL PRIMARY KEY,
    kaynak_url        TEXT UNIQUE NOT NULL,
    orjinal_metin     TEXT NOT NULL,
    cevrilmis_metin   TEXT NOT NULL,
    sosyal_medya_metni TEXT,
    kategori          VARCHAR(20) NOT NULL CHECK (kategori IN ('Startup', 'Teknoloji', 'AI', 'Yazilim')),
    skor              REAL NOT NULL DEFAULT 0.0,
    eklendigi_tarih   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paylasildi_mi     BOOLEAN NOT NULL DEFAULT FALSE,
    paylasilma_tarihi TIMESTAMPTZ
);

-- Performans indeksleri
CREATE INDEX IF NOT EXISTS idx_haber_paylasilmadi
    ON haber_havuzu (paylasildi_mi, kategori, eklendigi_tarih DESC)
    WHERE paylasildi_mi = FALSE;

CREATE INDEX IF NOT EXISTS idx_haber_paylasilma_tarihi
    ON haber_havuzu (paylasilma_tarihi)
    WHERE paylasilma_tarihi IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_haber_kaynak_url
    ON haber_havuzu (kaynak_url);

CREATE TABLE IF NOT EXISTS collection_batches (
    id              BIGSERIAL PRIMARY KEY,
    state           TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed')),
    found_count     INTEGER NOT NULL DEFAULT 0,
    error_count     INTEGER NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS news_items (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        BIGINT NOT NULL REFERENCES collection_batches(id),
    source_url      TEXT NOT NULL,
    normalized_url  TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_category TEXT NOT NULL CHECK (source_category IN ('Girisim', 'AI', 'Teknoloji', 'Yazilim')),
    published_at    TIMESTAMPTZ,
    state           TEXT NOT NULL DEFAULT 'collected'
                    CHECK (state IN ('collected', 'scored', 'drafted', 'approved', 'rejected', 'failed')),
    score           DOUBLE PRECISION,
    ai_category     TEXT CHECK (ai_category IN ('Girisim', 'AI', 'Teknoloji', 'Yazilim')),
    score_reason    TEXT,
    key_facts       JSONB,
    risk_flags      JSONB,
    is_publishable  BOOLEAN,
    draft_text      TEXT,
    external_post_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generation_versions (
    id              BIGSERIAL PRIMARY KEY,
    news_id         BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    generated_text  TEXT NOT NULL,
    used_facts      JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_name      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_jobs (
    id              BIGSERIAL PRIMARY KEY,
    news_id         BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    job_type        TEXT NOT NULL CHECK (job_type IN ('score', 'generate')),
    state           TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'running', 'retry', 'completed', 'failed')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    worker_id       TEXT,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_jobs_one_active
    ON ai_jobs (news_id, job_type)
    WHERE state IN ('pending', 'running', 'retry');

CREATE INDEX IF NOT EXISTS idx_ai_jobs_claim
    ON ai_jobs (state, next_attempt_at, id)
    WHERE state IN ('pending', 'retry');

CREATE INDEX IF NOT EXISTS idx_news_items_ranking
    ON news_items (ai_category, score DESC)
    WHERE state = 'scored' AND is_publishable = TRUE;

CREATE TABLE IF NOT EXISTS editor_actions (
    id              BIGSERIAL PRIMARY KEY,
    news_id         BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'edit', 'regenerate')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def initialize_database() -> None:
    """Veritabanı tablolarını ve indekslerini oluşturur."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
    logger.info("Veritabanı tabloları ve indeksler hazır.")


# ─────────────────────────────────────────────────────────────
# CRUD İşlemleri
# ─────────────────────────────────────────────────────────────


async def url_exists(kaynak_url: str) -> bool:
    """Verilen URL'nin veritabanında zaten mevcut olup olmadığını kontrol eder."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM haber_havuzu WHERE kaynak_url = $1)",
            kaynak_url,
        )
    return bool(row)


async def insert_news(
    kaynak_url: str,
    orjinal_metin: str,
    cevrilmis_metin: str,
    sosyal_medya_metni: str,
    kategori: str,
    skor: float,
) -> Optional[int]:
    """
    Yeni bir haber kaydı ekler.
    Başarılıysa oluşturulan ID'yi döndürür, çakışma varsa None döner.
    """
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row_id: Optional[int] = await conn.fetchval(
                """
                INSERT INTO haber_havuzu
                    (kaynak_url, orjinal_metin, cevrilmis_metin,
                     sosyal_medya_metni, kategori, skor)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (kaynak_url) DO NOTHING
                RETURNING id
                """,
                kaynak_url,
                orjinal_metin,
                cevrilmis_metin,
                sosyal_medya_metni,
                kategori,
                skor,
            )
        if row_id:
            logger.info(
                "Haber kaydedildi ─ id=%d, kategori=%s, skor=%.1f, url=%s",
                row_id,
                kategori,
                skor,
                kaynak_url[:80],
            )
        return row_id
    except Exception as exc:
        logger.error("Haber ekleme hatası ─ url=%s: %s", kaynak_url[:80], exc)
        return None


async def get_daily_publish_stats(today: date) -> Dict[str, int]:
    """
    Bugün paylaşılan haberlerin kategori bazlı sayısını döndürür.
    Dönen dict: {'total': N, 'Startup': N, 'Teknoloji': N, 'AI': N, 'Yazilim': N}
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kategori, COUNT(*) as cnt
            FROM haber_havuzu
            WHERE paylasildi_mi = TRUE
              AND paylasilma_tarihi::date = $1
            GROUP BY kategori
            """,
            today,
        )

    stats: Dict[str, int] = {
        "total": 0,
        "Startup": 0,
        "Teknoloji": 0,
        "AI": 0,
        "Yazilim": 0,
    }
    for row in rows:
        stats[row["kategori"]] = row["cnt"]
        stats["total"] += row["cnt"]

    return stats


async def pick_next_news(force_category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Paylaşılmamış en yeni haberi seçer.
    force_category verilmişse, sadece o kategoriden seçer.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if force_category:
            row = await conn.fetchrow(
                """
                SELECT id, kaynak_url, sosyal_medya_metni, kategori, skor
                FROM haber_havuzu
                WHERE paylasildi_mi = FALSE AND kategori = $1
                ORDER BY eklendigi_tarih DESC
                LIMIT 1
                """,
                force_category,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT id, kaynak_url, sosyal_medya_metni, kategori, skor
                FROM haber_havuzu
                WHERE paylasildi_mi = FALSE
                ORDER BY eklendigi_tarih DESC
                LIMIT 1
                """
            )

    if row is None:
        return None

    return dict(row)


async def mark_as_published(news_id: int) -> None:
    """Haberi paylaşıldı olarak işaretler ve paylaşılma tarihini kaydeder."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE haber_havuzu
            SET paylasildi_mi = TRUE,
                paylasilma_tarihi = NOW()
            WHERE id = $1
            """,
            news_id,
        )
    logger.info("Haber paylaşıldı olarak işaretlendi ─ id=%d", news_id)


async def get_pool_stats() -> Dict[str, int]:
    """Haber havuzunun genel istatistiklerini döndürür (admin panel için)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM haber_havuzu")
        unpublished = await conn.fetchval(
            "SELECT COUNT(*) FROM haber_havuzu WHERE paylasildi_mi = FALSE"
        )
        published = await conn.fetchval(
            "SELECT COUNT(*) FROM haber_havuzu WHERE paylasildi_mi = TRUE"
        )

    return {
        "total": total or 0,
        "unpublished": unpublished or 0,
        "published": published or 0,
    }
