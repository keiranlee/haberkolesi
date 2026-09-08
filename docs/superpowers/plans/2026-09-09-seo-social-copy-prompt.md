# SEO Social Copy Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing single Gemini batch call produce one accurate, discoverable, natural Turkish social caption with explicit content type and keyword metadata.

**Architecture:** Extend the structured batch schema rather than adding another Gemini call. Validate content type, attribution, length, keywords, Turkish orthography, numbers, facts, hashtags, and title originality locally before a draft can be stored.

**Tech Stack:** Python 3.9, Pydantic, Google Gen AI structured output, pytest, pytest-asyncio.

## Global Constraints

- Keep one Gemini request per scheduled slot.
- Produce one shared X, Instagram, and Threads caption.
- Caption length is 180–240 characters.
- Use at most two hashtags.
- Do not publish externally.
- Preserve existing uncommitted work.

---

### Task 1: Extend the editorial response contract

**Files:**
- Modify: `gemini_service.py`
- Modify: `tests/test_gemini_service.py`

**Interfaces:**
- Produce `ContentType` values `news`, `analysis`, `opinion`, `guide`, and `promotional`.
- Add `content_type` to `CandidateScore`.
- Add `primary_keyword` and `secondary_keywords` to `EditorialBatchResult`.

- [ ] Write a failing test proving the new fields are required and parsed.
- [ ] Run `.venv/bin/python -m pytest tests/test_gemini_service.py -q` and confirm schema validation fails.
- [ ] Add the enum and Pydantic fields with bounded string/list lengths.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Enforce content quality locally

**Files:**
- Modify: `gemini_service.py`
- Modify: `tests/test_gemini_service.py`

**Interfaces:**
- Extend `GeminiService._validate_batch_result` without changing the public call count.

- [ ] Add failing tests for captions below 180 characters, missing primary keyword, missing all secondary keywords, ASCII Turkish words, source-absent numbers, promotional winners, and opinion winners without attribution.
- [ ] Run each focused test and confirm the failure is caused by missing validation.
- [ ] Implement normalization and validation helpers. Compare numeric tokens against the selected source; inspect caption body without hashtags for keyword presence; reject common ASCII spellings of Turkish words.
- [ ] Run all Gemini service tests and confirm they pass.

### Task 3: Replace the batch prompt with an editorial brief

**Files:**
- Modify: `gemini_service.py`
- Modify: `tests/test_gemini_service.py`

**Interfaces:**
- Keep `GeminiService.evaluate_candidates(candidates)` unchanged.

- [ ] Add a failing behavior test whose transport returns a compliant response only when supplied with the B2B source fixture and full structured schema.
- [ ] Update the prompt to define content types, category relevance, opinion/guide scoring penalty, promotional rejection, natural search phrases, 180–240 character structure, attribution, modality preservation, Turkish characters, number fidelity, and one-output-only behavior.
- [ ] Run the focused test and all Gemini tests.

### Task 4: Update orchestration fakes and live smoke verification

**Files:**
- Modify: `tests/test_scheduled_content.py`
- Modify: `tests/test_smoke_report.py`
- Modify: `README.md`
- Modify: `SETUP.md`

**Interfaces:**
- Existing scheduled runner and smoke runner consume the expanded response without adding calls.

- [ ] Update fake structured responses to provide content type and keyword fields and use compliant 180–240 character Turkish captions.
- [ ] Run `.venv/bin/python -m pytest tests/test_scheduled_content.py tests/test_smoke_report.py -q`.
- [ ] Run one explicit live Gemini smoke test and inspect keyword use, Turkish spelling, length, factual numbers, and content type.
- [ ] Document the discoverability rules and content-type handling.

### Task 5: Full verification and runtime restart

**Files:**
- Test: complete project

**Interfaces:**
- No interface changes.

- [ ] Run `.venv/bin/python -m pytest -q`.
- [ ] Run `.venv/bin/python -m compileall -q -x '(^|/)(\.venv|\.git)/' .`.
- [ ] Run `git diff --check`.
- [ ] Restart the existing port 8000 process and verify `curl -fsS http://127.0.0.1:8000/health` returns `{"status":"ok"}`.
