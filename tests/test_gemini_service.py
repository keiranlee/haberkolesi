from datetime import datetime, timezone

import pytest

from domain import Category, NewsRecord, RawNews
from gemini_service import (
    ContentType,
    EditorialBatchResult,
    GeminiService,
    InvalidGeminiResponse,
    ScoreResult,
    UnsafeDraftError,
)


class ImmediateGate:
    def __init__(self):
        self.calls = 0

    async def acquire(self):
        self.calls += 1
        return float(self.calls)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def generate_json(self, *, model, prompt, response_schema):
        self.requests.append(
            {"model": model, "prompt": prompt, "response_schema": response_schema}
        )
        return self.responses.pop(0)


@pytest.fixture
def news():
    return RawNews(
        url="https://source.test/new-ai-product",
        title="Company launches an AI product",
        summary="The company introduced the product today.",
        content="The company introduced the product today for software teams.",
        source="Source",
        source_category=Category.AI,
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
    )


def make_service(transport, gate=None, max_draft_chars=240):
    return GeminiService(
        transport=transport,
        gate=gate or ImmediateGate(),
        model="gemini-3.7-flash",
        max_draft_chars=max_draft_chars,
    )


def make_record(news_id, *, title, published_minute):
    raw = RawNews(
        url=f"https://source.test/news-{news_id}",
        title=title,
        summary=f"{title} hakkında doğrulanmış özet.",
        content=f"{title} hakkında yazılım ekiplerini etkileyen doğrulanmış ayrıntılar.",
        source="Source",
        source_category=Category.AI,
        published_at=datetime(2026, 8, 24, 12, published_minute, tzinfo=timezone.utc),
    )
    return NewsRecord(
        id=news_id,
        batch_id=1,
        raw=raw,
        normalized_url=raw.url,
    )


VALID_BATCH_TEXT = (
    "Yapay zeka aracı, yazılım ekiplerinin günlük iş akışını daha verimli "
    "yönetmesini sağlıyor. Yeni çözüm, tekrar eden görevleri azaltarak ekiplerin "
    "ürün geliştirmeye odaklanmasına yardımcı oluyor. #AI #Yazılım"
)


def batch_payload(selected_news_id=2, text=VALID_BATCH_TEXT):
    return {
        "evaluations": [
            {
                "news_id": 1,
                "score": 8.2,
                "category": "AI",
                "reason": "Somut ancak etkisi sınırlı.",
                "key_facts": ["İlk ürün yazılım ekiplerine sunuldu."],
                "risk_flags": [],
                "is_publishable": True,
                "topic_relevant": True,
                "content_type": "news",
            },
            {
                "news_id": 2,
                "score": 9.1,
                "category": "AI",
                "reason": "Güncel ve güçlü ürün haberi.",
                "key_facts": ["Yeni araç yazılım ekiplerine sunuldu."],
                "risk_flags": [],
                "is_publishable": True,
                "topic_relevant": True,
                "content_type": "news",
            },
            {
                "news_id": 3,
                "score": 9.8,
                "category": "AI",
                "reason": "Doğrulanmamış iddia içeriyor.",
                "key_facts": ["Üçüncü ürün hakkında bir iddia yayımlandı."],
                "risk_flags": [],
                "is_publishable": True,
                "topic_relevant": False,
                "content_type": "opinion",
            },
        ],
        "selected_news_id": selected_news_id,
        "text": text,
        "threads_text": "Yapay zeka aracı yazılım ekiplerine sunuldu. Yazıya göre bu gelişme ekiplerin iş akışını değiştirebilir.",
        "instagram_text": "Yazılım ekiplerine yeni yapay zeka aracı.\n\nYazıya göre yeni araç, ekiplerin günlük iş akışında kullanılabilecek bir çözüm olarak sunuluyor.",
        "image_title": "Yazılım ekiplerine yeni AI aracı",
        "image_fact": "Yeni araç yazılım ekiplerine sunuldu.",
        "used_facts": ["Yeni araç yazılım ekiplerine sunuldu."],
        "primary_keyword": "yapay zeka aracı",
        "secondary_keywords": ["yazılım ekipleri", "iş akışı"],
    }


def test_api_schema_avoids_unsupported_additional_properties_keyword():
    assert "additionalProperties" not in ScoreResult.model_json_schema()


@pytest.mark.asyncio
async def test_score_news_returns_validated_structured_result(news):
    transport = FakeTransport(
        {
            "score": 8.7,
            "category": "AI",
            "reason": "Yeni ve somut ürün haberi.",
            "key_facts": ["Ürün bugün yazılım ekipleri için duyuruldu."],
            "risk_flags": [],
            "is_publishable": True,
        }
    )

    result = await make_service(transport).score_news(news)

    assert result.score == 8.7
    assert result.category is Category.AI
    assert transport.requests[0]["model"] == "gemini-3.7-flash"


@pytest.mark.asyncio
async def test_score_news_rejects_invalid_category(news):
    transport = FakeTransport(
        {
            "score": 8.0,
            "category": "Spor",
            "reason": "Yanlış kategori.",
            "key_facts": ["Bir bilgi."],
            "risk_flags": [],
            "is_publishable": True,
        }
    )

    with pytest.raises(InvalidGeminiResponse):
        await make_service(transport).score_news(news)


@pytest.mark.asyncio
async def test_generate_draft_rejects_unapproved_facts(news):
    score = ScoreResult(
        score=9.0,
        category=Category.AI,
        reason="Güncel.",
        key_facts=["Ürün bugün duyuruldu."],
        risk_flags=[],
        is_publishable=True,
    )
    transport = FakeTransport(
        {
            "text": "Şirket 10 milyon dolar yatırım aldı. #AI",
            "used_facts": ["10 milyon dolar yatırım aldı."],
        }
    )

    with pytest.raises(UnsafeDraftError, match="unapproved fact"):
        await make_service(transport).generate_draft(news, score)


@pytest.mark.asyncio
async def test_generate_draft_enforces_length_and_hashtag_limits(news):
    score = ScoreResult(
        score=9.0,
        category=Category.AI,
        reason="Güncel.",
        key_facts=["Ürün bugün duyuruldu."],
        risk_flags=[],
        is_publishable=True,
    )
    too_long = FakeTransport(
        {"text": "x" * 41, "used_facts": ["Ürün bugün duyuruldu."]}
    )
    too_many_tags = FakeTransport(
        {
            "text": "Yeni ürün duyuruldu. #AI #Teknoloji #Yazılım",
            "used_facts": ["Ürün bugün duyuruldu."],
        }
    )

    with pytest.raises(UnsafeDraftError, match="40 characters"):
        await make_service(too_long, max_draft_chars=40).generate_draft(news, score)
    with pytest.raises(UnsafeDraftError, match="two hashtags"):
        await make_service(too_many_tags).generate_draft(news, score)


@pytest.mark.asyncio
async def test_each_gemini_call_passes_through_request_gate(news):
    gate = ImmediateGate()
    transport = FakeTransport(
        {
            "score": 8.7,
            "category": "AI",
            "reason": "Güncel.",
            "key_facts": ["Ürün bugün duyuruldu."],
            "risk_flags": [],
            "is_publishable": True,
        }
    )

    await make_service(transport, gate=gate).score_news(news)

    assert gate.calls == 1


@pytest.mark.asyncio
async def test_evaluate_candidates_uses_one_request_and_selects_highest_safe_record():
    records = [
        make_record(1, title="İlk yapay zeka ürünü duyuruldu", published_minute=1),
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2),
        make_record(3, title="Doğrulanmamış model iddiası", published_minute=3),
    ]
    transport = FakeTransport(batch_payload())

    result = await make_service(transport).evaluate_candidates(records)

    assert isinstance(result, EditorialBatchResult)
    assert len(transport.requests) == 1
    assert len(result.evaluations) == 3
    assert result.threads_text != result.text
    assert result.instagram_text != result.threads_text
    assert result.selected_news_id == 2
    assert result.evaluations[0].content_type is ContentType.NEWS
    assert result.primary_keyword == "yapay zeka aracı"
    assert transport.requests[0]["response_schema"] is EditorialBatchResult


@pytest.mark.asyncio
async def test_evaluate_candidates_replaces_paraphrased_image_fact_locally():
    records = [
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)
    ]
    payload = batch_payload(selected_news_id=2)
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["image_fact"] = "Yazılım ekipleri için yeni bir araç yayınlandı."

    result = await make_service(FakeTransport(payload)).evaluate_candidates(records)

    assert result.image_fact == result.used_facts[0]


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_a_winner_that_is_not_highest_safe_record():
    records = [
        make_record(1, title="İlk yapay zeka ürünü duyuruldu", published_minute=1),
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2),
        make_record(3, title="Doğrulanmamış model iddiası", published_minute=3),
    ]
    transport = FakeTransport(batch_payload(selected_news_id=1))

    with pytest.raises(InvalidGeminiResponse, match="highest safe"):
        await make_service(transport).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_accepts_either_candidate_tied_for_highest_score():
    records = [
        make_record(1, title="İlk yapay zeka ürünü duyuruldu", published_minute=1),
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2),
        make_record(3, title="Doğrulanmamış model iddiası", published_minute=3),
    ]
    payload = batch_payload(selected_news_id=2)
    payload["evaluations"][0]["score"] = 9.1
    transport = FakeTransport(payload)

    result = await make_service(transport).evaluate_candidates(records)

    assert result.selected_news_id == 2


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_copy_that_is_too_similar_to_title():
    records = [
        make_record(1, title="İlk yapay zeka ürünü duyuruldu", published_minute=1),
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2),
        make_record(3, title="Doğrulanmamış model iddiası", published_minute=3),
    ]
    transport = FakeTransport(
        batch_payload(text="Yazılım ekipleri için yeni araç çıktı.")
    )

    with pytest.raises(UnsafeDraftError, match="too similar"):
        await make_service(transport).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_caption_shorter_than_180_characters():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    payload = batch_payload(selected_news_id=2, text="Yapay zeka aracı yazılım ekiplerine sunuldu. #AI")
    payload["evaluations"] = [payload["evaluations"][1]]
    transport = FakeTransport(payload)

    with pytest.raises(UnsafeDraftError, match="at least 180"):
        await make_service(transport).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_requires_primary_and_secondary_keywords_in_body():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    missing_primary = batch_payload(selected_news_id=2)
    missing_primary["evaluations"] = [missing_primary["evaluations"][1]]
    missing_primary["primary_keyword"] = "kurumsal veri güvenliği"
    missing_secondary = batch_payload(selected_news_id=2)
    missing_secondary["evaluations"] = [missing_secondary["evaluations"][1]]
    missing_secondary["secondary_keywords"] = ["bulut maliyeti"]

    with pytest.raises(UnsafeDraftError, match="primary keyword"):
        await make_service(FakeTransport(missing_primary)).evaluate_candidates(records)
    with pytest.raises(UnsafeDraftError, match="secondary keyword"):
        await make_service(FakeTransport(missing_secondary)).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_ascii_spellings_of_common_turkish_words():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    text = VALID_BATCH_TEXT.replace("aracı", "araci").replace("yazılım", "yazilim")
    payload = batch_payload(selected_news_id=2, text=text)
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["primary_keyword"] = "yapay zeka araci"

    with pytest.raises(UnsafeDraftError, match="Turkish characters"):
        await make_service(FakeTransport(payload)).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_ascii_turkish_hashtags():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    text = VALID_BATCH_TEXT.replace("#Yazılım", "#Girisim")
    payload = batch_payload(selected_news_id=2, text=text)
    payload["evaluations"] = [payload["evaluations"][1]]

    with pytest.raises(UnsafeDraftError, match="Turkish characters"):
        await make_service(FakeTransport(payload)).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_numbers_absent_from_source():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    payload = batch_payload(selected_news_id=2, text=VALID_BATCH_TEXT.replace("Yeni çözüm", "2027 hedefiyle yeni çözüm"))
    payload["evaluations"] = [payload["evaluations"][1]]

    with pytest.raises(UnsafeDraftError, match="number absent"):
        await make_service(FakeTransport(payload)).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_promotional_winner():
    records = [
        make_record(1, title="İlk yapay zeka ürünü duyuruldu", published_minute=1),
        make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2),
    ]
    payload = batch_payload(selected_news_id=2)
    payload["evaluations"] = payload["evaluations"][:2]
    payload["evaluations"][1]["content_type"] = "promotional"

    with pytest.raises(InvalidGeminiResponse, match="promotional"):
        await make_service(FakeTransport(payload)).evaluate_candidates(records)


@pytest.mark.asyncio
async def test_evaluate_candidates_accepts_standalone_opinion_copy_without_formulaic_attribution():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    payload = batch_payload(selected_news_id=2)
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["evaluations"][0]["content_type"] = "opinion"

    payload["threads_text"] = "Bu araç yazılım ekiplerine sunuldu. Ekipler yeni çözümü kendi ihtiyaçlarına göre değerlendirebilir."
    payload["instagram_text"] = "Yazılım ekiplerine yeni araç.\n\nBu çözüm ekiplerin günlük çalışmalarında değerlendirilebilir; etkisi kullanım biçimine bağlı olabilir."
    result = await make_service(FakeTransport(payload)).evaluate_candidates(records)
    assert result.text == payload["text"]


@pytest.mark.asyncio
async def test_b2b_opinion_caption_preserves_attribution_keywords_and_percentage():
    raw = RawNews(
        url="https://entrepreneur.test/digital-footprint",
        title="Your Search Engine Footprint Has Real Financial Value",
        summary="68% of B2B buyers prefer to research online before engaging with sales.",
        content=(
            "The contributor argues that digital reputation can affect conversion "
            "rates and customer acquisition costs. 68% of B2B buyers prefer to "
            "research online before engaging with a sales representative."
        ),
        source="Entrepreneur",
        source_category=Category.GIRISIM,
        published_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
    )
    record = NewsRecord(id=7, batch_id=1, raw=raw, normalized_url=raw.url)
    fact = "B2B alıcılarının %68’i satış ekibiyle görüşmeden önce çevrim içi araştırmayı tercih ediyor."
    payload = {
        "evaluations": [{
            "news_id": 7,
            "score": 8.1,
            "category": "Girisim",
            "reason": "Somut sektör verisi içeren görüş yazısı.",
            "key_facts": [fact],
            "risk_flags": [],
            "is_publishable": True,
            "topic_relevant": True,
            "content_type": "opinion",
        }],
        "selected_news_id": 7,
        "text": (
            "B2B satış süreci, ilk görüşmeden önce arama sonuçlarında başlıyor. "
            "Yazıda aktarılan veriye göre alıcıların %68’i çevrim içi araştırmayı "
            "tercih ediyor; dijital itibar müşteri edinme maliyetini etkileyebiliyor. "
            "#B2B #Dijitalİtibar"
        ),
        "image_title": "B2B satışta dijital itibar",
        "threads_text": "Yazıya göre dijital itibar, B2B satış sürecini etkileyebiliyor. Alıcılar görüşmeden önce araştırmayı tercih ediyor.",
        "instagram_text": "Dijital itibar neden önemli?\n\nYazıya göre müşterilerin satış görüşmesinden önce araştırmayı tercih etmesi, arama sonuçlarını markalar için önemli hale getiriyor.",
        "image_fact": fact,
        "used_facts": [fact],
        "primary_keyword": "B2B satış",
        "secondary_keywords": ["dijital itibar", "müşteri edinme maliyeti"],
    }

    result = await make_service(FakeTransport(payload)).evaluate_candidates([record])

    assert result.text.startswith("B2B satış süreci")


@pytest.mark.asyncio
async def test_batch_request_sends_complete_discoverability_editorial_brief():
    records = [make_record(2, title="Yazılım ekipleri için yeni araç çıktı", published_minute=2)]
    payload = batch_payload(selected_news_id=2)
    payload["evaluations"] = [payload["evaluations"][1]]

    class EditorialBriefTransport:
        async def generate_json(self, *, model, prompt, response_schema):
            del model
            required_instructions = (
                "content_type",
                "primary_keyword",
                "secondary_keywords",
                "180-240",
                "opinion",
                "promotional",
                "Türkçe karakter",
                "tek bir sosyal medya metni",
                "sayısal",
            )
            if response_schema is not EditorialBatchResult or not all(
                instruction in prompt for instruction in required_instructions
            ):
                return {}
            return payload

    result = await make_service(EditorialBriefTransport()).evaluate_candidates(records)

    assert result.primary_keyword == "yapay zeka aracı"


@pytest.mark.asyncio
async def test_regenerate_content_uses_compact_new_editorial_prompt_for_same_news():
    record = make_record(
        2,
        title="Yazılım ekipleri için yeni araç çıktı",
        published_minute=2,
    )
    fact = "Yeni araç yazılım ekiplerine sunuldu."
    record.key_facts = [fact]
    transport = FakeTransport(
        {
            "text": VALID_BATCH_TEXT,
            "threads_text": "Yazılım ekiplerine yeni araç sunuldu. Ekipler bu çözümü iş akışlarında değerlendirebilir.",
            "instagram_text": "Yazılım ekiplerine yeni araç.\n\nYeni çözüm yazılım ekiplerinin kullanımına sunuldu. İş akışlarına nasıl dahil edileceği ekiplerin ihtiyaçlarına bağlı.",
            "image_title": "Yazılım ekiplerine yeni AI aracı",
            "image_fact": fact,
            "used_facts": [fact],
            "primary_keyword": "yapay zeka aracı",
            "secondary_keywords": ["yazılım ekipleri", "iş akışı"],
            "content_type": "news",
        }
    )

    result = await make_service(transport).regenerate_content(record)

    assert result.text == VALID_BATCH_TEXT
    assert len(transport.requests) == 1
    assert transport.requests[0]["response_schema"].__name__ == "RegeneratedContentResult"
    assert "180-240" in transport.requests[0]["prompt"]
    assert "primary_keyword" in transport.requests[0]["prompt"]
    assert "opinion" in transport.requests[0]["prompt"]


@pytest.mark.asyncio
async def test_batch_rejects_invented_numbers_in_instagram_caption():
    record = make_record(2, title="Yeni geliştirici çözümü", published_minute=2)
    payload = batch_payload()
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["instagram_text"] = "Kaynakta bulunmayan 987654 müşteriye ulaşıldı."
    with pytest.raises(UnsafeDraftError, match="number absent"):
        await make_service(FakeTransport(payload)).evaluate_candidates([record])


@pytest.mark.asyncio
async def test_batch_rejects_copying_x_caption_to_other_platforms():
    record = make_record(2, title="Yeni geliştirici çözümü", published_minute=2)
    payload = batch_payload()
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["threads_text"] = payload["text"]
    with pytest.raises(UnsafeDraftError, match="distinct copy"):
        await make_service(FakeTransport(payload)).evaluate_candidates([record])


@pytest.mark.asyncio
async def test_batch_removes_observed_paragraph_scaffolding():
    record = make_record(2, title="Yeni geliştirici çözümü", published_minute=2)
    payload = batch_payload()
    payload["evaluations"] = [payload["evaluations"][1]]
    payload["threads_text"] = "Yeni araç ekiplerin kullanımına sunuldu.\n\nİkinci paragrafta ise yazıya göre ekipler aracı kullanabilir."
    result = await make_service(FakeTransport(payload)).evaluate_candidates([record])
    assert result.threads_text.endswith("\n\nYazıya göre ekipler aracı kullanabilir.")
