"""Shared domain values for the Devosuit news workflow."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional


class Category(str, Enum):
    GIRISIM = "Girisim"
    AI = "AI"
    TEKNOLOJI = "Teknoloji"
    YAZILIM = "Yazilim"


class NewsState(str, Enum):
    COLLECTED = "collected"
    SCORED = "scored"
    DRAFTED = "drafted"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class AiJobType(str, Enum):
    SCORE = "score"
    GENERATE = "generate"


class AiJobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class RawNews:
    url: str
    title: str
    summary: str
    content: str
    source: str
    source_category: Category
    published_at: Optional[datetime]


@dataclass
class NewsRecord:
    id: int
    batch_id: int
    raw: RawNews
    normalized_url: str
    state: NewsState = NewsState.COLLECTED
    score: Optional[float] = None
    ai_category: Optional[Category] = None
    score_reason: Optional[str] = None
    key_facts: Optional[List[str]] = None
    risk_flags: Optional[List[str]] = None
    is_publishable: Optional[bool] = None
    draft_text: Optional[str] = None
    external_post_id: Optional[str] = None


@dataclass
class AiJob:
    id: int
    news_id: int
    job_type: AiJobType
    state: AiJobState
    attempts: int = 0
    next_attempt_at: Optional[datetime] = None
    worker_id: Optional[str] = None
    last_error: Optional[str] = None


@dataclass(frozen=True)
class EditorAction:
    news_id: int
    action: str
    created_at: datetime

