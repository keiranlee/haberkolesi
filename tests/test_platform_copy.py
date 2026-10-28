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


@pytest.mark.parametrize("platform,limit", [("x", 280), ("threads", 500), ("instagram", 1800)])
def test_platform_budget_and_missing_copy_are_rejected(platform, limit):
    copies = {"x": "X metni", "threads": "Threads metni", "instagram": "Instagram metni"}
    copies[platform] = "a" * (limit + 1)
    with pytest.raises(ValueError):
        validate_platform_texts(copies)
    copies[platform] = ""
    with pytest.raises(ValueError):
        validate_platform_texts(copies)


def test_blog_editor_save_and_download():
    client, repository, news_id = make_panel()
    copies = {"x": "X metni", "threads": "Threads metni", "instagram": "Instagram metni",
              "x_followups": "Devam gönderisi.", "threads_followups": "Threads devamı.",
              "blog_title": "Açıklayıcı başlık", "blog_description": "Arama açıklaması", "blog_text": "## Nasıl çalışır?\n\nAyrıntılı açıklama."}
    asyncio.run(repository.save_draft(news_id, copies["x"], ["Bilgi"], platform_texts=copies))
    with client:
        csrf = login(client)
        page = client.get(f"/news/{news_id}")
        assert 'name="blog_text"' in page.text
        download = client.get(f"/news/{news_id}/blog.md")
        assert download.status_code == 200
        assert "## Nasıl çalışır?" in download.text
        response = client.post(f"/news/{news_id}/approve", data={"csrf_token": csrf, "edited_text": copies["x"], "threads_text": copies["threads"], "instagram_text": copies["instagram"], "blog_title": "Yeni başlık", "blog_description": copies["blog_description"], "blog_text": "## Mekanizma\n\nDüzenlenen ayrıntı."})
        assert response.status_code == 200
    saved = asyncio.run(repository.get_news(news_id))
    assert saved.platform_texts["blog_title"] == "Yeni başlık"
    assert saved.platform_texts["x_followups"] == "Devam gönderisi."


def test_continuation_posts_must_fit_each_platform():
    copies = {"x": "İlk gönderi", "threads": "İlk Threads", "instagram": "Instagram", "x_followups": "a" * 281}
    with pytest.raises(ValueError, match="280"):
        validate_platform_texts(copies)
    copies["x_followups"] = "a" * 260 + "\n\n" + "b" * 260
    assert validate_platform_texts(copies)["x_followups"] == copies["x_followups"]


def test_english_blog_editor_download_and_language_isolation():
    client, repository, news_id = make_panel()
    copies = {"x": "X metni", "threads": "Threads metni", "instagram": "Instagram metni",
              "blog_title": "Türkçe başlık", "blog_description": "Türkçe açıklama", "blog_text": "## Ayrıntı\n\nTürkçe yazı.",
              "blog_title_en": "English headline", "blog_description_en": "English description", "blog_text_en": "## Details\n\nFull English article."}
    asyncio.run(repository.save_draft(news_id, copies["x"], [], platform_texts=copies))
    with client:
        csrf = login(client)
        assert 'name="blog_text_en"' in client.get(f"/news/{news_id}").text
        en = client.get(f"/news/{news_id}/blog.md?lang=en")
        assert en.status_code == 200
        assert "# English headline" in en.text and "Türkçe yazı" not in en.text
        assert "-en.md" in en.headers["content-disposition"]
        tr = client.get(f"/news/{news_id}/blog.md")
        assert "Türkçe yazı" in tr.text and "Full English article" not in tr.text
        assert client.get(f"/news/{news_id}/blog.md?lang=de").status_code == 400
        response = client.post(f"/news/{news_id}/approve", data={"csrf_token": csrf, "edited_text": copies["x"], "threads_text": copies["threads"], "instagram_text": copies["instagram"], "blog_title_en": "Updated English headline", "blog_description_en": copies["blog_description_en"], "blog_text_en": "## Details\n\nEdited English article."})
        assert response.status_code == 200
    pack = asyncio.run(repository.get_news(news_id)).platform_texts
    assert pack["blog_text"] == "## Ayrıntı\n\nTürkçe yazı."
    assert pack["blog_title_en"] == "Updated English headline"
    assert pack["blog_text_en"] == "## Details\n\nEdited English article."


def test_english_blog_requires_complete_title_description_and_body():
    copies = {"x": "X", "threads": "Threads", "instagram": "Instagram", "blog_text_en": "English body"}
    with pytest.raises(ValueError, match="birlikte"):
        validate_platform_texts(copies)
