# Run Next Slot Now Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a protected dashboard action that immediately prepares content for the next Istanbul publishing slot without consuming that scheduled run.

**Architecture:** A pure schedule helper identifies the next slot. `ScheduledContentRunner` accepts an explicit isolated run key through a manual-test entry point while sharing the existing collection, scoring, drafting, and image pipeline. FastAPI starts it as a background task and the dashboard's existing polling reveals the result.

**Tech Stack:** Python 3.9, FastAPI, Jinja2, APScheduler, pytest, vanilla JavaScript.

## Global Constraints

- One manual click uses at most one normal Gemini batch request, except the existing single retry on a retryable response.
- Manual test keys must never equal scheduled slot keys.
- Only the next Istanbul-time category is eligible.
- No external social network publishing.
- State-changing requests require administrator authentication and CSRF validation.

---

### Task 1: Next-slot calculation

**Files:**
- Modify: `schedule.py`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Produces: `next_slot(now: datetime) -> PublishingSlot`

- [ ] Add failing tests for before 10:00, between slots, and after 20:00.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_schedule.py` and confirm the missing helper failure.
- [ ] Implement timezone-aware next-slot selection, wrapping to the next day's 10:00 slot.
- [ ] Run the schedule tests and confirm they pass.

### Task 2: Isolated manual runner

**Files:**
- Modify: `scheduled_content.py`
- Test: `tests/test_scheduled_content.py`

**Interfaces:**
- Produces: `ScheduledContentRunner.run_test_slot(slot: PublishingSlot) -> Optional[ContentRun]`
- Reuses: the existing slot preparation pipeline with an explicit unique `test:` run key.

- [ ] Add a failing test proving the manual test prepares the winner and does not claim the normal scheduled key.
- [ ] Run the targeted test and confirm failure because `run_test_slot` is absent.
- [ ] Extract the shared execution body and implement the manual entry point with a per-process concurrency guard.
- [ ] Run all scheduled-content tests and confirm they pass.

### Task 3: Protected panel action

**Files:**
- Modify: `app.py`
- Modify: `main.py`
- Modify: `templates/dashboard.html`
- Modify: `static/dashboard.js`
- Modify: `static/app.css`
- Test: `tests/test_app.py`

**Interfaces:**
- Adds: `POST /content/test-next-slot`
- Consumes: `next_slot(datetime.now(ISTANBUL_TIMEZONE))` and `content_runner.run_test_slot(slot)`.

- [ ] Add failing tests for the displayed next slot, CSRF protection, and background invocation.
- [ ] Run the targeted application tests and confirm the route/UI assertions fail.
- [ ] Inject `content_runner`, add the protected route, pass `next_publishing_slot` to the template, and wire the action into the dashboard polling UI.
- [ ] Run all application tests and confirm they pass.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `SETUP.md`

- [ ] Document the manual test button, one-call cost, and scheduled-run isolation.
- [ ] Run `.venv/bin/python -m pytest -q` and require all environment-independent tests to pass.
- [ ] Run `.venv/bin/python -m compileall -q -x '(^|/)(\\.venv|\\.git)/' .`.
- [ ] Run `git diff --check`.
- [ ] Restart the local server and verify `curl -fsS http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
