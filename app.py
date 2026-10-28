"""FastAPI application factory for the Devosuit news review panel."""

from contextlib import asynccontextmanager
from datetime import datetime
import inspect
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Awaitable, Callable, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import ensure_csrf_token, require_admin, verify_csrf, verify_password
from domain import Category, NewsState
from schedule import PUBLISHING_SLOTS, next_slot


BASE_DIR = Path(__file__).resolve().parent
STATE_LABELS = {
    NewsState.COLLECTED: "Puanlama bekliyor",
    NewsState.SCORED: "Puanlandı",
    NewsState.DRAFTED: "Taslak hazır",
    NewsState.APPROVED: "Onaylandı",
    NewsState.REJECTED: "Reddedildi",
    NewsState.FAILED: "Hata",
}
ISTANBUL_TIMEZONE = ZoneInfo("Europe/Istanbul")


def format_istanbul_datetime(value):
    if value is None:
        return ""
    return value.astimezone(ISTANBUL_TIMEZONE).strftime("%d.%m.%Y · %H:%M")


def create_app(
    settings,
    repository,
    pipeline,
    *,
    worker=None,
    scheduler=None,
    rate_gate=None,
    content_runner=None,
    x_publisher=None,
    ai_providers=None,
    close_callback: Optional[Callable[[], Awaitable[None]]] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        del application
        if worker is not None:
            worker.start()
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            if worker is not None:
                await worker.stop()
            if close_callback is not None:
                result = close_callback()
                if inspect.isawaitable(result):
                    await result

    app = FastAPI(title="Devosuit Haber Paneli", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["istanbul_datetime"] = format_istanbul_datetime
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="devosuit_admin",
        same_site="lax",
        https_only=settings.cookie_secure,
        max_age=60 * 60 * 12,
    )
    app.state.settings = settings
    app.state.repository = repository
    app.state.pipeline = pipeline

    @app.get("/health")
    async def health():
        health_check = getattr(repository, "health", None)
        if health_check is not None:
            await health_check()
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": None},
        )

    @app.post("/login")
    async def login(request: Request, password: str = Form(...)):
        if not verify_password(password, settings.admin_password):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"error": "Geçersiz parola"},
                status_code=401,
            )
        request.session.clear()
        request.session["is_admin"] = True
        ensure_csrf_token(request)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request, csrf_token: str = Form("")):
        require_admin(request)
        verify_csrf(request, csrf_token)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    async def dashboard(
        request: Request,
        category: Optional[Category] = None,
        state: Optional[NewsState] = None,
    ):
        require_admin(request)
        records = await repository.list_news(
            category=category,
            state=state,
            limit=100,
        )
        queue_count = await repository.count_jobs()
        job_counts = await repository.job_counts()
        latest_batch = await repository.latest_batch()
        stats = await repository.dashboard_stats()
        stats["failed_jobs"] = job_counts["failed"]
        active_jobs = await repository.active_jobs_by_news()
        today = datetime.now(ISTANBUL_TIMEZONE).date()
        content_runs = await repository.list_content_runs(today)
        next_publishing_slot = next_slot(datetime.now(ISTANBUL_TIMEZONE))
        run_states = {
            (run.scheduled_for.astimezone(ISTANBUL_TIMEZONE).hour, run.category): run.state.value
            for run in content_runs
            if not run.slot_key.startswith("test:")
        }
        ready_records = [
            record
            for record in records
            if record.state is NewsState.DRAFTED
            and record.draft_text
            and record.image_path
        ]
        rate_status = (
            rate_gate.status()
            if rate_gate is not None
            else {"last_started_at": None, "next_allowed_at": None}
        )
        provider_status = await ai_providers.status() if ai_providers is not None else None
        if provider_status is not None:
            rate_status = provider_status["rate_status"] or {"last_started_at": None, "next_allowed_at": None}
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "csrf_token": ensure_csrf_token(request),
                "records": records,
                "categories": list(Category),
                "states": list(NewsState),
                "selected_category": category,
                "selected_state": state,
                "queue_count": queue_count,
                "job_counts": job_counts,
                "active_jobs": active_jobs,
                "stats": stats,
                "rate_status": rate_status,
                "latest_batch": latest_batch,
                "publishing_slots": PUBLISHING_SLOTS,
                "next_publishing_slot": next_publishing_slot,
                "run_states": run_states,
                "ready_records": ready_records,
                "state_labels": STATE_LABELS,
                "unsafe_password": settings.admin_password == "1234",
                "ai_provider": provider_status,
                "provider_flash": request.session.pop("provider_flash", None),
            },
        )

    @app.post("/settings/ai-provider")
    async def select_ai_provider(request: Request, provider: str = Form(...), csrf_token: str = Form("")):
        require_admin(request)
        verify_csrf(request, csrf_token)
        if ai_providers is None:
            raise HTTPException(status_code=503, detail="AI sağlayıcı seçimi kullanılamıyor")
        try:
            await ai_providers.select(provider)
            request.session["provider_flash"] = "AI sağlayıcısı kaydedildi. Yeni işler bu sağlayıcıyı kullanacak."
        except ValueError as exc:
            request.session["provider_flash"] = str(exc)
        return RedirectResponse("/", status_code=303)

    @app.post("/collect")
    async def collect(
        request: Request,
        background_tasks: BackgroundTasks,
        csrf_token: str = Form(""),
        category: Optional[str] = Form(None),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        target_category = None
        if category:
            try:
                target_category = Category(category)
            except ValueError:
                pass
        background_tasks.add_task(pipeline.start_collection, target_category)
        return RedirectResponse("/", status_code=303)

    @app.post("/content/test-next-slot")
    async def test_next_slot_content(
        request: Request,
        background_tasks: BackgroundTasks,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        if content_runner is None:
            raise HTTPException(status_code=503, detail="Content runner unavailable")
        slot = next_slot(datetime.now(ISTANBUL_TIMEZONE))
        background_tasks.add_task(content_runner.run_test_slot, slot)
        return RedirectResponse("/", status_code=303)

    @app.get("/news/{news_id}")
    async def news_detail(request: Request, news_id: int):
        require_admin(request)
        try:
            record = await repository.get_news(news_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        return templates.TemplateResponse(
            request=request,
            name="news_detail.html",
            context={
                "csrf_token": ensure_csrf_token(request),
                "record": record,
                "state_labels": STATE_LABELS,
                "unsafe_password": settings.admin_password == "1234",
                "x_enabled": x_publisher is not None,
                "flash": request.session.pop("flash", None),
            },
        )

    @app.get("/news/{news_id}/image")
    async def news_image(news_id: int):
        try:
            record = await repository.get_news(news_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        if not record.image_path or not os.path.exists(record.image_path):
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(record.image_path, media_type="image/png")

    @app.get("/news/{news_id}/blog.md")
    async def download_blog(request: Request, news_id: int, lang: str = "tr"):
        require_admin(request)
        if lang not in {"tr", "en"}:
            raise HTTPException(status_code=400, detail="Blog dili tr veya en olmalı")
        try:
            record = await repository.get_news(news_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        pack = record.platform_texts or {}
        suffix = "_en" if lang == "en" else ""
        if not pack.get("blog_text" + suffix):
            raise HTTPException(status_code=404, detail="Blog henüz üretilmedi")
        body = f"# {pack.get('blog_title' + suffix, '')}\n\n{pack.get('blog_text' + suffix, '')}\n"
        filename = f"haber-{news_id}-en.md" if lang == "en" else f"haber-{news_id}.md"
        return Response(body, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.post("/news/{news_id}/prepare")
    async def prepare(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        selected = await pipeline.prepare_news_candidate(news_id)
        if selected is None:
            raise HTTPException(status_code=409, detail="No safe scored candidate")
        return RedirectResponse(f"/news/{selected.id}", status_code=303)

    @app.post("/news/{news_id}/score")
    async def score_news_item(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        try:
            job = await pipeline.score_candidate(news_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                {"job_id": job.id, "news_id": news_id},
                status_code=202,
            )
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/generate")
    async def generate_content(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        try:
            job = await pipeline.generate_candidate(news_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                {"job_id": job.id, "news_id": news_id},
                status_code=202,
            )
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/regenerate")
    async def regenerate(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        try:
            job = await pipeline.regenerate_candidate(news_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                {"job_id": job.id, "news_id": news_id},
                status_code=202,
            )
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/clear-unready")
    async def clear_unready_news(
        request: Request,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        deleted_count = await pipeline.clear_unready_pool()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                {"deleted_count": deleted_count, "success": True},
                status_code=200,
            )
        return RedirectResponse("/", status_code=303)

    @app.post("/news/clear-all")
    async def clear_all_news(
        request: Request,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        deleted_count = await pipeline.clear_all_pool()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JSONResponse(
                {"deleted_count": deleted_count, "success": True},
                status_code=200,
            )
        return RedirectResponse("/", status_code=303)



    @app.get("/ai-jobs/{job_id}")
    async def ai_job_status(request: Request, job_id: int):
        require_admin(request)
        try:
            job = await repository.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="AI job not found") from exc
        return {
            "id": job.id,
            "news_id": job.news_id,
            "job_type": job.job_type.value,
            "state": job.state.value,
            "error": job.last_error,
        }

    @app.post("/news/{news_id}/approve")
    async def approve(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
        edited_text: Optional[str] = Form(None),
        threads_text: Optional[str] = Form(None),
        instagram_text: Optional[str] = Form(None),
        blog_title: Optional[str] = Form(None),
        blog_description: Optional[str] = Form(None),
        blog_text: Optional[str] = Form(None),
        blog_title_en: Optional[str] = Form(None),
        blog_description_en: Optional[str] = Form(None),
        blog_text_en: Optional[str] = Form(None),
        x_followups: Optional[str] = Form(None),
        threads_followups: Optional[str] = Form(None),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        try:
            platform_texts = None
            if threads_text is not None or instagram_text is not None:
                platform_texts = {"x": edited_text, "threads": threads_text, "instagram": instagram_text}
                existing = (await repository.get_news(news_id)).platform_texts or {}
                for name, value in (("blog_title", blog_title), ("blog_description", blog_description), ("blog_text", blog_text), ("blog_title_en", blog_title_en), ("blog_description_en", blog_description_en), ("blog_text_en", blog_text_en), ("x_followups", x_followups), ("threads_followups", threads_followups)):
                    if value is not None:
                        platform_texts[name] = value
                    elif name in existing:
                        platform_texts[name] = existing[name]
            await pipeline.approve_candidate(news_id, edited_text, platform_texts=platform_texts)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/reject")
    async def reject(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        try:
            next_candidate = await pipeline.reject_candidate(news_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if next_candidate is None:
            return RedirectResponse("/", status_code=303)
        return RedirectResponse(f"/news/{next_candidate.id}", status_code=303)

    @app.post("/news/{news_id}/publish-x")
    async def publish_x(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        if x_publisher is None:
            raise HTTPException(status_code=503, detail="X paylaşımı yapılandırılmamış")
        from x_publisher import XPublishError

        try:
            tweet_id = await x_publisher.publish_news(news_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="News not found") from exc
        except (ValueError, XPublishError) as exc:
            request.session["flash"] = {"kind": "error", "message": str(exc)}
        else:
            request.session["flash"] = {
                "kind": "success",
                "message": f"X'te paylaşıldı (tweet {tweet_id})",
            }
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    return app
