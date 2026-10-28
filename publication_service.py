"""Blog-first publication of scheduled winners. Tests never enter this queue."""
import asyncio
import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown

from domain import NewsState
from publication_clients import PublishFailure, jpeg_image
from x_publisher import XAuthError, XRateLimitedError

logger = logging.getLogger('haberkolesi.publications')
ISTANBUL = ZoneInfo('Europe/Istanbul')
LABELS = {'pending': 'Bekliyor', 'retry': 'Yeniden denenecek', 'running': 'Yayınlanıyor',
          'posted': 'Yayınlandı', 'complete': 'Tamamlandı', 'skipped': 'Kapalı',
          'failed': 'Hata', 'uncertain': 'Sonucu kontrol edin', 'attention': 'Kontrol gerekli',
          'sending': 'Gönderiliyor'}


def x_weight(text):
    # Conservative upper bound of twitter-text weights. ZWJ emoji can be shorter
    # than this estimate, never longer; no accidental split of a URL is possible.
    return sum(1 if (ord(c) <= 0x10FF or 0x2000 <= ord(c) <= 0x200D or
                         0x2010 <= ord(c) <= 0x201F or 0x2032 <= ord(c) <= 0x2037) else 2 for c in text)


def social_text(summary, url, platform):
    summary = re.sub(r'https?://\S+', '', summary)
    summary = unicodedata.normalize('NFC', ' '.join(summary.split()))
    if not summary:
        raise ValueError('Sosyal haber özeti boş')
    measure = x_weight if platform == 'x' else len
    budget = (280 - 23 - 2) if platform == 'x' else (500 - len(url) - 2)
    if budget < 25:
        raise ValueError('Blog bağlantısı gönderi için fazla uzun')
    if measure(summary) > budget:
        clipped = ''
        for char in summary:
            if measure(clipped + char + '…') > budget:
                break
            clipped += char
        if ' ' in clipped:
            clipped = clipped.rsplit(' ', 1)[0]
        summary = clipped.rstrip() + '…'
    return f'{summary}\n\n{url}'


class PublicationService:
    def __init__(self, settings, repository, store, blog, x_client=None, threads=None):
        self.settings, self.repository, self.store = settings, repository, store
        self.blog, self.x_client, self.threads = blog, x_client, threads

    def problems(self):
        problems = []
        if self.blog is None:
            problems.append('DEVOSUIT_API_URL, DEVOSUIT_PUBLISH_TOKEN ve DEVOSUIT_SITE_URL gerekli.')
        if self.settings.x_enabled and self.x_client is None:
            problems.append('X kimlik bilgileri eksik.')
        if self.settings.threads_enabled and self.threads is None:
            problems.append('THREADS_USER_ID ve uzun ömürlü THREADS_ACCESS_TOKEN gerekli.')
        return problems

    async def enabled(self):
        return self.settings.auto_publish and await self.store.enabled()

    async def status(self):
        return {'env_enabled': self.settings.auto_publish, 'panel_enabled': await self.store.enabled(),
                'enabled': await self.enabled(), 'problems': self.problems(),
                'x_enabled': self.settings.x_enabled and self.settings.x_auto_publish,
                'threads_enabled': self.settings.threads_enabled,
                'jobs': await self.store.recent(), 'labels': LABELS}

    async def run_slot(self, runner, slot):
        moment = datetime.now(timezone.utc)
        if await self.enabled():
            key = f'{moment.astimezone(ISTANBUL).date().isoformat()}T{slot.hour:02d}:{slot.category.value}'
            await self.store.register_slot(key)
        result = await runner.run_slot(slot, scheduled_for=moment)
        await self.tick()
        return result

    async def enqueue(self, news_id, *, automatic=False):
        existing = await self.store.get(news_id)
        if existing and (automatic or 'blog' in existing['payload']):
            return
        record = await self.repository.get_news(news_id)
        if record.state not in (NewsState.DRAFTED, NewsState.APPROVED):
            raise ValueError('Yalnız hazır/onaylı içerik yayınlanabilir')
        if automatic and (record.is_publishable is not True or record.risk_flags or
                          record.score is None or record.score < self.settings.gemini_min_score):
            raise ValueError('Otomatik yayın için puan veya risk kontrolü uygun değil')
        if not automatic and record.state != NewsState.APPROVED:
            raise ValueError('Önce içeriği onaylayın')
        texts = record.platform_texts or {}
        required = ('blog_title', 'blog_title_en', 'blog_text', 'blog_text_en', 'x', 'threads')
        if any(not texts.get(key, '').strip() for key in required) or not record.image_path:
            raise ValueError('İki dilde blog, X/Threads özeti ve görsel gerekli; içeriği yeniden üretin')
        key = hashlib.sha256(record.normalized_url.encode()).hexdigest()
        directory = self.settings.data_dir / 'publications'
        directory.mkdir(parents=True, exist_ok=True)
        image_path = directory / f'{key}.jpg'
        image_path.write_bytes(await asyncio.to_thread(jpeg_image, record.image_path))
        title = unicodedata.normalize('NFKD', texts['blog_title'].replace('ı', 'i')).encode('ascii', 'ignore').decode().lower()
        slug = re.sub(r'[^a-z0-9]+', '-', title).strip('-')[:65].strip('-') or 'haber'
        payload = {'key': key, 'automatic': automatic, 'image_path': str(image_path),
                   'x': texts['x'], 'threads': texts['threads'],
                   'channels': {'x': self.settings.x_enabled and (not automatic or self.settings.x_auto_publish),
                                'threads': self.settings.threads_enabled},
                   'existing_x': record.external_post_id or (record.x_thread_post_ids or [None])[0],
                   'blog': {'titleTr': texts['blog_title'], 'titleEn': texts['blog_title_en'],
                            'slug': f'{slug}-{key[:12]}',
                            'contentTr': markdown.markdown(texts['blog_text'], extensions=['extra']),
                            'contentEn': markdown.markdown(texts['blog_text_en'], extensions=['extra'])}}
        if automatic and record.state == NewsState.DRAFTED:
            await self.repository.approve(news_id)
        if existing:
            await self.store.rebuild(news_id, payload)
        else:
            await self.store.enqueue(news_id, payload)

    async def tick(self):
        async with self.store.lock() as acquired:
            if not acquired:
                return
            # Keep an authorized account usable even when no publishable news is found.
            if self.threads is not None and hasattr(self.threads, 'token'):
                try:
                    await self.threads.token()
                except PublishFailure:
                    logger.warning('Threads token yenilenemedi; bağlantı ayarlarını kontrol edin')
            if await self.enabled() and not self.problems():
                for row in await self.store.ready_news():
                    try:
                        await self.enqueue(row['selected_news_id'], automatic=True)
                    except (ValueError, OSError):
                        # Record an actionable failure instead of retrying a bad winner every minute.
                        await self.store.enqueue(row['selected_news_id'], {'automatic': True, 'channels': {}})
                        job = await self.store.get(row['selected_news_id'])
                        job['state'] = 'attention'
                        job['progress'] = {'blog': {'state': 'failed', 'error': 'İçerik, risk veya görsel kontrolü başarısız; haberi inceleyin.'}}
                        await self.store.save(job)
            for job in await self.store.due():
                if job['payload'].get('automatic') and not await self.enabled():
                    continue
                try:
                    await self.process(job)
                except Exception:
                    # A sending marker survives DB loss/cancellation. Never replay it blindly.
                    logger.error('Yayın işi #%s tamamlanamadı; kayıtlı aşamadan kurtarılacak', job['news_id'])

    async def process(self, job):
        payload, progress = job['payload'], job['progress']
        for channel in ('blog', 'x', 'threads'):
            progress.setdefault(channel, {'state': 'pending', 'attempts': 0})
        job['state'] = 'running'
        await self.store.save(job)
        for channel in ('blog', 'x', 'threads'):
            if payload.get('automatic') and not await self.enabled():
                break
            stage = progress.setdefault(channel, {'state': 'pending', 'attempts': 0})
            if channel != 'blog' and not payload['channels'].get(channel):
                stage['state'] = 'skipped'
            if stage['state'] == 'sending':
                stage.update(state='uncertain', error='Önceki gönderinin sonucu belirsiz; hesabı kontrol edin.')
            if stage['state'] in ('posted', 'skipped', 'failed', 'uncertain'):
                if channel == 'blog' and stage['state'] != 'posted':
                    break
                continue
            if channel != 'blog' and progress.get('blog', {}).get('state') != 'posted':
                break
            try:
                if channel == 'blog':
                    if self.blog is None:
                        raise PublishFailure('Blog entegrasyonu yapılandırılmadı', permanent=True)
                    if 'result' not in stage:
                        stage['result'] = await self.blog.publish(payload)
                        await self.store.save(job)
                    await self.blog.verify(stage['result'])
                    stage.update(state='posted', error=None)
                else:
                    await self.publish_social(channel, stage, job)
            except PublishFailure as exc:
                stage['attempts'] = stage.get('attempts', 0) + 1
                stage['state'] = ('uncertain' if exc.uncertain else 'failed' if exc.permanent or stage['attempts'] >= 5 else 'retry')
                stage['error'] = str(exc)
            await self.store.save(job)
        states = [stage['state'] for stage in progress.values()]
        if progress.get('blog', {}).get('state') in ('failed', 'uncertain'):
            job['state'] = 'attention'
        elif any(state in ('pending', 'retry') for state in states):
            job['state'] = 'retry'
        elif any(state in ('failed', 'uncertain') for state in states):
            job['state'] = 'attention'
        else:
            job['state'] = 'complete'
        attempts = max((s.get('attempts', 0) for s in progress.values()), default=0)
        await self.store.save(job, delay=min(3600, 60 * 2**attempts) if job['state'] == 'retry' else 0)

    async def publish_social(self, channel, stage, job):
        payload = job['payload']
        blog = job['progress']['blog']['result']
        if channel == 'x' and payload.get('existing_x'):
            stage.update(state='posted', id=payload['existing_x'], error=None)
            return
        if ((channel == 'x' and not self.settings.x_enabled) or
                (channel == 'threads' and not self.settings.threads_enabled)):
            raise PublishFailure(f'{channel} Coolify ayarlarından kapalı', permanent=True)
        try:
            text = social_text(payload[channel], blog['url'], channel)
        except ValueError as exc:
            raise PublishFailure(str(exc), permanent=True) from None
        if channel == 'x':
            if self.x_client is None:
                raise PublishFailure('X bağlantısı yapılandırılmadı', permanent=True)
            if not Path(payload['image_path']).is_file():
                raise PublishFailure('X görseli bulunamadı; /app/data kalıcı diski kontrol edin', permanent=True)
            today = datetime.now(ISTANBUL).replace(hour=0, minute=0, second=0, microsecond=0)
            if await self.repository.count_x_published_since(today) >= self.settings.x_daily_limit:
                raise PublishFailure('Günlük X sınırına ulaşıldı')
            stage['state'] = 'sending'
            await self.store.save(job)
            try:
                post_id = await self.x_client.post(text, payload['image_path'])
            except XRateLimitedError:
                raise PublishFailure('X istek sınırı; daha sonra yeniden denenecek') from None
            except XAuthError:
                raise PublishFailure('X erişim bilgilerini kontrol edin', permanent=True) from None
            except Exception:
                raise PublishFailure('X yanıtı alınamadı; hesabı kontrol edin', uncertain=True) from None
            stage.update(state='posted', id=str(post_id), error=None)
            await self.store.save(job)
            await self.repository.mark_x_published(job['news_id'], str(post_id))
        else:
            if self.threads is None:
                raise PublishFailure('Threads bağlantısı yapılandırılmadı', permanent=True)
            if not stage.get('container_id'):
                stage['container_id'] = await self.threads.create(text, blog['image_url'])
                await self.store.save(job)
            status = await self.threads.status(stage['container_id'])
            if status == 'PUBLISHED':
                raise PublishFailure('Threads kabı yayınlanmış; gönderi kimliğini doğrulayın', uncertain=True)
            if status in ('ERROR', 'EXPIRED'):
                stage.pop('container_id', None)
                raise PublishFailure('Threads görsel kabı işlenemedi/süresi doldu')
            if status != 'FINISHED':
                raise PublishFailure('Threads görseli henüz işleniyor')
            stage['state'] = 'sending'
            await self.store.save(job)
            post_id = await self.threads.publish(stage['container_id'])
            stage.update(state='posted', id=post_id, error=None)

    async def retry(self, news_id, channel, *, post_id='', confirmed_not_posted=False):
        if channel not in ('blog', 'x', 'threads'):
            raise ValueError('Geçersiz kanal')
        async with self.store.lock() as acquired:
            if not acquired:
                raise ValueError('Yayın sürüyor; biraz sonra tekrar deneyin')
            job = await self.store.get(news_id)
            if not job or 'blog' not in job['payload']:
                raise ValueError('Geçerli yayın paketi yok; içeriği yeniden hazırlayın')
            stage = job['progress'].get(channel, {})
            if stage.get('state') not in ('failed', 'uncertain', 'retry'):
                raise ValueError('Bu aşama tekrar başlatılamaz')
            if stage.get('state') == 'uncertain':
                if post_id:
                    if not post_id.isdigit() or len(post_id) > 30:
                        raise ValueError('Sayısal gönderi kimliği gerekli')
                    stage.update(state='posted', id=post_id, error=None)
                    if channel == 'x':
                        await self.repository.mark_x_published(news_id, post_id)
                elif confirmed_not_posted:
                    stage.update(state='pending', attempts=0, error=None)
                    stage.pop('container_id', None)
                else:
                    raise ValueError('Önce hesabı kontrol edin: gönderi kimliği girin veya yayınlanmadığını doğrulayın')
            else:
                stage.update(state='pending', attempts=0, error=None)
            job['state'] = 'pending'
            await self.store.save(job)
