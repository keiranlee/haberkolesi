# Devosuit News Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a password-protected panel that collects recent RSS news, filters and ranks up to five candidates per category with Gemini 3.7 Flash, generates one editable Devosuit X draft on demand, and never publishes externally.

**Architecture:** Extend the existing Python application into one FastAPI service with PostgreSQL-backed collection batches and AI jobs. Keep RSS collection, deterministic filtering, Gemini access, orchestration, persistence, and HTTP presentation behind separate interfaces so each can be tested independently. A single durable worker processes Gemini jobs at least 15 seconds apart.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, HTMX, asyncpg, aiohttp, feedparser, trafilatura, Google Gen AI SDK (`google-genai`), APScheduler, pytest, pytest-asyncio, HTTPX.

## Global Constraints

- Work only on `feature/devosuit-news-panel`; do not merge or push to `main`.
- First phase must not call X APIs or generate news images.
- Use `gemini-3.7-flash` by default and allow override through `GEMINI_MODEL`.
- Start at most one Gemini request every 15 seconds and never run concurrent Gemini requests.
- Keep at most five new Gemini candidates per category per collection batch.
- Categories are exactly `Girisim`, `AI`, `Teknoloji`, and `Yazilim`.
- Initial development password is supplied as `ADMIN_PASSWORD=1234` in `.env.example`, never hardcoded in Python.
- Generate text only for the highest-ranked requested candidate; generate the next candidate only after explicit rejection.
- Approval only changes database state. It must not publish to X.
- Preserve `assets/logotek.svg`; visual generation is outside this plan.
- Use test-first development for every behavior change.

---

## Planned File Structure

```text
haberkolesi/
├── app.py                         # FastAPI factory, lifespan, middleware
├── config.py                      # Validated environment settings and sources
├── database.py                    # Pool initialization and schema migration
├── domain.py                      # Enums and typed records shared across modules
├── collector.py                   # RSS fetch, parse, article extraction
├── filtering.py                   # URL normalization, freshness, dedup, category caps
├── repositories.py                # PostgreSQL persistence and atomic state changes
├── pipeline.py                    # Collection/scoring/generation orchestration
├── gemini_service.py              # Structured Gemini scoring and text generation
├── rate_limiter.py                # Injected-clock 15-second request gate
├── worker.py                      # Durable ai_jobs worker
├── auth.py                        # Password/session helpers
├── main.py                        # Uvicorn entry point and scheduler startup
├── smoke_test.py                  # Explicit real-Gemini test report command
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   └── news_detail.html
├── static/app.css                 # Devosuit panel styles
├── tests/
│   ├── fixtures/rss_sample.xml
│   ├── test_config.py
│   ├── test_filtering.py
│   ├── test_rate_limiter.py
│   ├── test_gemini_service.py
│   ├── test_collector.py
│   ├── test_pipeline.py
│   ├── test_repositories.py
│   ├── test_auth.py
│   └── test_app.py
├── .env.example
├── .gitignore
├── Dockerfile
└── requirements.txt
```

### Task 1: Testable Configuration and Domain Types

**Files:**
- Create: `domain.py`
- Create: `tests/test_config.py`
- Create: `tests/test_domain.py`
- Modify: `config.py`
- Modify: `.env.example`
- Create: `.gitignore`
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: `Category`, `NewsState`, `AiJobType`, `AiJobState`, `Settings`, `get_settings()`.
- Consumes: environment variables and the existing RSS source mapping.

- [ ] **Step 1: Add test dependencies and write failing configuration tests**

```python
# tests/test_config.py
import pytest
from config import Settings


def test_settings_require_secrets(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings.from_env()


def test_settings_use_safe_gemini_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_PASSWORD", "1234")
    settings = Settings.from_env()
    assert settings.gemini_model == "gemini-3.7-flash"
    assert settings.gemini_min_interval_seconds == 15.0
    assert settings.candidate_limit_per_category == 5
```

- [ ] **Step 2: Run tests and verify the expected import/API failure**

Run: `pytest tests/test_config.py -v`

Expected: FAIL because `Settings` does not exist.

- [ ] **Step 3: Add domain enums and validated settings**

```python
# domain.py
from enum import StrEnum


class Category(StrEnum):
    GIRISIM = "Girisim"
    AI = "AI"
    TEKNOLOJI = "Teknoloji"
    YAZILIM = "Yazilim"


class NewsState(StrEnum):
    COLLECTED = "collected"
    SCORED = "scored"
    DRAFTED = "drafted"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class AiJobType(StrEnum):
    SCORE = "score"
    GENERATE = "generate"


class AiJobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
```

Implement an immutable `Settings` dataclass in `config.py` with `from_env()`. It must require `GEMINI_API_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, and `SESSION_SECRET`; parse numeric values; validate `15 <= GEMINI_MIN_INTERVAL_SECONDS`; and use a project-local `data/` default outside Docker.

- [ ] **Step 4: Update dependencies and ignored paths**

Add exact runtime packages `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `itsdangerous`, `google-genai`, and `pydantic`. Add `pytest`, `pytest-asyncio`, and `httpx` to `requirements-dev.txt`. Ignore `.env`, `.venv/`, `data/`, `__pycache__/`, `.pytest_cache/`, and `.worktrees/`.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_config.py tests/test_domain.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add config.py domain.py .env.example .gitignore requirements.txt requirements-dev.txt tests/test_config.py tests/test_domain.py
git commit -m "feat: add validated news panel configuration"
```

### Task 2: Deterministic News Filtering

**Files:**
- Create: `filtering.py`
- Create: `tests/test_filtering.py`

**Interfaces:**
- Consumes: `RawNews(url, title, summary, content, source, source_category, published_at)`.
- Produces: `normalize_url(url: str) -> str` and `select_candidates(items, now, max_age, per_category) -> list[RawNews]`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_normalize_url_removes_tracking_and_fragment():
    url = "https://Example.com/a/?utm_source=rss&x=1#top"
    assert normalize_url(url) == "https://example.com/a?x=1"


def test_select_candidates_deduplicates_and_caps_each_category(news_factory, now):
    items = [news_factory(category=Category.AI, index=i) for i in range(7)]
    items += [news_factory(category=Category.GIRISIM, index=i) for i in range(6)]
    selected = select_candidates(items, now=now, max_age=timedelta(hours=24), per_category=5)
    assert sum(item.source_category == Category.AI for item in selected) == 5
    assert sum(item.source_category == Category.GIRISIM for item in selected) == 5
```

Also cover old items, duplicate normalized URLs, duplicate normalized titles, missing publication dates, and deterministic newest-first ordering.

- [ ] **Step 2: Run tests and confirm module-not-found failure**

Run: `pytest tests/test_filtering.py -v`

Expected: FAIL because `filtering.py` does not exist.

- [ ] **Step 3: Implement minimal pure filtering functions**

Use `urllib.parse` to remove `utm_*`, `fbclid`, `gclid`, fragments, duplicate trailing slashes, and lowercase only scheme/host. Normalize titles with Unicode case folding and whitespace collapse. Treat missing publication dates as ineligible rather than guessing freshness.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_filtering.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add filtering.py domain.py tests/test_filtering.py
git commit -m "feat: filter and deduplicate news candidates"
```

### Task 3: Safe Gemini Rate Limiter

**Files:**
- Create: `rate_limiter.py`
- Create: `tests/test_rate_limiter.py`

**Interfaces:**
- Produces: `AsyncRequestGate(min_interval: float, clock: Callable, sleep: Callable)` and `await gate.acquire()`.
- Consumes: monotonic clock and async sleep function.

- [ ] **Step 1: Write a failing fake-clock test**

```python
@pytest.mark.asyncio
async def test_gate_starts_requests_at_least_15_seconds_apart(fake_clock):
    gate = AsyncRequestGate(15.0, fake_clock.now, fake_clock.sleep)
    await gate.acquire()
    await gate.acquire()
    await gate.acquire()
    assert fake_clock.sleep_calls == [15.0, 15.0]
```

Add a concurrency test proving two simultaneous callers serialize through one `asyncio.Lock`.

- [ ] **Step 2: Run test and verify missing implementation failure**

Run: `pytest tests/test_rate_limiter.py -v`

Expected: FAIL because `AsyncRequestGate` does not exist.

- [ ] **Step 3: Implement the lock-protected monotonic gate**

```python
class AsyncRequestGate:
    def __init__(self, min_interval, clock=time.monotonic, sleep=asyncio.sleep):
        self.min_interval = min_interval
        self.clock = clock
        self.sleep = sleep
        self._lock = asyncio.Lock()
        self._last_started = None

    async def acquire(self):
        async with self._lock:
            if self._last_started is not None:
                delay = self.min_interval - (self.clock() - self._last_started)
                if delay > 0:
                    await self.sleep(delay)
            self._last_started = self.clock()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_rate_limiter.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rate_limiter.py tests/test_rate_limiter.py
git commit -m "feat: enforce Gemini request spacing"
```

### Task 4: Structured Gemini Scoring and Draft Generation

**Files:**
- Create: `gemini_service.py`
- Create: `tests/test_gemini_service.py`

**Interfaces:**
- Produces: `ScoreResult`, `DraftResult`, `GeminiService.score_news(news)`, `GeminiService.generate_draft(news, score)`.
- Consumes: `google.genai.Client`, `AsyncRequestGate`, `Settings`.

- [ ] **Step 1: Write failing contract tests with a transport fake**

```python
@pytest.mark.asyncio
async def test_score_news_returns_validated_structured_result(fake_transport, news):
    fake_transport.respond_with({
        "score": 8.7,
        "category": "AI",
        "reason": "Yeni ve somut ürün haberi.",
        "key_facts": ["Ürün bugün duyuruldu."],
        "risk_flags": [],
        "is_publishable": True,
    })
    result = await service(fake_transport).score_news(news)
    assert result.score == 8.7
    assert result.category is Category.AI


@pytest.mark.asyncio
async def test_generate_draft_rejects_facts_not_present_in_score(fake_transport, news, score):
    fake_transport.respond_with({"text": "Kaynakta olmayan 10 milyon dolar yatırım aldı.", "used_facts": ["10 milyon dolar"]})
    with pytest.raises(UnsafeDraftError):
        await service(fake_transport).generate_draft(news, score)
```

Test invalid category, score outside 0–10, malformed JSON, empty draft, more than two hashtags, and configured X text budget.

- [ ] **Step 2: Run tests and verify expected failure**

Run: `pytest tests/test_gemini_service.py -v`

Expected: FAIL because service and schemas do not exist.

- [ ] **Step 3: Implement Pydantic schemas and prompts**

Use `client.aio.models.generate_content()` with model `settings.gemini_model`, `response_mime_type="application/json"`, and a response schema. Scoring prompt must instruct the model to use only supplied source text. Draft prompt must include approved `key_facts`, Devosuit tone rules, source URL budget, and at most two hashtags. Validate the response before returning it.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_gemini_service.py -v`

Expected: all tests pass without real network requests.

- [ ] **Step 5: Commit**

```bash
git add gemini_service.py tests/test_gemini_service.py
git commit -m "feat: score news and generate Devosuit drafts"
```

### Task 5: RSS Collection and Article Extraction

**Files:**
- Create: `collector.py`
- Create: `tests/fixtures/rss_sample.xml`
- Create: `tests/test_collector.py`
- Modify: `config.py`

**Interfaces:**
- Produces: `RssCollector.collect() -> CollectionResult` containing `items` and per-source `errors`.
- Consumes: configured `RSS_FEEDS`, injected `aiohttp.ClientSession`, and article extractor.

- [ ] **Step 1: Write failing fixture-based tests**

```python
@pytest.mark.asyncio
async def test_collect_parses_feed_and_extracts_article(fake_http, rss_fixture):
    fake_http.feed("https://source.test/feed", rss_fixture)
    fake_http.page("https://source.test/news", "<article><p>Long source content.</p></article>")
    result = await collector(fake_http).collect()
    assert result.items[0].title == "Sample AI news"
    assert result.items[0].content == "Long source content."


@pytest.mark.asyncio
async def test_one_broken_source_does_not_stop_other_sources(fake_http, rss_fixture):
    fake_http.error("https://broken.test/feed", 403)
    fake_http.feed("https://source.test/feed", rss_fixture)
    result = await collector(fake_http).collect()
    assert len(result.items) == 1
    assert result.errors[0].status_code == 403
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_collector.py -v`

Expected: FAIL because `RssCollector` does not exist.

- [ ] **Step 3: Implement bounded, certificate-verified collection**

Use one shared `aiohttp.ClientSession`, TLS verification enabled, total timeout 20 seconds, response-size limit, per-source exception isolation, `asyncio.to_thread(feedparser.parse, bytes)`, and `trafilatura.extract`. Do not collect X accounts in phase one.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_collector.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add collector.py config.py tests/fixtures/rss_sample.xml tests/test_collector.py
git commit -m "feat: collect recent RSS news safely"
```

### Task 6: PostgreSQL Schema and Atomic Repository

**Files:**
- Modify: `database.py`
- Create: `repositories.py`
- Create: `tests/test_repositories.py`

**Interfaces:**
- Produces: `NewsRepository`, `BatchRepository`, `AiJobRepository` with atomic state transitions.
- Consumes: `asyncpg.Pool` and domain enums.

- [ ] **Step 1: Write failing repository integration tests**

```python
@pytest.mark.asyncio
async def test_insert_news_is_idempotent(repository, raw_news):
    first = await repository.insert_news(raw_news)
    second = await repository.insert_news(raw_news)
    assert first.id == second.id
    assert await repository.count_news() == 1


@pytest.mark.asyncio
async def test_claim_next_job_uses_skip_locked(job_repository):
    await job_repository.enqueue_score(news_id=1)
    first, second = await asyncio.gather(
        job_repository.claim_next("worker-a"),
        job_repository.claim_next("worker-b"),
    )
    assert sum(job is not None for job in (first, second)) == 1
```

Use a test database URL from `TEST_DATABASE_URL`. Skip integration tests with a clear message only when that variable is absent; CI must provide it.

- [ ] **Step 2: Run tests and verify missing schema/API failure**

Run: `pytest tests/test_repositories.py -v`

Expected: FAIL when `TEST_DATABASE_URL` is configured because repositories do not exist.

- [ ] **Step 3: Implement migrations and repositories**

Create tables `collection_batches`, `news_items`, `generation_versions`, `ai_jobs`, and `editor_actions`. Use unique `normalized_url`, category/state check constraints, timestamps with time zone, `FOR UPDATE SKIP LOCKED` for claiming jobs, and transactions for reject-and-enqueue-next and approve transitions.

Required signatures:

```python
async def insert_news(self, batch_id: int, item: RawNews) -> NewsRecord: ...
async def save_score(self, news_id: int, result: ScoreResult) -> None: ...
async def save_generation(self, news_id: int, result: DraftResult) -> GenerationRecord: ...
async def claim_next(self, worker_id: str) -> AiJob | None: ...
async def retry(self, job_id: int, next_attempt_at: datetime, error: str) -> None: ...
async def reject_and_enqueue_next(self, news_id: int, category: Category) -> int | None: ...
async def approve(self, news_id: int, edited_text: str | None) -> None: ...
```

- [ ] **Step 4: Run repository tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/haberkolesi_test pytest tests/test_repositories.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add database.py repositories.py tests/test_repositories.py
git commit -m "feat: persist news and durable AI jobs"
```

### Task 7: Pipeline and Durable AI Worker

**Files:**
- Create: `pipeline.py`
- Create: `worker.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `NewsPipeline.start_collection()`, `prepare_candidate(category)`, `reject_candidate(news_id)`, `approve_candidate(news_id, edited_text)`, and `AiWorker.run_once()`.
- Consumes: collector, filtering functions, repositories, Gemini service, and request gate.

- [ ] **Step 1: Write failing orchestration tests**

```python
@pytest.mark.asyncio
async def test_collection_enqueues_at_most_five_scores_per_category(pipeline, collector, jobs):
    collector.return_items(make_news(Category.AI, 7) + make_news(Category.GIRISIM, 6))
    await pipeline.start_collection()
    assert await jobs.count(AiJobType.SCORE, Category.AI) == 5
    assert await jobs.count(AiJobType.SCORE, Category.GIRISIM) == 5


@pytest.mark.asyncio
async def test_prepare_generates_only_highest_scored_candidate(pipeline, news, jobs):
    await news.add_scored(Category.AI, scores=[9.1, 8.8, 8.2])
    selected = await pipeline.prepare_candidate(Category.AI)
    assert selected.score == 9.1
    assert await jobs.count(AiJobType.GENERATE, Category.AI) == 1


@pytest.mark.asyncio
async def test_reject_enqueues_exactly_one_next_candidate(pipeline, drafted_news, jobs):
    await pipeline.reject_candidate(drafted_news.id)
    assert await jobs.count(AiJobType.GENERATE, drafted_news.category) == 1
```

Also test that approval only changes state, collection cannot overlap, worker retries 429/5xx with exponential backoff, and permanent validation errors become failed.

- [ ] **Step 2: Run tests and verify expected failure**

Run: `pytest tests/test_pipeline.py -v`

Expected: FAIL because pipeline and worker do not exist.

- [ ] **Step 3: Implement orchestration and one-job worker loop**

The worker must claim one job, call `await gate.acquire()`, execute score or generate, persist the result, and mark the job complete. On retryable errors, calculate `min(300, 15 * 2 ** attempts)` seconds and persist `next_attempt_at`. The continuous loop calls `run_once()` and waits on an event or a short idle interval; it must stop cleanly during FastAPI shutdown.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_pipeline.py tests/test_rate_limiter.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline.py worker.py tests/test_pipeline.py
git commit -m "feat: orchestrate collection and Gemini jobs"
```

### Task 8: Session Authentication and Panel API

**Files:**
- Create: `auth.py`
- Create: `app.py`
- Create: `tests/test_auth.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Produces: `create_app(settings, repositories, pipeline) -> FastAPI` and authenticated panel routes.
- Consumes: settings, repositories, and pipeline service.

- [ ] **Step 1: Write failing authentication and route tests**

```python
def test_dashboard_redirects_anonymous_user(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_accepts_configured_password(client):
    response = client.post("/login", data={"password": "1234"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_approve_never_calls_external_publisher(authenticated_client, pipeline):
    response = authenticated_client.post("/news/42/approve", data={"edited_text": "Onaylı metin"})
    assert response.status_code == 303
    pipeline.approve_candidate.assert_awaited_once_with(42, "Onaylı metin")
```

Add CSRF rejection, wrong-password, logout, collect, prepare, reject, regenerate, list filter, and detail tests.

- [ ] **Step 2: Run tests and verify missing app failure**

Run: `pytest tests/test_auth.py tests/test_app.py -v`

Expected: FAIL because auth and app factory do not exist.

- [ ] **Step 3: Implement signed-session auth and routes**

Use `SessionMiddleware` with `HttpOnly`, `SameSite=Lax`, configurable `https_only`, and `SESSION_SECRET`. Compare passwords with `secrets.compare_digest`. Create a per-session CSRF token and require it on every state-changing POST.

Required routes:

```text
GET/POST /login
POST     /logout
GET      /
POST     /collect
GET      /news/{news_id}
POST     /news/{news_id}/prepare
POST     /news/{news_id}/regenerate
POST     /news/{news_id}/approve
POST     /news/{news_id}/reject
```

- [ ] **Step 4: Run focused HTTP tests**

Run: `pytest tests/test_auth.py tests/test_app.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add auth.py app.py tests/test_auth.py tests/test_app.py
git commit -m "feat: add authenticated news panel API"
```

### Task 9: Devosuit Panel Templates and Styles

**Files:**
- Create: `templates/base.html`
- Create: `templates/login.html`
- Create: `templates/dashboard.html`
- Create: `templates/news_detail.html`
- Create: `static/app.css`
- Modify: `app.py`
- Add: `assets/logotek.svg`
- Modify: `tests/test_app.py`

**Interfaces:**
- Produces: server-rendered dashboard and detail UI.
- Consumes: view models returned by repositories and authenticated routes.

- [ ] **Step 1: Add failing rendered-content tests**

```python
def test_dashboard_shows_quota_and_filters(authenticated_client):
    html = authenticated_client.get("/").text
    assert "Gemini kuyruğu" in html
    assert "Sonraki istek" in html
    assert 'name="category"' in html


def test_detail_shows_original_and_generated_text(authenticated_client):
    html = authenticated_client.get("/news/42").text
    assert "Orijinal haber" in html
    assert "Devosuit metni" in html
    assert "Görsel sonraki aşamada" in html
    assert "X yayını kapalı" in html
```

- [ ] **Step 2: Run rendered-content tests and verify failure**

Run: `pytest tests/test_app.py -k 'dashboard or detail' -v`

Expected: FAIL because templates are absent.

- [ ] **Step 3: Implement responsive templates**

Use semantic HTML, keyboard-visible focus, labeled forms, status badges with text plus color, responsive tables/cards, and confirmation text for actions that consume a Gemini request. Use `#201F4B` as the primary dark surface and the logo's orange gradient for actions. Show a warning banner when `ADMIN_PASSWORD=1234`.

- [ ] **Step 4: Run panel tests**

Run: `pytest tests/test_app.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add app.py assets/logotek.svg templates static tests/test_app.py
git commit -m "feat: add Devosuit news review interface"
```

### Task 10: Application Lifespan, Scheduler, and Docker Runtime

**Files:**
- Modify: `main.py`
- Modify: `app.py`
- Modify: `Dockerfile`
- Create: `docker-compose.yml`
- Modify: `SETUP.md`
- Create: `tests/test_lifespan.py`

**Interfaces:**
- Produces: one runnable web service with database initialization, worker startup, clean shutdown, and periodic collection.
- Consumes: app factory, database pool, worker, pipeline, and scheduler.

- [ ] **Step 1: Write failing lifespan tests**

```python
@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_worker(app_factory, worker):
    app = app_factory(worker=worker)
    async with LifespanManager(app):
        worker.start.assert_called_once()
    worker.stop.assert_awaited_once()


def test_no_publisher_job_is_registered(scheduler):
    ids = {job.id for job in scheduler.get_jobs()}
    assert "collector_job" in ids
    assert "publisher_job" not in ids
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_lifespan.py -v`

Expected: FAIL because the web lifespan is not wired.

- [ ] **Step 3: Wire runtime without external publishing**

Use FastAPI lifespan to initialize schema, start one AI worker, create the collection scheduler, and stop worker/pool cleanly. Run with `uvicorn main:app --host 0.0.0.0 --port 8000`. Docker healthcheck calls `/health`; it must verify process and database connectivity without opening a new leaked connection.

- [ ] **Step 4: Run application tests**

Run: `pytest tests/test_lifespan.py tests/test_app.py -v`

Expected: all tests pass.

- [ ] **Step 5: Build container**

Run: `docker build -t haberkolesi:feature .`

Expected: image builds successfully.

- [ ] **Step 6: Commit**

```bash
git add main.py app.py Dockerfile docker-compose.yml SETUP.md tests/test_lifespan.py
git commit -m "feat: run news panel and worker service"
```

### Task 11: Explicit Real-Gemini Smoke Test and Report

**Files:**
- Create: `smoke_test.py`
- Create: `tests/test_smoke_report.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `python smoke_test.py --category AI --output data/gemini-smoke-report.md`.
- Consumes: live RSS sources, configured Gemini API, pipeline, and report renderer.

- [ ] **Step 1: Write failing report-rendering test**

```python
def test_smoke_report_compares_source_score_and_draft(sample_result):
    report = render_smoke_report(sample_result)
    assert "## Orijinal haber" in report
    assert "## Gemini puanı" in report
    assert "## Devosuit metni" in report
    assert sample_result.source_url in report
```

- [ ] **Step 2: Run test and verify missing function failure**

Run: `pytest tests/test_smoke_report.py -v`

Expected: FAIL because `render_smoke_report` does not exist.

- [ ] **Step 3: Implement explicit smoke command**

The command requires `--live` before making network/API calls, creates one collection batch, waits until the chosen category is scored, generates only its highest-ranked candidate, writes the Markdown comparison, prints the output path, and exits. It must never approve, generate an image, or publish to X.

- [ ] **Step 4: Run all offline tests**

Run: `pytest -v`

Expected: all offline tests pass; live smoke test is not run automatically.

- [ ] **Step 5: Run one authorized live test**

Run: `python smoke_test.py --live --category Girisim --output data/gemini-smoke-report.md`

Expected: one Markdown report containing source content, score, reason, risk flags, and one generated Devosuit draft.

- [ ] **Step 6: Review generated copy with the user**

Open `data/gemini-smoke-report.md`, compare every factual claim against the source facts, and collect concrete tone/copy feedback before changing the prompt.

- [ ] **Step 7: Commit**

```bash
git add smoke_test.py tests/test_smoke_report.py README.md
git commit -m "test: add live Gemini news smoke report"
```

### Task 12: Final Verification on the Feature Branch

**Files:**
- No new files expected.

**Interfaces:**
- Consumes: the complete phase-one implementation.
- Produces: verification evidence for user review; no merge or push.

- [ ] **Step 1: Run formatting and static checks**

Run: `python -m compileall -q .`

Expected: exit code 0.

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`

Expected: all tests pass with zero failures.

- [ ] **Step 3: Build the Docker image**

Run: `docker build -t haberkolesi:feature .`

Expected: exit code 0.

- [ ] **Step 4: Confirm external integrations remain disabled**

Run: `rg -n "create_tweet|publish_to_x|image generation|imagegen" app.py pipeline.py worker.py main.py`

Expected: no active call path from the phase-one runtime.

- [ ] **Step 5: Review branch state**

Run: `git status --short && git log --oneline --decorate -12`

Expected: intended feature commits only; `main` remains unchanged.

- [ ] **Step 6: Hand off for user testing**

Provide local start commands, panel URL, login password source, test evidence, known source failures, and the generated smoke report path. Do not merge or push until the user explicitly approves the tested result.
