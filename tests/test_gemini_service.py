from datetime import datetime, timezone

import pytest

from domain import Category, RawNews
from gemini_service import GeminiService, InvalidGeminiResponse, ScoreResult, UnsafeDraftError


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
