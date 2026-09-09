import asyncio

import pytest

from platform_copy import validate_platform_texts
from tests.test_app import make_panel, login


def test_platform_editor_saves_all_captions_and_displays_them_after_approval():
    client, repository, news_id = make_panel()
    copies = {"x": "Kısa X metni", "threads": "Threads için sohbet metni", "instagram": "Instagram ilk satır\n\nAçıklama paragrafı"}
    asyncio.run(repository.save_draft(news_id, copies["x"], ["Bilgi"], platform_texts=copies))
    with client:
        csrf = login(client)
        page = client.get(f"/news/{news_id}")
        assert 'name="threads_text"' in page.text
        assert 'name="instagram_text"' in page.text
        response = client.post(f"/news/{news_id}/approve", data={
            "csrf_token": csrf, "edited_text": "Düzenlenen X",
            "threads_text": "Düzenlenen Threads", "instagram_text": "Düzenlenen Instagram",
        })
        assert response.status_code == 200
        assert "Düzenlenen Instagram" in response.text
    record = asyncio.run(repository.get_news(news_id))
    assert record.platform_texts == {"x": "Düzenlenen X", "threads": "Düzenlenen Threads", "instagram": "Düzenlenen Instagram"}
    assert record.draft_text == record.platform_texts["x"]


@pytest.mark.parametrize("platform,limit", [("x", 240), ("threads", 480), ("instagram", 1800)])
def test_platform_budget_and_missing_copy_are_rejected(platform, limit):
    copies = {"x": "X metni", "threads": "Threads metni", "instagram": "Instagram metni"}
    copies[platform] = "a" * (limit + 1)
    with pytest.raises(ValueError):
        validate_platform_texts(copies)
    copies[platform] = ""
    with pytest.raises(ValueError):
        validate_platform_texts(copies)
