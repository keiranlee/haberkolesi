"""Durable publication queue; a DB advisory lock serializes all publisher replicas."""
import json
from contextlib import asynccontextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS publication_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1), enabled BOOLEAN NOT NULL DEFAULT TRUE
);
INSERT INTO publication_settings (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS publications (
    news_id BIGINT PRIMARY KEY,
    payload JSONB NOT NULL,
    progress JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'pending',
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS publications_due ON publications (next_attempt_at)
    WHERE state IN ('pending', 'retry', 'running');
CREATE TABLE IF NOT EXISTS publication_credentials (
    name TEXT PRIMARY KEY, seed_hash TEXT NOT NULL, value JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS publication_slots (
    slot_key TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def decode(row):
    if row is None:
        return None
    result = dict(row)
    for key in ('payload', 'progress'):
        if isinstance(result[key], str):
            result[key] = json.loads(result[key])
    return result


class PublicationStore:
    def __init__(self, pool):
        self.pool = pool

    async def initialize(self):
        async with self.pool.acquire() as conn:
            await conn.execute(SCHEMA)

    async def enabled(self):
        return await self.pool.fetchval('SELECT enabled FROM publication_settings WHERE id=1')

    async def set_enabled(self, enabled):
        await self.pool.execute('UPDATE publication_settings SET enabled=$1 WHERE id=1', enabled)

    async def register_slot(self, key):
        await self.pool.execute('INSERT INTO publication_slots(slot_key) VALUES($1) ON CONFLICT DO NOTHING', key)

    async def ready_news(self):
        return await self.pool.fetch("""
            SELECT c.selected_news_id FROM content_runs c JOIN publication_slots p USING(slot_key)
            WHERE c.state='ready' AND c.selected_news_id IS NOT NULL
            AND p.created_at > NOW()-interval '24 hours'
            AND NOT EXISTS(SELECT 1 FROM publications j WHERE j.news_id=c.selected_news_id)
        """)

    async def enqueue(self, news_id, payload):
        await self.pool.execute(
            'INSERT INTO publications(news_id,payload) VALUES($1,$2::jsonb) ON CONFLICT DO NOTHING',
            news_id, json.dumps(payload),
        )

    async def get(self, news_id):
        return decode(await self.pool.fetchrow('SELECT * FROM publications WHERE news_id=$1', news_id))

    async def rebuild(self, news_id, payload):
        # Only rejected preflight packages can be rebuilt. Published/frozen packages cannot.
        await self.pool.execute("""
            UPDATE publications SET payload=$2::jsonb, progress='{}'::jsonb, state='pending',
            next_attempt_at=NOW(), updated_at=NOW() WHERE news_id=$1 AND NOT (payload ? 'blog')
        """, news_id, json.dumps(payload))

    async def recent(self):
        return [decode(row) for row in await self.pool.fetch(
            'SELECT * FROM publications ORDER BY created_at DESC LIMIT 30')]

    async def due(self):
        return [decode(row) for row in await self.pool.fetch("""
            SELECT * FROM publications WHERE state IN ('pending','retry','running')
            AND next_attempt_at<=NOW() ORDER BY created_at LIMIT 20
        """)]

    async def save(self, job, *, delay=0):
        await self.pool.execute("""
            UPDATE publications SET progress=$2::jsonb, state=$3,
            next_attempt_at=NOW()+$4*interval '1 second', updated_at=NOW() WHERE news_id=$1
        """, job['news_id'], json.dumps(job['progress']), job['state'], float(delay))

    @asynccontextmanager
    async def lock(self):
        # Held by a dedicated connection across HTTP calls; released even on cancellation.
        async with self.pool.acquire() as conn:
            acquired = await conn.fetchval('SELECT pg_try_advisory_lock(184721, 1)')
            try:
                yield acquired
            finally:
                if acquired:
                    await conn.execute('SELECT pg_advisory_unlock(184721, 1)')

    async def credential(self, name, seed_hash):
        value = await self.pool.fetchval(
            'SELECT value FROM publication_credentials WHERE name=$1 AND seed_hash=$2', name, seed_hash)
        return json.loads(value) if isinstance(value, str) else value

    async def save_credential(self, name, seed_hash, value):
        await self.pool.execute("""
            INSERT INTO publication_credentials(name,seed_hash,value) VALUES($1,$2,$3::jsonb)
            ON CONFLICT(name) DO UPDATE SET seed_hash=EXCLUDED.seed_hash,value=EXCLUDED.value
        """, name, seed_hash, json.dumps(value))
