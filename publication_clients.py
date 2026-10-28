"""HTTP adapters. Credentials and remote response bodies never enter error messages."""
import hashlib
import io
import json
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image


class PublishFailure(RuntimeError):
    def __init__(self, message, *, uncertain=False, permanent=False):
        super().__init__(message)
        self.uncertain = uncertain
        self.permanent = permanent


def public_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise PublishFailure('Geçersiz herkese açık HTTPS adresi', permanent=True)
    return value


def jpeg_image(path):
    with Image.open(path) as image:
        image = image.convert('RGB')
        image.thumbnail((1600, 1600))
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=90)
        return buffer.getvalue()


class BlogClient:
    def __init__(self, api_url, token, site_url, *, transport=None):
        self.api_url = api_url.rstrip('/')
        self.site_url = site_url.rstrip('/')
        self.http = httpx.AsyncClient(timeout=90, transport=transport)
        self.token = token

    async def publish(self, payload):
        key = payload['key']
        headers = {'Authorization': f'Bearer {self.token}'}
        try:
            # Recover a committed blog after a lost response, even if the image file is gone.
            response = await self.http.get(f'{self.api_url}/integrations/news/{key}', headers=headers)
            if response.status_code == 404:
                image = jpeg_image(payload['image_path'])
                response = await self.http.put(
                    f'{self.api_url}/integrations/news/{key}', headers=headers,
                    data={'payload': json.dumps(payload['blog'], ensure_ascii=False)},
                    files={'image': ('news.jpg', image, 'image/jpeg')},
                )
            if response.status_code not in (200, 201):
                raise PublishFailure(f'Blog API HTTP {response.status_code}',
                                     permanent=response.status_code in (400, 401, 403, 409, 413))
            data = response.json()
            if not data.get('isPublished') or not data.get('id') or not data.get('slug'):
                raise PublishFailure('Blog yanıtı yayınlanmış bir yazı içermiyor', permanent=True)
            url = public_url(data['url'])
            if not url.startswith(self.site_url + '/blog/'):
                raise PublishFailure('Blog adresi yapılandırılmış siteyle eşleşmiyor', permanent=True)
            return {'id': data['id'], 'url': url, 'image_url': public_url(data['imageUrl'])}
        except (httpx.HTTPError, ValueError, KeyError):
            raise PublishFailure('Blog bağlantısı veya yanıtı doğrulanamadı') from None
        except (OSError, Image.DecompressionBombError):
            raise PublishFailure('Haber görseli okunamadı', permanent=True) from None

    async def verify(self, blog):
        # Social crawlers must see a real page and its Open Graph tags before posting.
        try:
            response = await self.http.get(blog['url'], follow_redirects=True)
            if (response.status_code != 200 or response.url.path != urlsplit(blog['url']).path or
                    'og:title' not in response.text or 'og:image' not in response.text):
                raise PublishFailure('Blog sayfası/önizlemesi henüz hazır değil')
            image = await self.http.get(blog['image_url'], headers={'Range': 'bytes=0-31'}, follow_redirects=True)
            if image.status_code not in (200, 206) or not image.headers.get('content-type', '').startswith('image/'):
                raise PublishFailure('Blog görseli dışarıdan erişilebilir değil')
        except httpx.HTTPError:
            raise PublishFailure('Blog veya görsel erişimi doğrulanamadı') from None

    async def close(self):
        await self.http.aclose()


class ThreadsClient:
    BASE = 'https://graph.threads.net/v1.0'

    def __init__(self, token, user_id, store, *, transport=None):
        self.seed = token
        self.seed_hash = hashlib.sha256(token.encode()).hexdigest()
        self.user_id = user_id
        self.store = store
        self.http = httpx.AsyncClient(timeout=60, transport=transport)

    async def token(self):
        saved = await self.store.credential('threads', self.seed_hash)
        if saved is None:
            # Coolify must supply a long-lived token, not the one-hour OAuth token.
            saved = {'token': self.seed, 'refresh_at': time.time() + 86400}
            await self.store.save_credential('threads', self.seed_hash, saved)
        if time.time() >= saved['refresh_at']:
            data = await self.request('GET', '/refresh_access_token', token=saved['token'],
                                      params={'grant_type': 'th_refresh_token'}, unversioned=True)
            if not data.get('access_token') or not data.get('expires_in'):
                raise PublishFailure('Threads token yenileme yanıtı geçersiz', permanent=True)
            saved = {'token': data['access_token'], 'refresh_at': time.time() + min(7*86400, int(data['expires_in'])/2)}
            await self.store.save_credential('threads', self.seed_hash, saved)
        return saved['token']

    async def request(self, method, path, *, token=None, params=None, data=None, publishing=False, unversioned=False):
        token = token or await self.token()
        base = 'https://graph.threads.net' if unversioned else self.BASE
        try:
            response = await self.http.request(method, base + path, params=params, data=data,
                                               headers={'Authorization': f'Bearer {token}'})
        except httpx.HTTPError:
            raise PublishFailure('Threads bağlantı hatası', uncertain=publishing) from None
        if not response.is_success:
            raise PublishFailure(f'Threads API HTTP {response.status_code}',
                                 uncertain=publishing and response.status_code >= 500,
                                 permanent=response.status_code in (400, 401, 403))
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise PublishFailure('Threads yanıtı geçersiz', uncertain=publishing) from None

    async def create(self, text, image_url):
        data = await self.request('POST', f'/{self.user_id}/threads', data={
            'media_type': 'IMAGE', 'image_url': image_url, 'text': text,
        })
        if not data.get('id'):
            raise PublishFailure('Threads görsel kabı kimliği yok')
        return str(data['id'])

    async def status(self, container):
        data = await self.request('GET', f'/{container}', params={'fields': 'status,error_message'})
        return data.get('status')

    async def publish(self, container):
        data = await self.request('POST', f'/{self.user_id}/threads_publish',
                                  data={'creation_id': container}, publishing=True)
        if not data.get('id'):
            raise PublishFailure('Threads gönderi kimliği yok', uncertain=True)
        return str(data['id'])

    async def close(self):
        await self.http.aclose()
