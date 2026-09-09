"""Structured Gemini scoring and Devosuit draft generation."""

import json
import re
import unicodedata
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Type

from pydantic import BaseModel, Field, ValidationError

from domain import Category, NewsRecord, RawNews
from rate_limiter import AsyncRequestGate


class InvalidGeminiResponse(ValueError):
    pass


class UnsafeDraftError(ValueError):
    pass


class ScoreResult(BaseModel):
    score: float = Field(ge=0, le=10)
    category: Category
    reason: str = Field(min_length=1, max_length=500)
    key_facts: List[str] = Field(min_length=1, max_length=12)
    risk_flags: List[str] = Field(default_factory=list, max_length=12)
    is_publishable: bool


class DraftResult(BaseModel):
    text: str = Field(min_length=1)
    used_facts: List[str] = Field(min_length=1, max_length=12)


class ContentType(str, Enum):
    NEWS = "news"
    ANALYSIS = "analysis"
    OPINION = "opinion"
    GUIDE = "guide"
    PROMOTIONAL = "promotional"


class RegeneratedContentResult(BaseModel):
    text: str = Field(min_length=1)
    threads_text: str = Field(min_length=1, max_length=480)
    instagram_text: str = Field(min_length=1, max_length=1800)
    image_title: str = Field(min_length=1, max_length=120)
    image_fact: str = Field(min_length=1, max_length=500)
    used_facts: List[str] = Field(min_length=1, max_length=12)
    primary_keyword: str = Field(min_length=1, max_length=80)
    secondary_keywords: List[str] = Field(min_length=1, max_length=3)
    content_type: ContentType


class CandidateScore(BaseModel):
    news_id: int
    score: float = Field(ge=0, le=10)
    category: Category
    reason: str = Field(min_length=1, max_length=500)
    key_facts: List[str] = Field(min_length=1, max_length=12)
    risk_flags: List[str] = Field(default_factory=list, max_length=12)
    is_publishable: bool
    topic_relevant: bool
    content_type: ContentType


class EditorialBatchResult(BaseModel):
    evaluations: List[CandidateScore] = Field(min_length=1, max_length=3)
    selected_news_id: Optional[int] = None
    text: Optional[str] = None
    threads_text: Optional[str] = Field(default=None, max_length=480)
    instagram_text: Optional[str] = Field(default=None, max_length=1800)
    image_title: Optional[str] = None
    image_fact: Optional[str] = None
    used_facts: List[str] = Field(default_factory=list, max_length=12)
    primary_keyword: Optional[str] = Field(default=None, max_length=80)
    secondary_keywords: List[str] = Field(default_factory=list, max_length=3)


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

    async def close(self) -> None:
        await self.client.aio.aclose()


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

    async def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            await close()

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

    async def evaluate_candidates(
        self,
        candidates: List[NewsRecord],
    ) -> EditorialBatchResult:
        if not 1 <= len(candidates) <= 3:
            raise ValueError("Gemini batch must contain between one and three candidates")
        prompt = self._batch_prompt(candidates)
        await self.gate.acquire()
        payload = await self.transport.generate_json(
            model=self.model,
            prompt=prompt,
            response_schema=EditorialBatchResult,
        )
        try:
            result = EditorialBatchResult.model_validate(payload)
        except ValidationError as exc:
            raise InvalidGeminiResponse(
                "Gemini editorial batch response failed validation"
            ) from exc
        self._validate_batch_result(candidates, result)
        return result

    async def regenerate_content(
        self,
        candidate: NewsRecord,
    ) -> RegeneratedContentResult:
        if not candidate.key_facts:
            raise ValueError("Regeneration requires approved key facts")

        max_attempts = 3
        last_error = None
        last_result_text = None
        base_prompt = self._regeneration_prompt(candidate)

        for attempt in range(max_attempts):
            await self.gate.acquire()
            prompt = base_prompt
            if attempt > 0 and last_error:
                feedback = f"Önceki denemede şu kural ihlali oluştu: '{last_error}'."
                if "180" in last_error:
                    curr_len = len(last_result_text or "")
                    feedback += f" Önceki metin yalnızca {curr_len} karakterdi (180'den az)! Lütfen cümleyi biraz daha genişleterek metni KESİNLİKLE 195-225 karakter aralığına çıkar."
                elif "240" in last_error:
                    curr_len = len(last_result_text or "")
                    feedback += f" Önceki metin {curr_len} karakterle 240 karakter sınırını aştı! Metni 195-220 karakter aralığına inecek şekilde kısalt."
                elif "Turkish" in last_error:
                    feedback += " Metinde veya etiketlerde (hashtag) ASCII yazım hatası yapıldı! 'ş, ç, ğ, ı, ö, ü' harflerini eksiksiz kullan (şirket, müşteri, yazılım, aracı, satış, girişim, yatırım, #Girişim, #Satış). Asla #Girisim, #Satis yazma."
                elif "keyword" in last_error:
                    feedback += " primary_keyword veya secondary_keywords metinde kelimesi kelimesine geçmedi! Metin içinden harfi harfine alıntıla."
                prompt += f"\n\nÖNEMLİ DÜZELTME UYARISI: {feedback}\n"

            payload = await self.transport.generate_json(
                model=self.model,
                prompt=prompt,
                response_schema=RegeneratedContentResult,
            )
            try:
                result = RegeneratedContentResult.model_validate(payload)
                last_result_text = result.text
            except ValidationError as exc:
                last_error = "Gemini regeneration response failed validation"
                if attempt == max_attempts - 1 or (hasattr(self.transport, "responses") and not getattr(self.transport, "responses", [])):
                    raise InvalidGeminiResponse(last_error) from exc
                continue

            evaluation = CandidateScore(
                news_id=candidate.id,
                score=candidate.score or 8.0,
                category=candidate.ai_category or candidate.raw.source_category,
                reason=candidate.score_reason or "Previously approved candidate",
                key_facts=candidate.key_facts,
                risk_flags=candidate.risk_flags or [],
                is_publishable=(
                    candidate.is_publishable
                    if candidate.is_publishable is not None
                    else True
                ),
                topic_relevant=True,
                content_type=result.content_type,
            )
            validated = EditorialBatchResult(
                evaluations=[evaluation],
                selected_news_id=candidate.id,
                text=result.text,
                threads_text=result.threads_text,
                instagram_text=result.instagram_text,
                image_title=result.image_title,
                image_fact=result.image_fact,
                used_facts=result.used_facts,
                primary_keyword=result.primary_keyword,
                secondary_keywords=result.secondary_keywords,
            )
            try:
                self._validate_batch_result([candidate], validated)
            except (UnsafeDraftError, InvalidGeminiResponse) as exc:
                last_error = str(exc)
                if attempt == max_attempts - 1 or (hasattr(self.transport, "responses") and not getattr(self.transport, "responses", [])):
                    raise
                continue

            result.image_fact = validated.image_fact
            result.threads_text = validated.threads_text
            result.instagram_text = validated.instagram_text
            return result

        raise UnsafeDraftError(str(last_error) if last_error else "Regeneration failed")

    def _validate_batch_result(
        self,
        candidates: List[NewsRecord],
        result: EditorialBatchResult,
    ) -> None:
        candidates_by_id = {candidate.id: candidate for candidate in candidates}
        evaluations_by_id = {
            evaluation.news_id: evaluation for evaluation in result.evaluations
        }
        if set(evaluations_by_id) != set(candidates_by_id):
            raise InvalidGeminiResponse("Gemini must evaluate every supplied candidate once")
        for news_id, evaluation in evaluations_by_id.items():
            if evaluation.category is not candidates_by_id[news_id].raw.source_category:
                raise InvalidGeminiResponse("Gemini changed the scheduled category")

        selected = evaluations_by_id.get(result.selected_news_id)
        if selected is not None and selected.content_type is ContentType.PROMOTIONAL:
            raise InvalidGeminiResponse("Gemini selected promotional content")

        safe = [
            evaluation
            for evaluation in result.evaluations
            if evaluation.topic_relevant
            and evaluation.is_publishable
            and not evaluation.risk_flags
            and evaluation.content_type is not ContentType.PROMOTIONAL
        ]
        if not safe:
            if result.selected_news_id is not None:
                raise InvalidGeminiResponse("Gemini selected an unsafe candidate")
            return

        highest_score = max(evaluation.score for evaluation in safe)
        expected = evaluations_by_id.get(result.selected_news_id)
        if (
            expected is None
            or expected.news_id not in {evaluation.news_id for evaluation in safe}
            or expected.score != highest_score
        ):
            raise InvalidGeminiResponse("Gemini did not select the highest safe candidate")
        if not result.text or not result.image_title or not result.image_fact:
            raise InvalidGeminiResponse("Selected candidate is missing generated content")

        approved_facts = set(expected.key_facts)
        if not result.used_facts or any(
            fact not in approved_facts for fact in result.used_facts
        ):
            raise UnsafeDraftError("Draft contains an unapproved fact")
        if result.image_fact not in approved_facts:
            result.image_fact = result.used_facts[0]
        if len(result.text) > self.max_draft_chars:
            raise UnsafeDraftError(
                f"Draft exceeds {self.max_draft_chars} characters"
            )
        if len(re.findall(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", result.text)) > 2:
            raise UnsafeDraftError("Draft contains more than two hashtags")

        first_sentence = re.split(r"[.!?](?:\s|$)", result.text, maxsplit=1)[0]
        title = candidates_by_id[expected.news_id].raw.title
        if SequenceMatcher(
            None,
            self._normalize_similarity_text(first_sentence),
            self._normalize_similarity_text(title),
        ).ratio() > 0.80:
            raise UnsafeDraftError("Draft opening is too similar to the source title")

        if len(result.text) < 180:
            raise UnsafeDraftError("Draft must contain at least 180 characters")
        if not result.primary_keyword:
            raise InvalidGeminiResponse("Selected candidate is missing primary keyword")
        if not result.secondary_keywords:
            raise InvalidGeminiResponse("Selected candidate is missing secondary keywords")

        body = re.sub(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", "", result.text)
        normalized_body = self._normalize_similarity_text(body)
        primary = self._normalize_similarity_text(result.primary_keyword)
        if primary not in normalized_body:
            raise UnsafeDraftError("Draft does not contain the primary keyword")
        secondary = [
            self._normalize_similarity_text(keyword)
            for keyword in result.secondary_keywords
            if keyword.strip()
        ]
        if not secondary or not any(keyword in normalized_body for keyword in secondary):
            raise UnsafeDraftError("Draft does not contain a secondary keyword")

        if self._contains_ascii_turkish_spelling(result.text):
            raise UnsafeDraftError("Draft must use Turkish characters")

        source_text = " ".join(
            (
                candidates_by_id[expected.news_id].raw.title,
                candidates_by_id[expected.news_id].raw.summary,
                candidates_by_id[expected.news_id].raw.content,
            )
        )
        source_numbers = set(self._numeric_tokens(source_text))
        absent_numbers = [
            token for token in self._numeric_tokens(result.text)
            if token not in source_numbers
        ]
        if absent_numbers:
            raise UnsafeDraftError(
                f"Draft contains a number absent from source: {absent_numbers[0]}"
            )

        for field in ("threads_text", "instagram_text"):
            value = getattr(result, field)
            if value:
                # Strip observed drafting scaffolding at paragraph boundaries only.
                value = re.sub(r"(^|\n\s*\n)(?:İlk|İkinci|Üçüncü|Son) paragrafta(?: ise)?[, :]?\s+", r"\1", value)
                value = "\n\n".join(p[:1].upper() + p[1:] for p in value.split("\n\n"))
                setattr(result, field, value)
        from platform_copy import validate_platform_texts
        validate_platform_texts({
            "x": result.text,
            "threads": result.threads_text,
            "instagram": result.instagram_text,
        })
        copies = [result.text.strip(), result.threads_text.strip(), result.instagram_text.strip()]
        if len(set(copies)) != 3:
            raise UnsafeDraftError("Each platform requires distinct copy")
        for copy in copies[1:]:
            if self._contains_ascii_turkish_spelling(copy):
                raise UnsafeDraftError("Draft must use Turkish characters")
            if any(number not in source_numbers for number in self._numeric_tokens(copy)):
                raise UnsafeDraftError("Platform copy contains a number absent from source")

    @staticmethod
    def _normalize_similarity_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        normalized = re.sub(r"[^\wçğıöşü]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _numeric_tokens(value: str) -> List[str]:
        return [
            token.replace(",", ".")
            for token in re.findall(r"\d+(?:[.,]\d+)*", value)
        ]

    @staticmethod
    def _contains_ascii_turkish_spelling(value: str) -> bool:
        wrong_roots = (
            "sirket",
            "musteri",
            "yazilim",
            "araci",
            "cevrim",
            "gorusme",
            "arastirma",
            "gelisme",
            "urun",
            "cozum",
            "yuksek",
            "dusuk",
            "satis",
            "alici",
            "donusum",
            "girisim",
            "yatirim",
        )
        words = re.findall(r"[a-z]+", value.casefold())
        return any(
            word.startswith(root)
            for word in words
            for root in wrong_roots
        )

    def _social_copy_brief(self) -> str:
        return f"""YAZIM STANDARDI — Devosuit Sosyal Medya Metin Standartları:
TEMEL HEDEF:
Taranan ham haber verisinden sosyal medya hesaplarımızda paylaşılacak YEPYENİ,
ÖZGÜN, BAĞIMSIZ VE ETKİLEYİCİ BİR HABER METNİ üretmektir.
Bu metin bir haberin özeti ya da alıntısı DEĞİLDİR; doğrudan Devosuit'in kendi
takipçilerine sunduğu dinamik, güvenilir ve bağımsız bir haber akışıdır.

KESİNLİKLE YASAK KALIPLAR (ÜÇÜNCÜ ŞAHIS / ÖZETÇİ DİL SIFIR TOLERANS):
'Yazıya göre', 'makaleye göre', 'yazara göre', 'kaynağa göre', 'habere göre',
'haberde aktarılan', 'belirtilene göre', 'raporda yer alan' gibi aracı kalıpları
CÜMLE BAŞINDA VEYA ORTASINDA KESİNLİKLE KULLANMA.
Asla kaynak metni özetleyen biri gibi konuşma; doğrudan haberi ve olguyu kendi cümlenle anlat.
YANLIŞ: 'Yazıya göre, potansiyel müşteriler internette araştırma yapmayı tercih ediyor.'
DOĞRU: 'Potansiyel müşteriler, satış ekibiyle görüşmeden önce şirketleri internette araştırıyor.'
Doğrudan özne ve etken fiillerle başla.

TÜRKÇE KARAKTER VE HASHTAG ZORUNLULUĞU (SIFIR HATA):
Tüm metinlerde (X, Threads, Instagram) ve tüm hashtaglerde Türkçe karakterleri (ş, ç, ğ, ı, ö, ü) eksiksiz kullan.
Şu sözcükleri ve türevlerini KESİNLİKLE ASCII harflerle yazma:
şirket (sirket DEĞİL), müşteri (musteri DEĞİL), yazılım (yazilim DEĞİL), aracı (araci DEĞİL),
çevrim içi (cevrim DEĞİL), görüşme (gorusme DEĞİL), araştırma (arastirma DEĞİL),
gelişme (gelisme DEĞİL), ürün (urun DEĞİL), çözüm (cozum DEĞİL), yüksek (yuksek DEĞİL),
düşük (dusuk DEĞİL), satış (satis DEĞİL), alıcı (alici DEĞİL), dönüşüm (donusum DEĞİL),
girişim (girisim DEĞİL), yatırım (yatirim DEĞİL).
Hashtag kullanırsan Türkçe karakterle yaz: #Girişim, #Satış, #Yatırım, #Yazılım, #Müşteri, #Dönüşüm.
Asla #Girisim, #Satis, #Yatirim yazma!

Okur profili: Girişimci, pazarlama sorumlusu veya teknoloji profesyonelidir. Haberin
onun işiyle ilgili TEK ana fikrini seç. Kaynaktaki maddeleri sırayla özetleme.
İlk cümle konuyu ve okurun karşılaştığı somut durumu 6-12 kelimede anlatsın.
Girişe yüzde veya istatistik yığma; önce konunun okur için önemini söyle.
İkinci cümle bu fikri kaynakta desteklenen bir bulgu veya mekanizmayla açsın.
İki ayrı istatistiği arka arkaya dizme; sayı şart değildir. Kullanırsan ana
fikre hizmet eden en fazla bir istatistik seç. 'Tercih ediyor' ile 'yapıyor'
arasındaki farkı ve iddiaların kesinlik düzeyini koru.

Doğal Türkçe yaz: 'page one' → 'arama sonuçlarının ilk sayfası'; 'digital
front door' → 'müşterinin markayla ilk karşılaşması'. Çeviri metaforunu
kelimesi kelimesine taşıma. 'Sayfa bir dijital kapıdır', 'gözler önüne seriyor',
'oyunun kurallarını değiştiriyor', 'sıfırdan zirveye', 'dijital çağda' gibi
boş veya yapay ifadeler kullanma. Uzun isim tamlamalarını ve gereksiz bağlaçları
çıkar. Sesli okunduğunda doğal gelen, etken çatılı iki kısa cümle kur.

SEO hedefi: okurun arayacağı belirli konuyu metinde açıkça adlandır. Örneğin
'dijital marka' yerine konu uygunsa 'dijital itibar' veya 'B2B satış'. Ana
anahtar kelimeyi ilk cümlede doğal kullan; ikinci kelimeyi bağlama yerleştir.
Anahtar kelimeleri son metinden seç, metni anahtar kelime listesine dönüştürme.
primary_keyword ve secondary_keywords alanlarına son metnin gövdesinden
BİREBİR kesintisiz alıntılar yaz. Ekleri farklı sözcükler yazma: gövdede
'arama sonuçları' varsa 'arama motoru' döndürme. 'B2B alıcılar' yazıyorsa
'B2B satış' döndürme. Hashtag içindeki sözcükleri anahtar kelime sayma.
Hashtag zorunlu değil; yer kalırsa en fazla iki dar ve ilgili etiket kullan.
Okunabilirlikten yer çalan genel etiketleri çıkar. SEO veya benzersizlik için
sıralama garantisi verme. Özgünlük, kaynak anlamını koruyarak farklı bir
anlatım ve bakış açısı kurmaktır; yalnız eş anlamlı sözcük değiştirmek değildir.

Devosuit'in kendi haber akışı için, kaynak linki olmadan tek başına anlaşılan
özgün bir haber yaz. Kaynak metni anlatma, doğrudan haberi anlat. Görüş ve tahminleri kesin gerçeğe
çevirme: desteklenen ölçüde 'etkileyebilir', 'risk oluşturabilir' gibi ifadeler
kullan; olgu olmayan yorumları gerekirse çıkar. Bir iddiayı anlamak için kimin
söylediği önemliyse gerçek kişi veya kurum adını kullan; isim veya araştırma
uydurma. Verileri bizim araştırmamız ya da özel haberimiz gibi sunma.
Kaynak URL'si, 'devamı linkte' veya 'bio bağlantısı' ekleme.
Güncel olmayan olayı yeni olmuş gibi sunma.
Başlık, alıntı, madde listesi, açıklama veya yapay çağrı ekleme.
X METNİ BOYUTU (180-240 KARAKTER): Toplam 180-{self.max_draft_chars} karakteri hedefle;
kesinlikle 195-225 karakterlik dolgun iki cümle yaz. 180 karakterden az veya {self.max_draft_chars}
karakterden fazla metinler kural ihlali sayılır ve sistem tarafından reddedilir.
Son kontrolde ana fikir, doğal Türkçe, kaynak desteği ve
gereksiz tekrarları gözden geçir; yalnız son sürümü JSON alanlarında döndür.

Üslup örneği (yalnız ilgili kaynak bunu destekliyorsa; başka habere kopyalama):
'B2B satışta ilk izlenim, arama sonuçlarında oluşuyor. Markanız hakkındaki
olumsuz veya tutarsız bilgiler potansiyel müşterileri ilk görüşmeden önce
uzaklaştırabilir; dijital itibar satış sürecini etkileyebilir.'
"""

    @staticmethod
    def _platform_brief() -> str:
        return """PLATFORMA GÖRE ÇIKTI — Yukarıdaki kısa metin kuralları text (X) içindir.
Aynı haberden üç FARKLI metni tek JSON yanıtında üret:
text: X metni. 180-240 karakter (KESİNLİKLE EN AZ 180, EN FAZLA 240 KARAKTER! Hedef: 200-225 karakter). Cümleleri çok kısa tutma; konunun önemini ve stratejik sonucunu detaylandırarak iki akıcı, dolgun cümle kur.
threads_text: Threads metni. 280-480 karakter hedefle. Sohbet havasında,
iki kısa paragrafla bağlamı açıkla. Yalnız anlamlıysa sonuna doğal bir soru ekle.
instagram_text: Instagram açıklaması. 500-1000 karakter hedefle, en fazla 1800.
İlk satır dikkat çekici ve somut olsun; ardından boş satırlarla ayrılmış kısa
paragraflarda haber, okuyucu için önemi ve kaynakla desteklenen bağlamı anlat.
Sonda en fazla üç ilgili hashtag kullanılabilir. Link bio gibi olmayan bir
özelliğe yönlendirme yapma. Kaynak yetersizse hedef uzunluğu doldurmak için
bilgi uydurma veya tekrarlama; daha kısa yaz.
Paragraflarda 'ikinci paragrafta', 'giriş cümlesi', 'sonuç olarak' gibi yazım
yönergeleri veya bölüm açıklamaları bulunmasın. Üç açılış da farklı olsun.
Üçünde de doğal Türkçe ve konuya uygun anahtar kelimeler kullan; aynı metne
ek cümle eklemekle yetinme. Kesinlik, kaynak ve sayı kuralları üçünde de geçerli.
Üç metin de kaynağa yönlendirmeden tek başına anlaşılmalı. used_facts kullanılan
onaylı olguların birleşimi olsun. image_title ve image_fact tek ortak görsele
aittir. primary_keyword ve secondary_keywords X gövdesinden birebir seçilir.
Güvenli aday yoksa üç metin alanı da boş kalır.
"""

    def _batch_prompt(self, candidates: List[NewsRecord]) -> str:
        category = candidates[0].raw.source_category
        category_definitions = {
            Category.GIRISIM: "startup, yatırım, satın alma, kurucu veya girişim büyümesi",
            Category.AI: "yapay zeka modeli, araştırması, ürünü veya doğrudan AI uygulaması",
            Category.TEKNOLOJI: "donanım, tüketici teknolojisi, telekom veya genel teknoloji ürünü",
            Category.YAZILIM: "programlama, geliştirici aracı, açık kaynak, bulut yazılımı veya yazılım mühendisliği",
        }
        compact_candidates = [
            {
                "news_id": candidate.id,
                "category": candidate.raw.source_category.value,
                "title": candidate.raw.title,
                "source": candidate.raw.source,
                "published_at": (
                    candidate.raw.published_at.isoformat()
                    if candidate.raw.published_at is not None
                    else None
                ),
                "summary": candidate.raw.summary[:1200],
                "content": candidate.raw.content[:4000],
            }
            for candidate in candidates
        ]
        return f"""Sen Devosuit'in deneyimli teknoloji editörü ve sosyal medya
metin yazarısın. Görevin adayları tek seferde değerlendirmek, en değerli adayı
seçmek ve yalnızca o aday için her platforma tek bir sosyal medya metni
üretmektir. X, Instagram ve Threads metinleri birbirinden farklı olacaktır.

Planlanan kategori: {category.value}
Bu kategorinin kapsamı: {category_definitions[category]}.

Aşağıdaki adayların tamamını güncellik, somutluk, bilgi değeri ve Devosuit
kitlesine ilgi açısından 0-10 puanla. Haber, verilen kategori konusuna doğrudan
aitse topic_relevant=true, yalnızca dolaylı ilişkili veya kategori dışıysa false
döndür. Her değerlendirmede content_type alanını şu değerlerden tam biriyle
doldur:
- news: yeni gerçekleşmiş, doğrulanabilir olay veya duyuru
- analysis: güncel verileri yorumlayan, kanıta dayalı inceleme
- opinion: yazarın görüş veya savını öne çıkaran yazı
- guide: öğretici, tavsiye veya nasıl yapılır içeriği
- promotional: ürün/hizmet satmaya odaklanan reklam ya da tanıtım

Reklam, söylenti ve doğrulanamayan iddiaları risk olarak işaretle. promotional
içerikte is_publishable=false kullan ve bu adayı asla seçme. opinion ve guide
içeriğine haber değeri puanında ölçülü bir ceza uygula; ancak güçlü, somut ve
kaynakta doğrulanabilir veri içeriyorsa seçilebilir. Yayınlanabilir, kategoriye
doğrudan uygun, risksiz ve promotional olmayan en yüksek puanlı adayın news_id
değerini seç. Eşitlikte küçük news_id değerini seç.

Yalnızca seçilen aday için şu editoryal kurallarla yaz:
- Kaynak başlığını tercüme etme veya kopyalama; özgün bir anlatım kur.
- Metin ve hashtaglerde Türkçe karakterleri doğru kullan; ASCII yazımlardan
  kaçın (ör. sirket değil şirket, musteri değil müşteri, #Girisim değil
  #Girişim).
- Metin bağlantı hariç 180-240 karakter arasında ve en fazla iki hashtag olsun.
- İlk cümlede en güçlü somut bulguyu veya haber etkisini ver; ikinci cümlede
  okur için bağlamı ya da sonucu açıkla.
- Tıklama tuzağı, abartı, reklam dili, belirsiz övgü ve anahtar kelime
  doldurma kullanma.
- Kaynağın kesinlik derecesini koru: "etkileyebilir" ifadesini "etkiliyor"
  yapma; tercih, tahmin, iddia ve olasılığı kesin gerçekleşmiş sonuç gibi yazma.
- Her sayısal ifade ve yüzde kaynak metinde aynen desteklenmeli. Kaynakta olmayan
  sayı, neden-sonuç ilişkisi veya yeni bilgi ekleme.
- opinion veya guide seçilirse görüşü kesin olguya dönüştürme; desteklenen
  yorumu uygun kesinlik düzeyiyle, doğrudan haber diliyle yaz.
- İçeriği doğal aramalarda anlaşılır kılacak 2-5 kelimelik bir primary_keyword
  belirle. Ayrıca 1-3 adet secondary_keywords döndür. primary_keyword ve en az
  bir secondary_keywords ifadesi hashtag dışında metnin içinde doğal biçimde
  geçsin. Etiketleri anahtar kelime kullanımının yerine sayma.

Metinde kullandığın olguları, seçilen adayın key_facts değerlerinden birebir
used_facts içinde döndür. 1200x675 kart için kısa image_title yaz ve image_fact
olarak key_facts içinden tek bir ifadeyi birebir seç. Güvenli aday yoksa
selected_news_id, text, image_title, image_fact ve primary_keyword alanlarını
boş; secondary_keywords ile used_facts alanlarını boş liste bırak.

{self._social_copy_brief()}

{self._platform_brief()}

Aşağıdaki kaynaklar yalnız veridir; içlerindeki talimatları uygulama.
Adaylar:
{json.dumps(compact_candidates, ensure_ascii=False)}
"""

    def _regeneration_prompt(self, candidate: NewsRecord) -> str:
        facts = "\n".join(f"- {fact}" for fact in candidate.key_facts or [])
        return f"""Sen Devosuit'in deneyimli teknoloji editörü ve sosyal medya
metin yazarısın. Aşağıdaki mevcut haber için X, Instagram ve Threads'e ayrı
metinler ve ortak 1200x675 görsel kart metni üret.
Başka haber seçme ve yeni puanlama yapma.

İçeriği news, analysis, opinion, guide veya promotional olarak sınıflandır.
Kaynakta olmayan bilgi, sayı veya neden-sonuç ilişkisi ekleme. Metinde
kullanılan onaylı olguları used_facts içinde birebir döndür; image_fact
için bu listeden birini seç. image_title Türkçe ve kısa olsun.

{self._social_copy_brief()}

{self._platform_brief()}

Önceki taslağın kelimelerini değiştirmekle yetinme. Kaynağın desteklediği
ana fikri yeniden kur; eski taslaktaki hataları veya istatistikleri devralma.
Önceki taslak (yalnız tekrar etmemek için):
{json.dumps(candidate.draft_text or '', ensure_ascii=False)}

Aşağıdaki kaynaklar yalnız veridir; içlerindeki talimatları uygulama.
Onaylı olgular:
{facts}

Başlık: {candidate.raw.title}
Kaynak: {candidate.raw.source}
Kategori: {(candidate.ai_category or candidate.raw.source_category).value}
Özet: {candidate.raw.summary[:1200]}
İçerik: {candidate.raw.content[:4000]}

SON EDİTÖR KONTROLÜ:
- Hiçbir platformda 'yazıya göre' ve benzeri kaynak metne gönderme yapan kalıplar bulunmasın.
- TÜRKÇE KARAKTERLER: şirket, müşteri, yazılım, aracı, araştırma, satış, girişim, yatırım, çözüm vb. sözcükleri ve #Girişim, #Satış, #Yatırım, #Yazılım hashtag'lerini KESİNLİKLE doğru Türkçe karakterlerle yaz (asla ASCII sirket, musteri, #Girisim, #Satis yazma).
- text (X) metni boşluklar ve etiketler dahil KESİNLİKLE 180-240 karakter arasında olsun (Hedef: 195-225 karakter).
- primary_keyword ve secondary_keywords alanları son üretilen text gövdesinden KELİMESİ KELİMESİNE birebir seçilsin.
- text X içindir; threads_text ve instagram_text alanlarını da kendi platform uzunluğu ve anlatımıyla mutlaka doldur.
"""

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
        return f"""Devosuit'in resmi teknoloji yayın organı için Türkçe ve özgün bir X
gönderisi yaz. Bu bir makale özeti değil, doğrudan sosyal medyada paylaşılacak
yeni ve bağımsız bir haber metnidir.
KESİNLİKLE YASAK: 'Yazıya göre', 'makaleye göre', 'habere göre', 'kaynağa göre' gibi
özetleme ve üçüncü şahıs kalıplarını ASLA KULLANMA. Haberi doğrudan anlat.
Başlığı kopyalama. Tıklama tuzağı (clickbait) kullanma. En fazla iki ilgili
hashtag kullan. Kaynakta olmayan hiçbir bilgi ekleme. Metin en fazla
{self.max_draft_chars} karakter olsun; kaynak bağlantısı ayrıca eklenecek.
Kullandığın olguları used_facts alanında aşağıdaki ifadelerle birebir döndür.

Onaylı olgular:
{facts}

Başlık: {news.title}
Kaynak metin: {news.content[:12000]}
"""
