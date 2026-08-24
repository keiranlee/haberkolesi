"""Structured Gemini scoring and Devosuit draft generation."""

import json
import re
from typing import Any, Dict, List, Protocol, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from domain import Category, RawNews
from rate_limiter import AsyncRequestGate


class InvalidGeminiResponse(ValueError):
    pass


class UnsafeDraftError(ValueError):
    pass


class ScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=10)
    category: Category
    reason: str = Field(min_length=1, max_length=500)
    key_facts: List[str] = Field(min_length=1, max_length=12)
    risk_flags: List[str] = Field(default_factory=list, max_length=12)
    is_publishable: bool


class DraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    used_facts: List[str] = Field(min_length=1, max_length=12)


class GeminiTransport(Protocol):
    async def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: Type[BaseModel],
    ) -> Dict[str, Any]:
        ...


class GoogleGenAITransport:
    def __init__(self, api_key: str):
        from google import genai

        self.client = genai.Client(api_key=api_key)

    async def generate_json(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: Type[BaseModel],
    ) -> Dict[str, Any]:
        from google.genai import types

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        if response.parsed is not None:
            parsed = response.parsed
            if isinstance(parsed, BaseModel):
                return parsed.model_dump(mode="json")
            if isinstance(parsed, dict):
                return parsed
        try:
            return json.loads(response.text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise InvalidGeminiResponse("Gemini did not return valid JSON") from exc


class GeminiService:
    def __init__(
        self,
        *,
        transport: GeminiTransport,
        gate: AsyncRequestGate,
        model: str,
        max_draft_chars: int = 240,
    ):
        self.transport = transport
        self.gate = gate
        self.model = model
        self.max_draft_chars = max_draft_chars

    async def score_news(self, news: RawNews) -> ScoreResult:
        prompt = self._score_prompt(news)
        await self.gate.acquire()
        payload = await self.transport.generate_json(
            model=self.model,
            prompt=prompt,
            response_schema=ScoreResult,
        )
        try:
            return ScoreResult.model_validate(payload)
        except ValidationError as exc:
            raise InvalidGeminiResponse("Gemini score response failed validation") from exc

    async def generate_draft(
        self,
        news: RawNews,
        score: ScoreResult,
    ) -> DraftResult:
        prompt = self._draft_prompt(news, score)
        await self.gate.acquire()
        payload = await self.transport.generate_json(
            model=self.model,
            prompt=prompt,
            response_schema=DraftResult,
        )
        try:
            result = DraftResult.model_validate(payload)
        except ValidationError as exc:
            raise InvalidGeminiResponse("Gemini draft response failed validation") from exc

        approved_facts = set(score.key_facts)
        if any(fact not in approved_facts for fact in result.used_facts):
            raise UnsafeDraftError("Draft contains an unapproved fact")
        if len(result.text) > self.max_draft_chars:
            raise UnsafeDraftError(
                f"Draft exceeds {self.max_draft_chars} characters"
            )
        if len(re.findall(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", result.text)) > 2:
            raise UnsafeDraftError("Draft contains more than two hashtags")
        return result

    @staticmethod
    def _score_prompt(news: RawNews) -> str:
        return f"""Sen Devosuit için çalışan deneyimli bir teknoloji editörüsün.
Yalnızca aşağıdaki kaynak metne dayan. Haber güncelliğini, somutluğunu,
Devosuit kitlesine ilgisini ve bilgi değerini 0-10 arasında puanla.
Kategoriyi sadece Girisim, AI, Teknoloji veya Yazilim seç.
Reklam, söylenti, doğrulanamayan iddia ve eski haber risklerini belirt.

Kaynak: {news.source}
Kaynak kategorisi: {news.source_category.value}
Başlık: {news.title}
Özet: {news.summary}
İçerik: {news.content[:12000]}
URL: {news.url}
"""

    def _draft_prompt(self, news: RawNews, score: ScoreResult) -> str:
        facts = "\n".join(f"- {fact}" for fact in score.key_facts)
        return f"""Devosuit'in profesyonel teknoloji markası tonunda Türkçe bir X
gönderisi yaz. Başlığı kopyalama. Tıklama tuzağı kullanma. En fazla iki ilgili
hashtag kullan. Kaynakta olmayan hiçbir bilgi ekleme. Metin en fazla
{self.max_draft_chars} karakter olsun; kaynak bağlantısı ayrıca eklenecek.
Kullandığın olguları used_facts alanında aşağıdaki ifadelerle birebir döndür.

Onaylı olgular:
{facts}

Başlık: {news.title}
Kaynak metin: {news.content[:12000]}
"""
