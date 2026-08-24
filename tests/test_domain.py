import pytest

from domain import AiJobState, AiJobType, Category, NewsState


def test_categories_have_stable_database_values():
    assert [category.value for category in Category] == [
        "Girisim",
        "AI",
        "Teknoloji",
        "Yazilim",
    ]


def test_unknown_category_is_rejected():
    with pytest.raises(ValueError):
        Category("Startup")


def test_news_and_job_states_cover_review_workflow():
    assert NewsState.APPROVED.value == "approved"
    assert NewsState.REJECTED.value == "rejected"
    assert AiJobType.SCORE.value == "score"
    assert AiJobState.RETRY.value == "retry"
