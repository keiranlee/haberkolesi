from types import SimpleNamespace
import re

from fastapi.testclient import TestClient

from app import create_app
from repositories import MemoryRepository


class StubPipeline:
    async def start_collection(self):
        return 0


def make_client():
    settings = SimpleNamespace(
        admin_password="1234",
        session_secret="test-secret-with-enough-length",
        cookie_secure=False,
    )
    return TestClient(create_app(settings, MemoryRepository(), StubPipeline()))


def csrf_from(html):
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def test_dashboard_redirects_anonymous_user():
    with make_client() as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_accepts_only_configured_password():
    with make_client() as client:
        denied = client.post(
            "/login", data={"password": "wrong"}, follow_redirects=False
        )
        accepted = client.post(
            "/login", data={"password": "1234"}, follow_redirects=False
        )

    assert denied.status_code == 401
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/"


def test_logout_removes_admin_session():
    with make_client() as client:
        client.post("/login", data={"password": "1234"})
        csrf_token = csrf_from(client.get("/").text)
        response = client.post(
            "/logout",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        dashboard = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert dashboard.status_code == 303
