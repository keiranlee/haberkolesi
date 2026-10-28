import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from domain import Category, RawNews
from gemini_service import ScoreResult
from repositories import MemoryRepository
from publication_clients import PublishFailure
from publication_service import PublicationService, social_text, x_weight


class Store:
    def __init__(self):
        self.jobs = {}
        self.on = True
        self.locked = False
        self.creds = {}
        self.ready = []
        self.slots = []

    async def enabled(self): return self.on
    async def set_enabled(self, enabled): self.on = enabled
    async def enqueue(self, news_id, payload):
        self.jobs.setdefault(news_id, {'news_id': news_id, 'payload': deepcopy(payload), 'progress': {},
                                      'state': 'pending', 'updated_at': datetime.now(timezone.utc)})
    async def get(self, news_id): return deepcopy(self.jobs.get(news_id))
    async def rebuild(self, news_id, payload):
        self.jobs.pop(news_id, None)
        await self.enqueue(news_id, payload)
    async def save(self, job, **kwargs): self.jobs[job['news_id']] = deepcopy(job)
    async def recent(self): return deepcopy(list(self.jobs.values()))
    async def due(self): return [deepcopy(j) for j in self.jobs.values() if j['state'] in ('pending', 'retry', 'running')]
    async def ready_news(self): return [{'selected_news_id': id} for id in self.ready if id not in self.jobs]
    async def register_slot(self, key): self.slots.append(key)
    async def credential(self, name, seed): return self.creds.get((name, seed))
    async def save_credential(self, name, seed, value): self.creds[(name, seed)] = deepcopy(value)
    @asynccontextmanager
    async def lock(self):
        acquired = not self.locked
        if acquired: self.locked = True
        try: yield acquired
        finally:
            if acquired: self.locked = False


class Blog:
    def __init__(self, events): self.events = events; self.failure = None
    async def publish(self, payload):
        self.events.append('blog')
        if self.failure: raise self.failure
        return {'id': 'blog1', 'url': 'https://devosuit.com/blog/example', 'image_url': 'https://cdn.devosuit.com/news.jpg'}
    async def verify(self, result): self.events.append('verify')


class X:
    def __init__(self, events): self.events = events; self.posts = []; self.failure = None
    async def post(self, text, image):
        self.events.append('x'); self.posts.append((text, image))
        if self.failure: raise self.failure
        return '123'


class Threads:
    def __init__(self, events): self.events=events; self.posts=[]; self.failure=None
    async def create(self, text, image):
        self.events.append('container'); self.posts.append((text, image)); return 'container1'
    async def status(self, container): return 'FINISHED'
    async def publish(self, container):
        self.events.append('threads')
        if self.failure: raise self.failure
        return '456'


async def setup(tmp_path):
    settings = SimpleNamespace(auto_publish=True, x_enabled=True, x_auto_publish=True,
                               threads_enabled=True, gemini_min_score=8, x_daily_limit=8, data_dir=tmp_path)
    repo = MemoryRepository()
    news = await repo.insert_news(1, RawNews('https://source.test/news', 'Haber', '', 'Facts', 'Source', Category.AI, datetime.now(timezone.utc)))
    await repo.save_score(news.id, ScoreResult(score=9, category=Category.AI, reason='Good', key_facts=['Fact'], risk_flags=[], is_publishable=True))
    texts = {'x': 'Kısa haber özeti ' * 20, 'threads': 'Threads özeti', 'instagram': 'Unused',
             'blog_title': 'Türkçe haber', 'blog_title_en': 'English news',
             'blog_text': '## Haber\n\nGerçek bilgiler.', 'blog_text_en': '## News\n\nFacts.'}
    # Existing draft API accepts old/full generation; publication shortens only the outbound summary.
    texts['x'] = texts['x'][:270]
    await repo.save_draft(news.id, texts['x'], ['Fact'], platform_texts=texts)
    image = tmp_path / 'image.png'; Image.new('RGB', (12, 12)).save(image)
    await repo.save_image(news.id, str(image))
    store=Store(); events=[]; blog=Blog(events); x=X(events); threads=Threads(events)
    service=PublicationService(settings, repo, store, blog, x, threads)
    return service, news.id, events


@pytest.mark.asyncio
async def test_automatic_blog_then_image_summaries_and_links_exactly_once(tmp_path):
    service, id, events=await setup(tmp_path)
    service.store.ready=[id]
    await service.tick(); await service.tick()
    assert events == ['blog', 'verify', 'x', 'container', 'threads']
    job=await service.store.get(id)
    assert job['state']=='complete'
    assert job['payload']['blog']['contentTr'].startswith('<h2>')
    for text, image in service.x_client.posts + service.threads.posts:
        assert text.endswith('\n\nhttps://devosuit.com/blog/example')
        assert image
    assert (await service.repository.get_news(id)).external_post_id=='123'


@pytest.mark.asyncio
async def test_blog_error_blocks_both_channels_and_recovers_without_duplicate(tmp_path):
    service, id, events=await setup(tmp_path)
    await service.enqueue(id, automatic=True)
    service.blog.failure=PublishFailure('temporary')
    await service.tick()
    assert events==['blog']
    service.blog.failure=None
    await service.tick()
    assert events==['blog','blog','verify','x','container','threads']


@pytest.mark.asyncio
async def test_threads_retry_never_repeats_blog_or_successful_x(tmp_path):
    service, id, events=await setup(tmp_path)
    await service.enqueue(id, automatic=True)
    service.threads.failure=PublishFailure('429')
    await service.tick()
    service.threads.failure=None
    await service.tick()
    assert events.count('blog')==events.count('x')==events.count('container')==1
    assert events.count('threads')==2


@pytest.mark.asyncio
async def test_ambiguous_x_timeout_and_restart_require_reconciliation(tmp_path):
    service, id, events=await setup(tmp_path)
    await service.enqueue(id, automatic=True)
    service.x_client.failure=TimeoutError('secret must not leak')
    await service.tick(); await service.tick()
    job=await service.store.get(id)
    assert job['progress']['x']['state']=='uncertain'
    assert events.count('x')==1 and events.count('threads')==1
    assert 'secret' not in str(job)
    with pytest.raises(ValueError, match='kontrol'):
        await service.retry(id,'x')
    await service.retry(id,'x',post_id='789')
    await service.tick()
    assert events.count('x')==1
    assert (await service.store.get(id))['state']=='complete'


@pytest.mark.asyncio
async def test_crash_after_sending_marker_does_not_resend(tmp_path):
    service,id,events=await setup(tmp_path)
    await service.enqueue(id,automatic=True)
    job=await service.store.get(id)
    job['progress']['x']={'state':'sending'}
    job['state']='running'; await service.store.save(job)
    await service.tick()
    assert 'x' not in events
    assert (await service.store.get(id))['progress']['x']['state']=='uncertain'


@pytest.mark.asyncio
async def test_both_switches_pause_automatic_but_explicit_manual_publish_works(tmp_path):
    service,id,events=await setup(tmp_path)
    await service.enqueue(id,automatic=True)
    service.store.on=False
    await service.tick(); assert events==[]
    service.store.on=True; service.settings.auto_publish=False
    await service.tick(); assert events==[]
    job=await service.store.get(id); job['payload']['automatic']=False; service.store.jobs[id]=job
    await service.tick(); assert 'threads' in events


@pytest.mark.asyncio
async def test_pause_between_stages_keeps_remaining_channels_pending(tmp_path):
    service,id,events=await setup(tmp_path)
    await service.enqueue(id,automatic=True)
    async def verify(result): service.store.on=False
    service.blog.verify=verify
    await service.tick()
    assert (await service.store.get(id))['state']=='retry'
    assert 'x' not in events
    service.store.on=True
    await service.tick()
    assert 'x' in events and events.count('blog')==1


@pytest.mark.asyncio
async def test_risky_scheduled_winner_never_publishes(tmp_path):
    service,id,events=await setup(tmp_path)
    service.repository._news[id].risk_flags=['Unverified']
    service.store.ready=[id]
    await service.tick()
    assert events==[]
    assert (await service.store.get(id))['state']=='attention'


@pytest.mark.asyncio
async def test_frozen_package_is_not_overwritten_by_enqueue(tmp_path):
    service,id,events=await setup(tmp_path)
    await service.enqueue(id,automatic=True)
    original=await service.store.get(id)
    service.repository._news[id].platform_texts['threads']='Changed'
    await service.enqueue(id,automatic=True)
    assert (await service.store.get(id))['payload']==original['payload']


def test_social_budget_accounts_for_links_unicode_and_removes_source_links():
    url='https://devosuit.com/blog/'+'a'*70
    for summary in ['Merhaba dünya '*100,'🤖你好 '*100, 'Başlık https://source.test/news ayrıntılar']:
        x=social_text(summary,url,'x')
        assert x_weight(x[:-len(url)])+23<=280
        assert len(social_text(summary,url,'threads'))<=500
        assert 'source.test' not in x
        assert x.endswith(url)


@pytest.mark.asyncio
async def test_failed_preflight_can_be_rebuilt_after_editor_approval(tmp_path):
    service,id,events=await setup(tmp_path)
    service.repository._news[id].risk_flags=['Review']
    service.store.ready=[id]
    await service.tick()
    await service.repository.approve(id)
    await service.enqueue(id)
    await service.tick()
    assert (await service.store.get(id))['state']=='complete'
    assert events.count('blog')==1


def test_panel_pause_retry_and_manual_publish_require_csrf(tmp_path):
    import re
    from fastapi.testclient import TestClient
    from app import create_app
    from collector import CollectionResult
    from pipeline import NewsPipeline
    service,id,events=asyncio.run(setup(tmp_path))
    class Collector:
        async def collect(self, category=None): return CollectionResult()
    settings=SimpleNamespace(admin_password='panel-test',session_secret='test-session-secret',cookie_secure=False)
    panel=create_app(settings,service.repository,NewsPipeline(service.repository,Collector()),publication_service=service)
    with TestClient(panel) as client:
        client.post('/login',data={'password':'panel-test'})
        html=client.get('/').text
        assert 'Otomatik yayın' in html and '20:00' in html
        token=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
        assert client.post('/settings/auto-publish',data={'enabled':'false'}).status_code==403
        assert client.post('/settings/auto-publish',data={'enabled':'false','csrf_token':token}).status_code==200
        assert service.store.on is False
        assert client.post(f'/news/{id}/publish').status_code==403
        assert client.post(f'/publications/{id}/retry',data={'channel':'x'}).status_code==403
        asyncio.run(service.repository.approve(id))
        response=client.post(f'/news/{id}/publish',data={'csrf_token':token})
        assert response.status_code==200
        assert events==[]  # HTTP handler queues; scheduler publishes later.
        assert asyncio.run(service.store.get(id))['payload']['automatic'] is False
        assert client.get('/').status_code==200


def test_scheduler_uses_serial_blog_first_flow_and_existing_six_slots(tmp_path):
    from main import create_scheduler
    class Runner:
        async def run_slot(self, slot, scheduled_for=None): pass
    service,_,_=asyncio.run(setup(tmp_path))
    scheduler=create_scheduler(Runner(),publication_service=service)
    jobs=scheduler.get_jobs()
    assert len(jobs)==7
    assert sum(job.id.startswith('content_') for job in jobs)==6
    assert not any(job.id.startswith('x_publish_') for job in jobs)
