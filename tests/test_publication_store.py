"""Optional real PostgreSQL coverage using a dedicated temporary schema."""
import os
import uuid
import asyncio

import pytest

from publication_store import PublicationStore


@pytest.mark.asyncio
async def test_postgres_publication_idempotency_lock_and_persistent_pause():
    dsn = os.getenv('TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('TEST_DATABASE_URL not configured')
    import asyncpg
    schema = 'pub_test_' + uuid.uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE SCHEMA {schema}')
    pool = None
    try:
        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=4,
                                        server_settings={'search_path': schema})
        store=PublicationStore(pool)
        await store.initialize()
        await store.initialize()  # Additive initialization is restart safe.
        await asyncio.gather(store.enqueue(1, {'blog': 'original'}), store.enqueue(1, {'blog': 'original'}))
        assert len(await store.recent())==1
        await store.enqueue(1, {'blog': 'must not overwrite'})
        assert (await store.get(1))['payload']['blog']=='original'
        await store.set_enabled(False)
        assert await PublicationStore(pool).enabled() is False
        async with store.lock() as first:
            async with PublicationStore(pool).lock() as second:
                assert first is True and second is False
        async with store.lock() as unlocked:
            assert unlocked is True
        job=await store.get(1)
        job['progress']={'x':{'state':'sending'}}; job['state']='running'
        await store.save(job)
        assert (await PublicationStore(pool).due())[0]['progress']['x']['state']=='sending'
        await store.save_credential('threads','seed',{'token':'fake'})
        assert await store.credential('threads','seed')=={'token':'fake'}
        assert await store.credential('threads','different') is None
        await store.rebuild(1, {'blog':'overwritten'})
        assert (await store.get(1))['payload']['blog']=='original'
        await store.enqueue(2, {'automatic':True})
        await store.rebuild(2, {'blog':'corrected'})
        assert (await store.get(2))['payload']['blog']=='corrected'
    finally:
        if pool: await pool.close()
        await admin.execute(f'DROP SCHEMA {schema} CASCADE')
        await admin.close()
