"""FastAPI application factory for the Devosuit news review panel."""

from typing import Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from auth import ensure_csrf_token, require_admin, verify_csrf, verify_password
from domain import Category, NewsState


def create_app(settings, repository, pipeline) -> FastAPI:
    app = FastAPI(title="Devosuit Haber Paneli")
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
    async def login_page():
        return "<form method='post'><input name='password' type='password'></form>"

    @app.post("/login")
    async def login(request: Request, password: str = Form(...)):
        if not verify_password(password, settings.admin_password):
            return HTMLResponse("Geçersiz parola", status_code=401)
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
        return JSONResponse(
            {
                "csrf_token": ensure_csrf_token(request),
                "news": [
                    {
                        "id": record.id,
                        "title": record.raw.title,
                        "category": (
                            record.ai_category or record.raw.source_category
                        ).value,
                        "score": record.score,
                        "state": record.state.value,
                    }
                    for record in records
                ],
            }
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
        return JSONResponse(
            {
                "csrf_token": ensure_csrf_token(request),
                "id": record.id,
                "title": record.raw.title,
                "source_url": record.raw.url,
                "content": record.raw.content,
                "category": (
                    record.ai_category or record.raw.source_category
                ).value,
                "score": record.score,
                "reason": record.score_reason,
                "key_facts": record.key_facts or [],
                "risk_flags": record.risk_flags or [],
                "draft_text": record.draft_text,
                "state": record.state.value,
            }
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
