# Hourly Category Content Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At six Istanbul-time slots, collect only the scheduled category, evaluate up to three candidates in one Gemini call, and prepare one original social post plus one local Devosuit image without publishing externally.

**Architecture:** Add a single source of truth for the daily schedule and durable slot-run records for idempotency. A scheduled content runner will perform category-scoped collection, deterministic preselection, one structured Gemini evaluation, persistence, and local card generation. The legacy per-news score queue will no longer be fed or consumed by the automatic path.

**Tech Stack:** Python 3.11, FastAPI, APScheduler, asyncpg/PostgreSQL, Pydantic, Google Gen AI SDK, Pillow, pytest, pytest-asyncio.

## Global Constraints

- Time zone is `Europe/Istanbul`.
- Schedule is 10:00 Girisim, 12:00 AI, 14:00 Teknoloji, 16:00 AI, 18:00 Yazilim, 20:00 Girisim.
- At most three candidates are sent in one Gemini request per slot.
- Normal budget is at most six Gemini calls per day.
- The shared post text is at most 240 characters and at most two hashtags.
- The generated image is one local 1200×675 PNG; no image AI is used.
- X, Instagram, and Threads APIs are not called in this phase.
- Existing uncommitted panel and image work must be preserved.

---

### Task 1: Schedule and category-scoped collection

**Files:**
- Create: `schedule.py`
- Modify: `collector.py`
- Test: `tests/test_schedule.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Produces: `PUBLISHING_SLOTS: tuple[PublishingSlot, ...]`, where the ellipsis is Python's variable-length tuple type marker; `PublishingSlot(hour: int, category: Category)`; and `slot_for(hour: int) -> PublishingSlot | None`.
- Produces: `RssCollector.collect(category: Category | None = None) -> CollectionResult`.

- [ ] **Step 1: Write failing schedule and scoped-collector tests**

```python
def test_schedule_maps_only_six_publishing_hours():
    assert [(slot.hour, slot.category) for slot in PUBLISHING_SLOTS] == [
        (10, Category.GIRISIM), (12, Category.AI),
        (14, Category.TEKNOLOJI), (16, Category.AI),
        (18, Category.YAZILIM), (20, Category.GIRISIM),
    ]

@pytest.mark.asyncio
async def test_collecting_one_category_does_not_fetch_other_feeds():
    result = await collector.collect(Category.AI)
    assert result.items
    assert all(item.source_category is Category.AI for item in result.items)
    assert http.requested_urls == ["https://ai.test/feed", "https://source.test/news"]
```

- [ ] **Step 2: Run the focused tests and verify missing API failures**

Run: `.venv/bin/python -m pytest tests/test_schedule.py tests/test_collector.py -q`

Expected: FAIL because `schedule.py` and the category argument do not exist.

- [ ] **Step 3: Implement the immutable schedule and scoped feed selection**

Use a frozen `PublishingSlot` dataclass. When `category` is supplied, `collect` must build tasks only from `self.feeds[category]`; without it, preserve the existing all-category behavior for manual collection compatibility.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_schedule.py tests/test_collector.py -q`

Expected: PASS.

### Task 2: One-call Gemini editorial evaluation

**Files:**
- Modify: `gemini_service.py`
- Test: `tests/test_gemini_service.py`

**Interfaces:**
- Produces: `CandidateScore`, `EditorialBatchResult`, and `GeminiService.evaluate_candidates(candidates: list[NewsRecord]) -> EditorialBatchResult`.
- `EditorialBatchResult` contains `evaluations`, `selected_news_id`, `text`, `image_title`, `image_fact`, and `used_facts`.

- [ ] **Step 1: Write failing tests for one request, safe winner selection, and original copy**

```python
@pytest.mark.asyncio
async def test_evaluate_candidates_uses_one_transport_request_for_three_records(records):
    result = await service.evaluate_candidates(records)
    assert transport.calls == 1
    assert len(result.evaluations) == 3
    assert result.selected_news_id == records[1].id

@pytest.mark.asyncio
async def test_evaluate_candidates_rejects_title_copy(records):
    transport.payload["text"] = records[0].raw.title
    with pytest.raises(UnsafeDraftError, match="too similar"):
        await service.evaluate_candidates(records)
```

- [ ] **Step 2: Run the focused tests and verify the new API is missing**

Run: `.venv/bin/python -m pytest tests/test_gemini_service.py -q`

Expected: FAIL because batch response models and `evaluate_candidates` do not exist.

- [ ] **Step 3: Implement structured batch prompting and validation**

Send at most 4,000 source characters per candidate. Validate candidate IDs, 0–10 scores, safe winner membership, highest safe winner selection, approved `used_facts`, 240-character length, two-hashtag maximum, and less than 0.80 `SequenceMatcher` similarity between the normalized source title and generated first sentence.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_gemini_service.py -q`

Expected: PASS.

### Task 3: Durable slot-run idempotency

**Files:**
- Modify: `domain.py`
- Modify: `database.py`
- Modify: `repositories.py`
- Test: `tests/test_repositories.py`

**Interfaces:**
- Produces: `ContentRunState`, `ContentRun`, `repository.claim_content_run(slot_key, scheduled_for, category) -> ContentRun | None`, `complete_content_run(run_id, selected_news_id | None)`, and `fail_content_run(run_id, error)`.
- Produces: `repository.list_content_runs(day) -> list[ContentRun]`.
- Produces: `repository.disable_active_score_jobs(reason) -> int` for retiring the old quota-consuming queue.

- [ ] **Step 1: Write failing memory-repository behavior tests**

```python
@pytest.mark.asyncio
async def test_content_run_can_be_claimed_only_once():
    first = await repository.claim_content_run("2026-09-08T12:AI", NOW, Category.AI)
    second = await repository.claim_content_run("2026-09-08T12:AI", NOW, Category.AI)
    assert first is not None
    assert second is None

@pytest.mark.asyncio
async def test_disable_active_score_jobs_leaves_generate_jobs_available():
    disabled = await repository.disable_active_score_jobs("replaced")
    assert disabled == 1
    assert (await repository.get_job(score_job.id)).state is AiJobState.FAILED
    assert (await repository.get_job(generate_job.id)).state is AiJobState.PENDING
```

- [ ] **Step 2: Run repository tests and verify interface failures**

Run: `.venv/bin/python -m pytest tests/test_repositories.py -q`

Expected: FAIL because slot-run persistence is absent.

- [ ] **Step 3: Implement memory and PostgreSQL persistence**

Create `content_runs` with a unique `slot_key`, `scheduled_for`, category, state, selected news ID, error, and timestamps. Use `INSERT ... ON CONFLICT DO NOTHING RETURNING *` for atomic claims. Update active score jobs to failed with the supplied migration reason, leaving generate jobs untouched.

- [ ] **Step 4: Run repository tests**

Run: `.venv/bin/python -m pytest tests/test_repositories.py -q`

Expected: PASS (PostgreSQL integration remains conditional on `TEST_DATABASE_URL`).

### Task 4: Scheduled content runner

**Files:**
- Create: `scheduled_content.py`
- Modify: `filtering.py`
- Modify: `repositories.py`
- Test: `tests/test_scheduled_content.py`

**Interfaces:**
- Consumes: scoped collector, `GeminiService.evaluate_candidates`, slot-run repository APIs, and `ImageService.generate_card`.
- Produces: `ScheduledContentRunner.run_slot(slot: PublishingSlot, scheduled_for: datetime) -> ContentRun | None`.
- Produces: `select_slot_candidates(items, now, max_age, limit=3) -> list[RawNews]` sorted by recency then content completeness.

- [ ] **Step 1: Write failing orchestration tests**

```python
@pytest.mark.asyncio
async def test_slot_uses_one_batch_call_and_prepares_only_safe_winner():
    run = await runner.run_slot(PublishingSlot(12, Category.AI), NOW)
    assert collector.categories == [Category.AI]
    assert gemini.calls == 1
    assert len(gemini.received_candidates) == 3
    assert (await repository.get_news(winner_id)).state is NewsState.DRAFTED
    assert (await repository.get_news(winner_id)).image_path is not None

@pytest.mark.asyncio
async def test_duplicate_slot_does_not_collect_or_call_gemini_twice():
    await runner.run_slot(slot, NOW)
    await runner.run_slot(slot, NOW)
    assert collector.calls == 1
    assert gemini.calls == 1

@pytest.mark.asyncio
async def test_empty_slot_skips_without_gemini_call():
    run = await runner.run_slot(slot, NOW)
    assert run.state is ContentRunState.SKIPPED
    assert gemini.calls == 0
```

- [ ] **Step 2: Run the focused tests and verify missing runner failures**

Run: `.venv/bin/python -m pytest tests/test_scheduled_content.py -q`

Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement orchestration and persistence**

Claim the slot before collection. Insert at most three new candidates, call Gemini once, save every evaluation, persist only the winning draft, generate its card with Gemini-provided `image_title` and `image_fact`, and complete the run. No safe winner completes the run as skipped. Preserve a valid draft when image generation fails and mark the run error so image regeneration is possible.

- [ ] **Step 4: Add bounded quota retry**

For status 429, parse a `retry_delay`/`Retry-After` value when exposed by the exception, otherwise use 60 seconds. Retry at most once through an injected async sleeper; other malformed responses also retry at most once. Persist the second failure.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_scheduled_content.py -q`

Expected: PASS.

### Task 5: Runtime scheduling and legacy queue shutdown

**Files:**
- Modify: `main.py`
- Modify: `tests/test_lifespan.py`
- Modify: `config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `create_scheduler(runner) -> AsyncIOScheduler` with six cron jobs named `content_10_girisim` through `content_20_girisim`.
- Runtime disables active legacy score jobs before starting `AiWorker`; no automatic path enqueues new score jobs, so the worker remains available only for manual generate jobs.

- [ ] **Step 1: Write failing scheduler tests**

```python
def test_scheduler_registers_exact_content_slots():
    ids = {job.id for job in create_scheduler(runner).get_jobs()}
    assert ids == {
        "content_10_girisim", "content_12_ai", "content_14_teknoloji",
        "content_16_ai", "content_18_yazilim", "content_20_girisim",
    }
```

- [ ] **Step 2: Run scheduler/config tests and verify old interval behavior fails**

Run: `.venv/bin/python -m pytest tests/test_lifespan.py tests/test_config.py -q`

Expected: FAIL because the scheduler still registers one hourly collector job.

- [ ] **Step 3: Wire six cron jobs and retire automatic score jobs**

Each job passes its immutable `PublishingSlot` and the current Istanbul slot time to the runner. Set candidate limit default to 3. Do not register or call the external publisher. Disable existing active score jobs before the worker starts, and change manual all-category collection so it stores news without enqueueing per-news score jobs. Manual regeneration remains available through `generate` jobs.

- [ ] **Step 4: Run scheduler/config tests**

Run: `.venv/bin/python -m pytest tests/test_lifespan.py tests/test_config.py -q`

Expected: PASS.

### Task 6: Image and panel presentation

**Files:**
- Modify: `image_service.py`
- Modify: `app.py`
- Modify: `templates/dashboard.html`
- Modify: `templates/news_detail.html`
- Modify: `static/app.css`
- Modify: `tests/test_image_service.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- `ImageService.generate_card` consumes the short `image_title` and `image_fact` selected by Gemini.
- Produces: `_truncate_lines(lines: list[str], max_lines: int) -> list[str]`, adding an ellipsis to the final retained line when input overflows.
- Dashboard consumes `repository.list_content_runs(today)` and prioritizes drafted records with images.

- [ ] **Step 1: Write failing UI and overflow tests**

```python
def test_dashboard_lists_ready_image_and_generated_copy_first():
    html = authenticated_client.get("/").text
    assert f'src="/news/{ready_id}/image"' in html
    assert "Generated unique copy" in html
    assert html.index("Generated unique copy") < html.index("Collected candidate")

def test_overflowing_card_lines_are_truncated_with_ellipsis():
    assert _truncate_lines(["bir", "iki", "üç"], 2) == ["bir", "iki…"]
```

- [ ] **Step 2: Run focused tests and verify list preview/overflow failures**

Run: `.venv/bin/python -m pytest tests/test_image_service.py tests/test_app.py -q`

Expected: FAIL because images are shown only on detail and overflow truncation is incomplete.

- [ ] **Step 3: Implement card truncation and ready-content panel block**

Truncate wrapped title/fact lines with an ellipsis when they exceed their allocated box. Render the six schedule items from `PUBLISHING_SLOTS`, show current run states, and add ready-content cards before the general news table. Keep the existing detail image route and CSRF behavior.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_image_service.py tests/test_app.py -q`

Expected: PASS.

### Task 7: End-to-end verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `SETUP.md`
- Modify: `smoke_test.py`
- Test: all tests

**Interfaces:**
- Documents one-call-per-slot behavior and explicitly states that external publishing remains disabled.
- Smoke mode evaluates one category with a single batch request and never publishes.

- [ ] **Step 1: Update smoke coverage before implementation changes**

Add a test proving the smoke runner sends one batch of no more than three candidates and produces the selected text without image or publisher calls.

- [ ] **Step 2: Run smoke tests and verify old per-news flow fails**

Run: `.venv/bin/python -m pytest tests/test_smoke_report.py -q`

Expected: FAIL until the smoke runner uses batch evaluation.

- [ ] **Step 3: Update smoke runner and operator documentation**

Document six daily slots, three-candidate batching, six-call normal daily ceiling, 429 behavior, image storage, and how to inspect a failed slot. Remove statements that image generation is a future phase.

- [ ] **Step 4: Run complete verification**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass except explicitly environment-gated PostgreSQL integration tests.

Run: `.venv/bin/python -m compileall -q .`

Expected: exit code 0.

Run: `git diff --check`

Expected: exit code 0.
