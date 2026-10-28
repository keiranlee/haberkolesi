import os

import pytest

os.environ.setdefault("DATA_DIR", "/tmp/haberkolesi-tests")

from config import Settings


REQUIRED = {
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/test",
    "GEMINI_API_KEY": "test-key",
    "ADMIN_PASSWORD": "1234",
    "SESSION_SECRET": "test-session-secret",
}


def set_required_environment(monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)


def test_settings_allow_openai_without_a_gemini_api_key(monkeypatch):
    set_required_environment(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY")

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    settings = Settings.from_env()
    assert settings.gemini_api_key == ""
    assert settings.openai_api_key == "test-openai-key"


def test_settings_use_safe_gemini_defaults(monkeypatch):
    set_required_environment(monkeypatch)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MIN_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("CANDIDATE_LIMIT_PER_CATEGORY", raising=False)

    settings = Settings.from_env()

    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.gemini_min_interval_seconds == 15.0
    assert settings.candidate_limit_per_category == 3


def test_settings_reject_request_interval_below_rate_limit(monkeypatch):
    set_required_environment(monkeypatch)
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "11.9")

    with pytest.raises(ValueError, match="at least 15"):
        Settings.from_env()


def test_openai_is_optional_and_has_cost_bounded_defaults(monkeypatch):
    set_required_environment(monkeypatch)
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_IMAGE_MODEL", "OPENAI_IMAGE_QUALITY"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.openai_api_key == ""
    assert settings.openai_model == "gpt-5.4-mini"
    assert settings.openai_image_model == "gpt-image-2"
    assert settings.openai_image_quality == "low"


def test_invalid_openai_quality_rejected_before_any_paid_request(monkeypatch):
    set_required_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_IMAGE_QUALITY", "auto")
    with pytest.raises(ValueError, match="OPENAI_IMAGE_QUALITY"):
        Settings.from_env()
