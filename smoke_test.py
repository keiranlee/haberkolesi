"""Explicit live RSS and Gemini smoke test; never publishes externally."""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

from collector import AioHttpClient, RssCollector
from config import (
    GEMINI_API_KEY,
    GEMINI_MIN_INTERVAL_SECONDS,
    GEMINI_MIN_SCORE,
    GEMINI_MODEL,
    RSS_FEEDS,
)
from domain import Category, RawNews
from filtering import select_candidates
from gemini_service import (
    DraftResult,
    GeminiService,
    GoogleGenAITransport,
    ScoreResult,
)
from rate_limiter import AsyncRequestGate


@dataclass(frozen=True)
class SmokeResult:
    news: RawNews
    score: ScoreResult
    draft: DraftResult
    created_at: datetime


def render_smoke_report(result: SmokeResult) -> str:
    facts = "\n".join(f"- {fact}" for fact in result.score.key_facts)
    risks = (
        "\n".join(f"- {risk}" for risk in result.score.risk_flags)
        if result.score.risk_flags
        else "- Risk işareti yok."
    )
    return f"""# Devosuit Gemini Haber Testi

**Oluşturulma:** {result.created_at.isoformat()}
**Model:** {GEMINI_MODEL}
**Kategori:** {result.score.category.value}

## Orijinal haber

**Başlık:** {result.news.title}
**Kaynak:** {result.news.source}
**URL:** {result.news.url}

{result.news.content}

## Gemini puanı

**Puan:** {result.score.score:.1f}/10
**Yayınlanabilir:** {"Evet" if result.score.is_publishable else "Hayır"}
**Gerekçe:** {result.score.reason}

### Temel gerçekler

{facts}

### Risk işaretleri

{risks}

## Devosuit metni

{result.draft.text}

## Kullanılan gerçekler

{chr(10).join(f"- {fact}" for fact in result.draft.used_facts)}
"""


async def run_live(category: Category, output: Path) -> SmokeResult:
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        raise RuntimeError("GEMINI_API_KEY must be configured for --live")

    normalized_feeds = RssCollector.normalized_feeds(RSS_FEEDS)
    http_client = AioHttpClient()
    collector = RssCollector(
        feeds={category: normalized_feeds[category]},
        http=http_client,
    )
    try:
        collected = await collector.collect()
    finally:
        await http_client.close()

    candidates = select_candidates(
        collected.items,
        now=datetime.now(timezone.utc),
        max_age=timedelta(hours=24),
        per_category=5,
    )
    if not candidates:
        errors = "; ".join(error.message for error in collected.errors[:5])
        raise RuntimeError(f"No recent {category.value} candidate found. {errors}")

    transport = GoogleGenAITransport(GEMINI_API_KEY)
    service = GeminiService(
        transport=transport,
        gate=AsyncRequestGate(GEMINI_MIN_INTERVAL_SECONDS),
        model=GEMINI_MODEL,
    )
    try:
        scored: List[tuple] = []
        for news in candidates:
            score = await service.score_news(news)
            if score.is_publishable and score.score >= GEMINI_MIN_SCORE:
                scored.append((news, score))
        if not scored:
            raise RuntimeError(
                f"No {category.value} candidate passed score {GEMINI_MIN_SCORE:.1f}"
            )

        news, score = max(scored, key=lambda pair: pair[1].score)
        draft = await service.generate_draft(news, score)
    finally:
        await service.close()
    result = SmokeResult(
        news=news,
        score=score,
        draft=draft,
        created_at=datetime.now(timezone.utc),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_smoke_report(result), encoding="utf-8")
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow real RSS and Gemini API requests",
    )
    parser.add_argument(
        "--category",
        choices=[category.value for category in Category],
        default=Category.GIRISIM.value,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/gemini-smoke-report.md"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.live:
        raise SystemExit("Refusing network/API calls without explicit --live")
    result = asyncio.run(run_live(Category(args.category), args.output))
    print(f"Report: {args.output}")
    print(f"Selected: {result.news.title} ({result.score.score:.1f}/10)")


if __name__ == "__main__":
    main()
