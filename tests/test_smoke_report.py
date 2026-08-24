from datetime import datetime, timezone

from domain import Category, RawNews
from gemini_service import DraftResult, ScoreResult
from smoke_test import SmokeResult, render_smoke_report


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
