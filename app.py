"""FastAPI application factory for the Devosuit news review panel."""

from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import ensure_csrf_token, require_admin, verify_csrf, verify_password
from domain import Category, NewsState


BASE_DIR = Path(__file__).resolve().parent


def create_app(settings, repository, pipeline) -> FastAPI:
    app = FastAPI(title="Devosuit Haber Paneli")
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
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
        records = await repository.list_news(category=category, state=state)
        queue_count = await repository.count_jobs()
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
                "unsafe_password": settings.admin_password == "1234",
            },
        )

    @app.post("/collect")
    async def collect(
        request: Request,
        background_tasks: BackgroundTasks,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        background_tasks.add_task(pipeline.start_collection)
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
                "unsafe_password": settings.admin_password == "1234",
            },
        )

    @app.post("/news/{news_id}/prepare")
    async def prepare(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        await pipeline.regenerate_candidate(news_id)
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/regenerate")
    async def regenerate(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        await pipeline.regenerate_candidate(news_id)
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/approve")
    async def approve(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
        edited_text: Optional[str] = Form(None),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        await pipeline.approve_candidate(news_id, edited_text)
        return RedirectResponse(f"/news/{news_id}", status_code=303)

    @app.post("/news/{news_id}/reject")
    async def reject(
        request: Request,
        news_id: int,
        csrf_token: str = Form(""),
    ):
        require_admin(request)
        verify_csrf(request, csrf_token)
        next_candidate = await pipeline.reject_candidate(news_id)
        if next_candidate is None:
            return RedirectResponse("/", status_code=303)
        return RedirectResponse(f"/news/{next_candidate.id}", status_code=303)

    return app
