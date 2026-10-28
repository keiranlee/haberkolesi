import json
import time

import httpx
import pytest
from PIL import Image

from publication_clients import BlogClient, ThreadsClient, PublishFailure
from test_publication_service import Store


@pytest.mark.asyncio
async def test_blog_upload_converts_image_and_recovery_reads_existing_post(tmp_path):
    image=tmp_path/'test.png'; Image.new('RGB',(16,16)).save(image)
    created=False; calls=[]
    def respond(request):
        nonlocal created
        calls.append(request.method)
        assert request.headers['Authorization']=='Bearer test-secret'
        if request.method=='GET' and not created:
            return httpx.Response(404)
        if request.method=='PUT':
            assert b'image/jpeg' in request.content
            assert b'\xff\xd8\xff' in request.content
            created=True
        return httpx.Response(200,json={'id':'1','slug':'news','isPublished':True,'url':'https://devosuit.com/blog/news','imageUrl':'https://cdn.devosuit.com/image.jpg'})
    client=BlogClient('http://backend:5000/api','test-secret','https://devosuit.com',transport=httpx.MockTransport(respond))
    payload={'key':'a'*64,'image_path':str(image),'blog':{'titleTr':'Haber'}}
    first=await client.publish(payload)
    image.unlink()
    assert await client.publish(payload)==first
    assert calls==['GET','PUT','GET']
    await client.close()


@pytest.mark.asyncio
async def test_blog_readiness_sends_no_service_secret_to_public_site():
    def respond(request):
        assert 'Authorization' not in request.headers
        if request.url.host=='devosuit.com':
            return httpx.Response(200,text='<meta property="og:title"><meta property="og:image">')
        return httpx.Response(206,headers={'Content-Type':'image/jpeg'},content=b'jpg')
    client=BlogClient('https://backend.test/api','secret','https://devosuit.com',transport=httpx.MockTransport(respond))
    await client.verify({'url':'https://devosuit.com/blog/news','image_url':'https://cdn.devosuit.com/image.jpg'})
    await client.close()


@pytest.mark.asyncio
async def test_threads_persists_refreshed_token_and_uses_image_container():
    store=Store(); requests=[]
    def respond(request):
        requests.append(request)
        if request.url.path=='/refresh_access_token':
            return httpx.Response(200,json={'access_token':'refreshed-secret','expires_in':5184000})
        assert request.headers['Authorization']=='Bearer refreshed-secret'
        if request.url.path.endswith('/threads'):
            assert b'media_type=IMAGE' in request.content
            assert b'image_url=' in request.content
            return httpx.Response(200,json={'id':'container'})
        if request.url.path.endswith('/threads_publish'):
            return httpx.Response(200,json={'id':'12345'})
        return httpx.Response(200,json={'status':'FINISHED'})
    transport=httpx.MockTransport(respond)
    client=ThreadsClient('seed-secret','999',store,transport=transport)
    await store.save_credential('threads',client.seed_hash,{'token':'old-secret','refresh_at':time.time()-1})
    container=await client.create('Summary https://devosuit.com/blog/news','https://cdn.test/image.jpg')
    assert await client.status(container)=='FINISHED'
    assert await client.publish(container)=='12345'
    restarted=ThreadsClient('seed-secret','999',store,transport=transport)
    assert await restarted.token()=='refreshed-secret'
    assert len([r for r in requests if r.url.path=='/refresh_access_token'])==1
    for request in requests:
        assert 'access_token' not in request.url.params
        assert 'secret' not in str(request.url)
    await client.close(); await restarted.close()


@pytest.mark.asyncio
async def test_threads_unknown_publish_result_is_not_safe_to_retry():
    def timeout(request): raise httpx.ReadTimeout('token=PRIVATE',request=request)
    client=ThreadsClient('secret','999',Store(),transport=httpx.MockTransport(timeout))
    with pytest.raises(PublishFailure) as caught:
        await client.publish('container')
    assert caught.value.uncertain
    assert 'PRIVATE' not in str(caught.value)
    await client.close()
