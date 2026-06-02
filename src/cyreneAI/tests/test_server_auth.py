from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.server import create_app
from cyreneAI.server.config import ServerSettings, build_server_settings_from_env


class AuthFakeProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_RESPONSES,
        name="fake",
        description="Fake provider.",
        models=[],
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_RESPONSES,
    )

    async def close(self) -> None:
        pass


def _client(settings: ServerSettings) -> TestClient:
    async def build_runtime() -> CyreneAIRuntime:
        provider = AuthFakeProvider()
        factory = ProviderFactory()

        async def build_provider(config: ProviderConfig) -> AuthFakeProvider:
            return provider

        factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
        manager = ProviderManager(factory)
        await manager.add(provider.config)
        return CyreneAIRuntime(
            provider_manager=manager,
            context_builder=ContextWindowBuilder(),
        )

    return TestClient(create_app(asyncio.run(build_runtime()), settings=settings))


def test_health_does_not_require_admin_auth() -> None:
    response = _client(ServerSettings()).get("/health")

    assert response.status_code == 200


def test_readiness_does_not_require_admin_auth() -> None:
    client = _client(ServerSettings())

    with client:
        response = client.get("/ready")

    assert response.status_code == 200


def test_admin_route_rejects_missing_auth_config() -> None:
    response = _client(ServerSettings()).get(
        "/providers",
        auth=("admin", "secret"),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Admin auth is not configured"


def test_admin_route_rejects_missing_credentials() -> None:
    response = _client(
        ServerSettings(admin_username="admin", admin_password="secret")
    ).get("/providers")

    assert response.status_code == 401


def test_admin_route_rejects_invalid_credentials() -> None:
    response = _client(
        ServerSettings(admin_username="admin", admin_password="secret")
    ).get(
        "/providers",
        auth=("admin", "wrong"),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid admin credentials"


def test_admin_route_accepts_valid_credentials() -> None:
    response = _client(
        ServerSettings(admin_username="admin", admin_password="secret")
    ).get(
        "/providers",
        auth=("admin", "secret"),
    )

    assert response.status_code == 200
    assert response.json()["providers"][0]["name"] == "fake"


def test_login_form_sets_session_cookie() -> None:
    client = _client(ServerSettings(admin_username="admin", admin_password="secret"))

    login = client.post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "secret",
        },
    )
    providers = client.get("/providers")

    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert "cyrene_admin_session" in client.cookies
    assert providers.status_code == 200


def test_login_form_rejects_invalid_password() -> None:
    response = _client(
        ServerSettings(admin_username="admin", admin_password="secret")
    ).post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "wrong",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid admin credentials"


def test_logout_clears_session_cookie() -> None:
    client = _client(ServerSettings(admin_username="admin", admin_password="secret"))
    client.post(
        "/auth/login",
        data={
            "username": "admin",
            "password": "secret",
        },
    )

    logout = client.post("/auth/logout")
    providers = client.get("/providers")

    assert logout.status_code == 200
    assert logout.json() == {"authenticated": False}
    assert providers.status_code == 401


def test_invalid_session_cookie_falls_back_to_basic_auth() -> None:
    client = _client(ServerSettings(admin_username="admin", admin_password="secret"))
    client.cookies.set("cyrene_admin_session", "invalid")

    rejected = client.get("/providers")
    accepted = client.get("/providers", auth=("admin", "secret"))

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_server_settings_reads_admin_auth_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("CYRENEAI_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("CYRENEAI_AUTH_ENABLED", "false")
    monkeypatch.setenv("CYRENEAI_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("CYRENEAI_SESSION_COOKIE_NAME", "custom_session")
    monkeypatch.setenv("CYRENEAI_SESSION_TTL_SECONDS", "60")

    settings = build_server_settings_from_env()

    assert settings.admin_username == "admin"
    assert settings.admin_password == "secret"
    assert settings.auth_enabled is False
    assert settings.session_secret == "session-secret"
    assert settings.session_cookie_name == "custom_session"
    assert settings.session_ttl_seconds == 60
