import asyncio
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app


def test_production_health_secure_cookie_and_trusted_hosts(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
            uploads_dir=str(tmp_path / "uploads"),
            benchmark_reports_dir=str(tmp_path / "reports"),
            enable_llm_extractor=False,
            enable_embedding_retrieval=False,
            enable_resume_ner=False,
            enable_resume_gpt_formatter=False,
            app_env="production",
            public_base_url="https://resume.example.com",
            allowed_hosts="resume.example.com,testserver",
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="https://resume.example.com") as client:
            health_response = await client.get("/health")
            assert health_response.status_code == 200
            assert "x-request-id" in health_response.headers
            health_payload = health_response.json()
            assert health_payload["status"] == "ok"
            assert health_payload["environment"] == "production"
            assert health_payload["session_cookie_secure"] is True
            assert health_payload["ready_status"] == "ready"

            ready_response = await client.get("/health/ready")
            assert ready_response.status_code == 200
            ready_payload = ready_response.json()
            assert ready_payload["status"] == "ready"
            assert ready_payload["checks"]["database"] == "ok"
            assert ready_payload["checks"]["uploads_dir"] == "ok"
            assert ready_payload["checks"]["benchmark_reports_dir"] == "ok"

            live_response = await client.get("/health/live")
            assert live_response.status_code == 200
            assert live_response.json()["status"] == "ok"

            register_response = await client.post(
                "/auth/register",
                json={
                    "full_name": "Divyesh Vishwakarma",
                    "email": "divyesh.runtime@example.com",
                    "password": "supersecure123",
                },
            )
            assert register_response.status_code == 200
            set_cookie = register_response.headers["set-cookie"]
            assert "Secure" in set_cookie
            assert "HttpOnly" in set_cookie
            assert "SameSite=lax" in set_cookie

            session_response = await client.get("/auth/session")
            assert session_response.status_code == 200
            assert session_response.json()["user"]["email"] == "divyesh.runtime@example.com"

        async with httpx.AsyncClient(transport=transport, base_url="https://unexpected.example.com") as client:
            blocked_response = await client.get("/health")
            assert blocked_response.status_code == 400

    asyncio.run(scenario())


def test_upload_limit_returns_request_too_large(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'limit.db'}",
            uploads_dir=str(tmp_path / "uploads"),
            benchmark_reports_dir=str(tmp_path / "reports"),
            enable_llm_extractor=False,
            enable_embedding_retrieval=False,
            enable_resume_ner=False,
            enable_resume_gpt_formatter=False,
            max_upload_size_mb=1,
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            register_response = await client.post(
                "/auth/register",
                json={
                    "full_name": "Divyesh Vishwakarma",
                    "email": "divyesh.limit@example.com",
                    "password": "supersecure123",
                },
            )
            assert register_response.status_code == 200

            oversized_text = "Machine learning platform.\n" * 60_000
            response = await client.post(
                "/job-description/parse",
                files={"file": ("job.txt", oversized_text, "text/plain")},
            )
            assert response.status_code == 413
            assert "upload limit" in response.json()["detail"]
            assert "x-request-id" in response.headers

    asyncio.run(scenario())
