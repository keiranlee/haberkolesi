"""Pure filtering rules applied before any Gemini request is queued."""

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from domain import Category, RawNews


TRACKING_PARAMETERS = {"fbclid", "gclid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            urlencode(query_items, doseq=True),
            "",
        )
    )


def _normalize_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def select_candidates(
    items: Iterable[RawNews],
    *,
    now: datetime,
    max_age: timedelta,
    per_category: int = 5,
) -> List[RawNews]:
    eligible = [
        item
        for item in items
        if item.published_at is not None
        and item.published_at.tzinfo is not None
        and now - max_age <= item.published_at <= now
    ]
    eligible.sort(
        key=lambda item: (item.published_at, normalize_url(item.url)),
        reverse=True,
    )

    selected: List[RawNews] = []
    category_counts = defaultdict(int)
    seen_urls = set()
    seen_titles = set()

    for item in eligible:
        normalized_url = normalize_url(item.url)
        normalized_title = _normalize_title(item.title)
        if normalized_url in seen_urls or normalized_title in seen_titles:
            continue
        if category_counts[item.source_category] >= per_category:
            continue
        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        category_counts[item.source_category] += 1
        selected.append(item)

    return selected
