"""Shared domain values for the Devosuit news workflow."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


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

