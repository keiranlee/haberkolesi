# AI Provider Toggle Implementation Plan

**Goal:** Preserve Gemini and add selectable OpenAI scoring, platform copy, and text-free images.

**Architecture:** Persist a single provider name in PostgreSQL. Resolve an immutable text/image service bundle at job start, never fall back silently. Reuse existing editorial validation and prompts through an OpenAI JSON transport. Keep Gemini's local card renderer unchanged.

**Tech Stack:** FastAPI, asyncpg, Pydantic, httpx, Pillow, pytest.

## Constraints

- Default is OpenAI (updated at the user's explicit request on 2026-10-28). A saved panel selection survives restarts. Credentials stay in environment variables; Gemini is optional when using OpenAI.
- No live API request without a key; mocked HTTP tests do not incur charges.
- OpenAI defaults: gpt-5.4-mini with reasoning none; gpt-image-2, low, 1536x1024, one PNG.
- Existing OpenAI image is reused on text regeneration; no text, logo, watermark or source overlays.
- Selection is admin/CSRF protected and applies to subsequent jobs, not running work.
- No publishing behavior changes.

## Tasks

- [x] Add failing tests for persisted selection, missing credentials, HTTP contracts, malformed/refused output, image reuse, and authenticated panel selection.
- [x] Add `ai_providers.py` bundles and selection controller, `openai_service.py` HTTP integrations, environment defaults and database setting methods.
- [x] Snapshot provider services in worker and scheduled runner, wire both in main, and add dashboard selection using existing design conventions.
- [x] Run new tests and full regression suite; test job switching while an operation is running.
- [x] Document key installation and restart, model settings, image reuse, and live-test limitation.

Review additionally required provider pinning across queued retries/restarts. This is persisted in `ai_jobs.provider`; repeated binding uses `COALESCE`. Regeneration now obtains the image before committing the new draft, preserving old copy on image failure. Both regressions are covered. Independent read-only review found no remaining important findings. Live paid generation is deferred until the user installs the key.

Known baseline issue: `tests/test_x_publisher.py::test_publish_x_web_endpoint` fails independently on Python 3.9 when the unchanged X publisher constructs an asyncio lock without a current event loop. X publishing was not modified in this task.

## Verification commands

```sh
.venv/bin/python -m pytest -q tests/test_ai_providers.py tests/test_openai_service.py
.venv/bin/python -m pytest -q
git diff --check
```
