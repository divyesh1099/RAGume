import asyncio
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app


async def register_and_create_profile(
    client: httpx.AsyncClient,
    *,
    full_name: str = "Divyesh Vishwakarma",
    email: str = "divyesh@example.com",
    password: str = "supersecure123",
    profile_name: str = "Primary Profile",
) -> dict:
    register_response = await client.post(
        "/auth/register",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
        },
    )
    assert register_response.status_code == 200
    assert register_response.json()["user"]["email"] == email

    session_response = await client.get("/auth/session")
    assert session_response.status_code == 200
    assert session_response.json()["user"]["full_name"] == full_name

    profile_response = await client.post("/profiles", json={"name": profile_name})
    assert profile_response.status_code == 200
    return profile_response.json()


def test_auth_pages_and_auto_profile_flow(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            uploads_dir=str(tmp_path / "uploads"),
            enable_llm_extractor=False,
            enable_embedding_retrieval=False,
            enable_resume_ner=False,
            enable_resume_gpt_formatter=False,
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for route in ("/login", "/register", "/profiles/select", "/", "/job", "/wiki", "/profile"):
                response = await client.get(route)
                assert response.status_code == 200
                assert "text/html" in response.headers["content-type"]

            unauthorized_profiles = await client.get("/profiles")
            assert unauthorized_profiles.status_code == 401

            profile = await register_and_create_profile(client)
            profile_id = profile["id"]

            parser_response = await client.get("/resume-parsers")
            assert parser_response.status_code == 200
            parser_payload = parser_response.json()
            assert any(item["id"] == "layout_ner" for item in parser_payload)

            jd_parse_response = await client.post(
                "/job-description/parse",
                files={"file": ("job.txt", "Looking for a Python engineer with OCR and RAG experience.", "text/plain")},
            )
            assert jd_parse_response.status_code == 200
            jd_payload = jd_parse_response.json()
            assert jd_payload["filename"] == "job.txt"
            assert "Python engineer" in jd_payload["text"]
            assert jd_payload["parse_metadata"]["parser"] == "plain_text"

            resume_text = """
            Divyesh Vishwakarma
            Document AI Engineer | Bengaluru, India
            divyesh@example.com | +91 98765 43210 | https://linkedin.com/in/divyesh | https://github.com/divyesh

            SUMMARY
            Backend and document AI engineer building OCR, RAG, and workflow automation systems.

            SKILLS
            Python, Fast API, OCR, Redis, LayoutLMv3, Docker, postgres, RAG

            WORK EXPERIENCE
            Document AI Engineer | Neuralit | Jan 2023 - Present | Bengaluru, India
            Built OCR and LayoutLMv3 workflows for 12,000+ pages and reduced manual review time by 40%.
            Built FastAPI services with Redis workers for document ingestion and classification.

            EDUCATION
            Bachelor of Technology in Computer Science
            XYZ University
            2019 - 2023

            PROJECTS
            FastPDF Pipeline
            Built a page-level PDF processing pipeline using Python, Redis, OCR, and LayoutLMv3.
            https://github.com/divyesh/fastpdf-pipeline
            """

            upload_response = await client.post(
                "/documents/upload",
                data={"profile_id": profile_id, "parser_backend": "auto"},
                files={"file": ("resume.txt", resume_text, "text/plain")},
            )
            assert upload_response.status_code == 200
            upload_payload = upload_response.json()
            document_id = upload_payload["document"]["id"]
            assert upload_payload["document"]["profile_id"] == profile_id
            assert upload_payload["document"]["parse_metadata"]["profile_parser_backend"] == "layout_ner"
            assert upload_payload["chunks_created"] >= 1
            assert "identity" in upload_payload["auto_profile_sections"]
            assert "work_experience" in upload_payload["auto_profile_sections"]
            assert "education" in upload_payload["auto_profile_sections"]
            assert "projects" in upload_payload["auto_profile_sections"]

            parser_compare_response = await client.get(f"/documents/{document_id}/parser-comparisons?profile_id={profile_id}")
            assert parser_compare_response.status_code == 200
            parser_compare_payload = parser_compare_response.json()
            assert parser_compare_payload["document_id"] == document_id
            assert parser_compare_payload["active_backend"] == "layout_ner"
            assert any(item["backend"] == "layout_ner" for item in parser_compare_payload["comparisons"])

            reparse_response = await client.post(
                f"/documents/{document_id}/reparse?profile_id={profile_id}&parser_backend=auto"
            )
            assert reparse_response.status_code == 200
            reparse_payload = reparse_response.json()
            assert reparse_payload["document"]["parse_metadata"]["profile_parser_backend"] == "layout_ner"

            studio_review_response = await client.get(f"/profile/studio/review?profile_id={profile_id}")
            assert studio_review_response.status_code == 200
            studio_review = studio_review_response.json()
            assert studio_review["profile_id"] == profile_id
            assert studio_review["claims_total"] >= 6
            assert any(section["section"] == "identity" and section["claims"] for section in studio_review["sections"])
            assert any(section["section"] == "work_experience" and section["claims"] for section in studio_review["sections"])
            assert studio_review["extracted_profile"]["profile_mode"] == "auto"
            assert studio_review["review_preview_profile"]["profile_mode"] == "review"
            assert len(studio_review["review_preview_profile"]["work_experience"]) >= 1
            assert studio_review["correction_summary"]["auto_corrected"] >= 2
            assert studio_review["diagnostics"]["correction"]["embedding_retrieval_enabled"] is False
            assert len(studio_review["diagnostics"]["parser_sources"]) == 1
            assert any("github.com/divyesh" == link["url"].removeprefix("https://").removeprefix("http://") for link in studio_review["review_preview_profile"]["public_profiles"])
            assert all("fastpdf-pipeline" not in link["url"] for link in studio_review["review_preview_profile"]["public_profiles"])
            assert any(
                any("fastpdf-pipeline" in link for link in project.get("links", []))
                for project in studio_review["review_preview_profile"]["projects"]
            )

            skill_section_initial = next(section for section in studio_review["sections"] if section["section"] == "skills")
            postgres_claim = next(claim for claim in skill_section_initial["claims"] if claim["raw_value_json"].get("name") == "postgres")
            fastapi_claim = next(claim for claim in skill_section_initial["claims"] if claim["raw_value_json"].get("name") == "Fast API")
            assert postgres_claim["value_json"]["name"] == "PostgreSQL"
            assert postgres_claim["resolver_action"] == "auto_correct"
            assert fastapi_claim["value_json"]["name"] == "FastAPI"
            assert fastapi_claim["resolver_action"] == "auto_correct"
            assert "PostgreSQL" in studio_review["review_preview_profile"]["skills"]
            assert "FastAPI" in studio_review["review_preview_profile"]["skills"]

            identity_section = next(section for section in studio_review["sections"] if section["section"] == "identity")
            editable_identity_claim = next(claim for claim in identity_section["claims"] if claim["field_name"] == "headline")
            studio_edit_response = await client.patch(
                f"/profile/studio/claims/{editable_identity_claim['id']}?profile_id={profile_id}",
                json={
                    "status": "edited",
                    "section": "identity",
                    "value_json": {"value": "Principal Document AI Engineer"},
                },
            )
            assert studio_edit_response.status_code == 200
            assert studio_edit_response.json()["status"] == "edited"
            assert studio_edit_response.json()["value_json"]["value"] == "Principal Document AI Engineer"

            studio_review_after_edit = await client.get(f"/profile/studio/review?profile_id={profile_id}")
            assert studio_review_after_edit.status_code == 200
            identity_section_after_edit = next(
                section for section in studio_review_after_edit.json()["sections"] if section["section"] == "identity"
            )
            persisted_identity_claim = next(
                claim for claim in identity_section_after_edit["claims"] if claim["id"] == editable_identity_claim["id"]
            )
            assert persisted_identity_claim["status"] == "edited"
            assert persisted_identity_claim["value_json"]["value"] == "Principal Document AI Engineer"
            assert studio_review_after_edit.json()["review_preview_profile"]["identity"]["headline"] == "Principal Document AI Engineer"

            skill_section = next(section for section in studio_review_after_edit.json()["sections"] if section["section"] == "skills")
            rejected_skill_claim = next(claim for claim in skill_section["claims"] if claim["value_json"]["name"] == "PostgreSQL")
            reject_skill_response = await client.patch(
                f"/profile/studio/claims/{rejected_skill_claim['id']}?profile_id={profile_id}",
                json={"status": "rejected", "section": "skills"},
            )
            assert reject_skill_response.status_code == 200

            studio_review_after_reject = await client.get(f"/profile/studio/review?profile_id={profile_id}")
            assert studio_review_after_reject.status_code == 200
            assert "PostgreSQL" not in studio_review_after_reject.json()["review_preview_profile"]["skills"]

            accept_all_response = await client.post(f"/profile/studio/claims/accept-all?profile_id={profile_id}")
            assert accept_all_response.status_code == 200
            assert accept_all_response.json()["updated"] >= 1

            save_profile_response = await client.post(f"/profile/studio/save?profile_id={profile_id}")
            assert save_profile_response.status_code == 200
            saved_profile = save_profile_response.json()
            assert saved_profile["profile_mode"] == "canonical"
            assert saved_profile["identity"]["full_name"] == "Divyesh Vishwakarma"
            assert len(saved_profile["work_experience"]) >= 1

            overview_response = await client.get(f"/profile/overview?profile_id={profile_id}")
            assert overview_response.status_code == 200
            overview = overview_response.json()
            assert overview["profile_id"] == profile_id
            assert overview["profile_mode"] == "canonical"
            assert overview["identity"]["full_name"] == "Divyesh Vishwakarma"
            assert "divyesh@example.com" in overview["identity"]["emails"]
            assert any("98765" in phone for phone in overview["identity"]["phones"])
            assert overview["identity"]["headline"] is not None
            assert any("linkedin.com" in link["url"] for link in overview["public_profiles"])
            assert any("github.com" in link["url"] for link in overview["public_profiles"])
            assert all("fastpdf-pipeline" not in link["url"] for link in overview["public_profiles"])
            assert any(skill.lower() == "python" for skill in overview["skills"])
            assert len(overview["work_experience"]) >= 1
            assert len(overview["education"]) >= 1
            assert len(overview["projects"]) >= 1
            assert any(
                any("fastpdf-pipeline" in link for link in project.get("links", []))
                for project in overview["projects"]
            )
            assert overview["documents_total"] == 1
            assert overview["source_documents"][0]["document_id"] == document_id

            profiles_response = await client.get("/profiles")
            assert profiles_response.status_code == 200
            profiles_payload = profiles_response.json()
            summary_row = next(item for item in profiles_payload if item["id"] == profile_id)
            assert summary_row["headline"] is not None
            assert summary_row["document_count"] == 1
            assert summary_row["skills_total"] >= 1
            assert summary_row["sections_ready"] >= 4

            profile_patch_response = await client.patch(
                f"/profile/overview?profile_id={profile_id}",
                json={
                    "identity": {
                        "headline": "Senior Document AI Engineer",
                        "summary": "Manual override summary.",
                    },
                    "skills": ["Python", "OCR", "FastAPI"],
                    "public_profiles": [{"label": "Portfolio", "url": "https://example.com"}],
                },
            )
            assert profile_patch_response.status_code == 200
            patched_overview = profile_patch_response.json()
            assert patched_overview["identity"]["headline"] == "Senior Document AI Engineer"
            assert patched_overview["identity"]["summary"] == "Manual override summary."
            assert patched_overview["skills"] == ["Python", "OCR", "FastAPI"]
            assert patched_overview["public_profiles"] == [{"label": "Portfolio", "url": "https://example.com"}]

            reset_response = await client.delete(f"/profile/overview/manual?profile_id={profile_id}")
            assert reset_response.status_code == 200
            reset_overview = reset_response.json()
            assert reset_overview["identity"]["headline"] != "Senior Document AI Engineer"
            assert any("linkedin.com" in link["url"] for link in reset_overview["public_profiles"])

            clear_canonical_response = await client.delete(f"/profile/studio/canonical?profile_id={profile_id}")
            assert clear_canonical_response.status_code == 200
            assert clear_canonical_response.json()["profile_mode"] == "auto"

            wiki_response = await client.get(f"/profile/wiki?profile_id={profile_id}")
            assert wiki_response.status_code == 200
            wiki_payload = wiki_response.json()
            profile_article = next(article for article in wiki_payload["articles"] if article["slug"] == "profile")
            assert "uploaded evidence" in profile_article["lede"].lower() or "evidence-backed" in profile_article["lede"].lower()
            section_titles = [section["title"] for section in profile_article["sections"]]
            assert "Work Experience" in section_titles
            assert "Projects" in section_titles

            delete_document_response = await client.delete(f"/documents/{document_id}?profile_id={profile_id}")
            assert delete_document_response.status_code == 200

            summary_after_delete = await client.get(f"/dashboard/summary?profile_id={profile_id}")
            assert summary_after_delete.status_code == 200
            assert summary_after_delete.json()["documents_total"] == 0

            overview_after_delete = await client.get(f"/profile/overview?profile_id={profile_id}")
            assert overview_after_delete.status_code == 200
            cleaned = overview_after_delete.json()
            assert cleaned["documents_total"] == 0
            assert cleaned["work_experience"] == []
            assert cleaned["education"] == []
            assert cleaned["projects"] == []
            assert cleaned["source_documents"] == []

    asyncio.run(scenario())


def test_profile_selection_and_isolation_flow(tmp_path: Path) -> None:
    async def scenario() -> None:
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            uploads_dir=str(tmp_path / "uploads"),
            enable_llm_extractor=False,
            enable_embedding_retrieval=False,
            enable_resume_ner=False,
            enable_resume_gpt_formatter=False,
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            primary_profile = await register_and_create_profile(
                client,
                email="owner@example.com",
                profile_name="Document AI Profile",
            )
            second_profile_response = await client.post("/profiles", json={"name": "Platform Profile"})
            assert second_profile_response.status_code == 200
            second_profile = second_profile_response.json()

            first_upload = await client.post(
                "/documents/upload",
                data={"profile_id": primary_profile["id"]},
                files={
                    "file": (
                        "doc-ai.txt",
                        """
                        Divyesh Vishwakarma
                        OCR Engineer
                        divyesh@example.com

                        WORK EXPERIENCE
                        OCR Engineer | Neuralit | 2023 - Present
                        Built OCR and LayoutLMv3 workflows for 12,000 pages.

                        PROJECTS
                        FastPDF Pipeline
                        Built document classification workflows with OCR and Redis.
                        """,
                        "text/plain",
                    )
                },
            )
            assert first_upload.status_code == 200
            first_document_id = first_upload.json()["document"]["id"]

            second_upload = await client.post(
                "/documents/upload",
                data={"profile_id": second_profile["id"]},
                files={
                    "file": (
                        "backend.txt",
                        """
                        Divyesh Vishwakarma
                        Backend Engineer

                        WORK EXPERIENCE
                        Backend Engineer | Internal Tools | 2022 - Present
                        Built FastAPI services with PostgreSQL and Docker for internal automation tools.

                        PROJECTS
                        Platform Toolkit
                        Built Docker-based internal services with FastAPI and PostgreSQL.
                        """,
                        "text/plain",
                    )
                },
            )
            assert second_upload.status_code == 200
            second_document_id = second_upload.json()["document"]["id"]

            first_overview = (await client.get(f"/profile/overview?profile_id={primary_profile['id']}")).json()
            second_overview = (await client.get(f"/profile/overview?profile_id={second_profile['id']}")).json()

            first_skills = {skill.lower() for skill in first_overview["skills"]}
            second_skills = {skill.lower() for skill in second_overview["skills"]}
            assert "ocr" in first_skills or "layoutlmv3" in first_skills
            assert "fastapi" not in first_skills
            assert "fastapi" in second_skills
            assert "ocr" not in second_skills

            first_documents = (await client.get(f"/documents?profile_id={primary_profile['id']}")).json()
            second_documents = (await client.get(f"/documents?profile_id={second_profile['id']}")).json()
            assert [document["id"] for document in first_documents] == [first_document_id]
            assert [document["id"] for document in second_documents] == [second_document_id]

            first_wiki = (await client.get(f"/profile/wiki?profile_id={primary_profile['id']}")).json()
            second_wiki = (await client.get(f"/profile/wiki?profile_id={second_profile['id']}")).json()
            first_profile_article = next(article for article in first_wiki["articles"] if article["slug"] == "profile")
            second_profile_article = next(article for article in second_wiki["articles"] if article["slug"] == "profile")
            first_text = " ".join(
                bullet["text"]
                for section in first_profile_article["sections"]
                for bullet in section.get("bullet_items", [])
            ).lower()
            second_text = " ".join(
                bullet["text"]
                for section in second_profile_article["sections"]
                for bullet in section.get("bullet_items", [])
            ).lower()
            assert "ocr" in first_text or "layoutlmv3" in first_text
            assert "fastapi" not in first_text
            assert "fastapi" in second_text
            assert "layoutlmv3" not in second_text

            rename_response = await client.patch(
                f"/profiles/{second_profile['id']}",
                json={"name": "Backend Platform Profile"},
            )
            assert rename_response.status_code == 200
            assert rename_response.json()["name"] == "Backend Platform Profile"

            delete_second_profile = await client.delete(f"/profiles/{second_profile['id']}")
            assert delete_second_profile.status_code == 200

            remaining_profiles = (await client.get("/profiles")).json()
            assert [profile["name"] for profile in remaining_profiles] == [primary_profile["name"]]

            delete_last_profile = await client.delete(f"/profiles/{primary_profile['id']}")
            assert delete_last_profile.status_code == 409

    asyncio.run(scenario())
