"""Shared domain values for the Devosuit news workflow."""

from enum import Enum


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

