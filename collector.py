"""RSS collection with source-level error isolation and verified TLS."""

import asyncio
import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Mapping, Optional, Protocol
from urllib.parse import urlsplit

import feedparser

from domain import Category, RawNews


@dataclass(frozen=True)
class FetchResponse:
    status: int
    body: bytes
    final_url: str


class FetchError(Exception):
    def __init__(
        self,
        *,
        url: str,
        status_code: Optional[int],
        message: str,
    ):
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.message = message


class HttpClient(Protocol):
    async def get(self, url: str) -> FetchResponse:
        ...


class AioHttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        max_response_bytes: int = 10_000_000,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._session = None

    async def get(self, url: str) -> FetchResponse:
        import aiohttp

        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "application/rss+xml,*/*;q=0.8"
                    ),
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
        try:
            async with self._session.get(url, allow_redirects=True) as response:
                if response.status >= 400:
                    raise FetchError(
                        url=url,
                        status_code=response.status,
                        message=f"HTTP {response.status}",
                    )
                body = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise FetchError(
                            url=url,
                            status_code=response.status,
                            message="response exceeds size limit",
                        )
                return FetchResponse(
                    status=response.status,
                    body=bytes(body),
                    final_url=str(response.url),
                )
        except FetchError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise FetchError(
                url=url,
                status_code=None,
                message=str(exc),
            ) from exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


@dataclass
class CollectionResult:
    items: List[RawNews] = field(default_factory=list)
    errors: List[FetchError] = field(default_factory=list)


def _extract_article(body: bytes) -> Optional[str]:
    import trafilatura

    html = body.decode("utf-8", errors="replace")
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )


def _published_at(entry) -> Optional[datetime]:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


class RssCollector:
    def __init__(
        self,
        *,
        feeds: Mapping[Category, List[str]],
        http: HttpClient,
        article_extractor: Callable[[bytes], Optional[str]] = _extract_article,
        entries_per_feed: int = 10,
        max_concurrency: int = 8,
    ):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self.feeds = dict(feeds)
        self.http = http
        self.article_extractor = article_extractor
        self.entries_per_feed = entries_per_feed
        self._request_semaphore = asyncio.Semaphore(max_concurrency)

    @staticmethod
    def normalized_feeds(feeds: Mapping[str, List[str]]) -> Dict[Category, List[str]]:
        names = {
            "Startup": Category.GIRISIM,
            "Girisim": Category.GIRISIM,
            "AI": Category.AI,
            "Teknoloji": Category.TEKNOLOJI,
            "Yazilim": Category.YAZILIM,
        }
        return {names[name]: list(urls) for name, urls in feeds.items()}

    async def collect(self, category: Optional[Category] = None) -> CollectionResult:
        result = CollectionResult()
        feeds = (
            {category: self.feeds.get(category, [])}
            if category is not None
            else self.feeds
        )
        tasks = [
            self._collect_feed(category, feed_url, result)
            for category, feed_urls in feeds.items()
            for feed_url in feed_urls
        ]
        await asyncio.gather(*tasks)
        return result

    async def _get(self, url: str) -> FetchResponse:
        async with self._request_semaphore:
            return await self.http.get(url)

    async def _collect_feed(
        self,
        category: Category,
        feed_url: str,
        result: CollectionResult,
    ) -> None:
        try:
            response = await self._get(feed_url)
        except FetchError as exc:
            result.errors.append(exc)
            return

        parsed = await asyncio.to_thread(feedparser.parse, response.body)
        if parsed.bozo and not parsed.entries:
            result.errors.append(
                FetchError(
                    url=feed_url,
                    status_code=response.status,
                    message=str(parsed.bozo_exception),
                )
            )
            return

        source = parsed.feed.get("title") or urlsplit(feed_url).hostname or feed_url
        await asyncio.gather(
            *(
                self._collect_entry(category, source, entry, result)
                for entry in parsed.entries[: self.entries_per_feed]
            )
        )

    async def _collect_entry(self, category, source, entry, result) -> None:
        url = str(entry.get("link", "")).strip()
        if not url:
            return
        try:
            article_response = await self._get(url)
        except FetchError as exc:
            result.errors.append(exc)
            return
        try:
            content = await asyncio.to_thread(
                self.article_extractor,
                article_response.body,
            )
        except Exception as exc:
            result.errors.append(
                FetchError(
                    url=url,
                    status_code=article_response.status,
                    message=f"article extraction failed: {exc}",
                )
            )
            return
        if not content or len(content.strip()) < 10:
            result.errors.append(
                FetchError(
                    url=url,
                    status_code=article_response.status,
                    message="article content is empty or too short",
                )
            )
            return
        result.items.append(
            RawNews(
                url=article_response.final_url,
                title=str(entry.get("title", "")).strip(),
                summary=str(
                    entry.get("summary", entry.get("description", ""))
                ).strip(),
                content=content.strip(),
                source=str(source),
                source_category=category,
                published_at=_published_at(entry),
            )
        )
