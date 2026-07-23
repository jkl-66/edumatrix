"""Shared authenticated TestClient helpers for API regression tests."""

from fastapi.testclient import TestClient


TEST_PASSWORD = "EduMatrix123!"


def auth_headers(client: TestClient, username: str) -> dict[str, str]:
    """Create or reuse a test student and return a JWT Authorization header."""
    register = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": TEST_PASSWORD,
            "display_name": f"测试用户 {username}",
        },
    )
    login = client.post(
        "/api/auth/login",
        data={"username": username, "password": TEST_PASSWORD},
    )
    if login.status_code != 200:
        raise AssertionError(
            f"test account setup failed: register={register.status_code} {register.text}; "
            f"login={login.status_code} {login.text}"
        )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
