from datetime import datetime, timezone

import pytest

from domain import Category, RawNews
from gemini_service import (
    CandidateScore,
    ContentType,
    DraftResult,
    EditorialBatchResult,
    ScoreResult,
)
from smoke_test import SmokeResult, evaluate_smoke_candidates, render_smoke_report


def test_smoke_report_compares_source_score_and_draft():
    result = SmokeResult(
        news=RawNews(
            url="https://source.test/news",
            title="Source title",
            summary="Source summary",
            content="Complete source content.",
            source="Source",
            source_category=Category.AI,
            published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        ),
        score=ScoreResult(
            score=9.1,
            category=Category.AI,
            reason="Güncel ve önemli.",
            key_facts=["Somut bilgi."],
            risk_flags=[],
            is_publishable=True,
        ),
        draft=DraftResult(
            text="Devosuit için yeni haber metni. #AI",
            used_facts=["Somut bilgi."],
        ),
        created_at=datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc),
    )

    report = render_smoke_report(result)

    assert "## Orijinal haber" in report
    assert "## Gemini puanı" in report
    assert "## Devosuit metni" in report
    assert "https://source.test/news" in report
    assert "Devosuit için yeni haber metni" in report


@pytest.mark.asyncio
async def test_smoke_evaluation_uses_one_batch_request_for_at_most_three_candidates():
    candidates = [
        RawNews(
            url=f"https://source.test/{index}",
            title=f"Source title {index}",
            summary="Source summary",
            content="Complete source content.",
            source="Source",
            source_category=Category.AI,
            published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        for index in range(5)
    ]

    class BatchService:
        calls = 0
        received = []

        async def evaluate_candidates(self, records):
            self.calls += 1
            self.received = records
            selected = records[1]
            fact = "Somut bilgi."
            return EditorialBatchResult(
                evaluations=[
                    CandidateScore(
                        news_id=record.id,
                        score=9.0 if record.id == selected.id else 8.0,
                        category=Category.AI,
                        reason="Güncel.",
                        key_facts=[fact],
                        risk_flags=[],
                        is_publishable=True,
                        topic_relevant=True,
                        content_type=ContentType.NEWS,
                    )
                    for record in records
                ],
                selected_news_id=selected.id,
                text="Kaynaklardan seçilen yeni ve özgün metin. #AI",
                image_title="Yeni AI gelişmesi",
                image_fact=fact,
                used_facts=[fact],
                primary_keyword="yapay zeka aracı",
                secondary_keywords=["yazılım ekipleri"],
            )

    service = BatchService()

    result = await evaluate_smoke_candidates(candidates, service)

    assert service.calls == 1
    assert len(service.received) == 3
    assert result.news == candidates[1]
