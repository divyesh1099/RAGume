import asyncio
import csv
import json
from pathlib import Path

import httpx

from app.config import Settings
from app.main import create_app
from app.services.benchmarking import benchmark_dataset_summary, load_latest_benchmark_report, run_resume_benchmark


def _write_benchmark_dataset(base_dir: Path) -> Path:
    dataset_dir = base_dir / "benchmark-dataset"
    sample_dir = dataset_dir / "sample_pdfs"
    sample_dir.mkdir(parents=True, exist_ok=True)

    resume_one = sample_dir / "ENGINEERING__1001.txt"
    resume_one.write_text(
        """
        DIVYESH VISHWAKARMA
        Senior Python / ML Engineer | Mumbai, India
        divyesh1099@gmail.com | +91 9920192856 | https://linkedin.com/in/divyesh-vishwakarma | https://github.com/divyesh1099

        SUMMARY
        AI engineer building OCR, RAG, and backend automation systems.

        SKILLS
        Python, FastAPI, OCR, Docker, Redis, PostgreSQL, RAG

        WORK EXPERIENCE
        Senior Python / ML Engineer | Neural IT Pvt Ltd | Apr 2024 - Present | Mumbai, India
        Built FastAPI, OCR, and RAG systems for document AI workflows.

        EDUCATION
        B.Tech. Computer Engineering
        Bharati Vidyapeeth College of Engineering
        2018 - 2022

        PROJECTS
        RAGume
        Evidence-backed resume generation workspace.
        https://github.com/divyesh1099/ragume
        """.strip(),
        encoding="utf-8",
    )

    resume_two = sample_dir / "DESIGNER__1002.txt"
    resume_two.write_text(
        """
        PRIYA SHARMA
        Product Designer | Bengaluru, India
        priyasharma@example.com | +91 9876543210 | https://www.linkedin.com/in/priya-sharma | https://priyasharma.design

        SUMMARY
        Product designer focused on design systems, user research, and web experiences.

        SKILLS
        Figma, Adobe XD, Design Systems, CSS, HTML, User Research

        WORK EXPERIENCE
        Product Designer | Pixel Labs | Jan 2023 - Present | Bengaluru, India
        Led UI redesigns and built component libraries in Figma.

        EDUCATION
        Bachelor of Design
        NIFT Bengaluru
        2018 - 2022

        PROJECTS
        Design Sprint Kit
        Figma starter kit for workshop facilitation.
        https://www.figma.com/community/file/123456
        """.strip(),
        encoding="utf-8",
    )

    with (dataset_dir / "sample_pdf_manifest.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["resume_id", "category", "source_pdf_path", "local_pdf_name", "local_pdf_path"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "resume_id": "1001",
                "category": "ENGINEERING",
                "source_pdf_path": "",
                "local_pdf_name": resume_one.name,
                "local_pdf_path": str(resume_one),
            }
        )
        writer.writerow(
            {
                "resume_id": "1002",
                "category": "DESIGNER",
                "source_pdf_path": "",
                "local_pdf_name": resume_two.name,
                "local_pdf_path": str(resume_two),
            }
        )

    with (dataset_dir / "gold_annotation_template.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "resume_id",
                "category",
                "local_pdf_name",
                "gold_name",
                "gold_email",
                "gold_phone",
                "gold_location",
                "gold_links_json",
                "gold_summary",
                "gold_skills_json",
                "gold_experience_json",
                "gold_education_json",
                "gold_projects_json",
                "gold_certifications_json",
                "gold_achievements_json",
                "review_status",
                "reviewer_notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "resume_id": "1001",
                "category": "ENGINEERING",
                "local_pdf_name": resume_one.name,
                "gold_name": "DIVYESH VISHWAKARMA",
                "gold_email": "divyesh1099@gmail.com",
                "gold_phone": "+91 9920192856",
                "gold_location": "Mumbai, India",
                "gold_links_json": json.dumps(
                    [
                        {"label": "LinkedIn", "url": "https://linkedin.com/in/divyesh-vishwakarma"},
                        {"label": "GitHub", "url": "https://github.com/divyesh1099"},
                    ]
                ),
                "gold_summary": "AI engineer building OCR, RAG, and backend automation systems.",
                "gold_skills_json": json.dumps(["Python", "FastAPI", "OCR", "Docker", "Redis", "PostgreSQL", "RAG"]),
                "gold_experience_json": json.dumps(
                    [
                        {
                            "title": "Senior Python / ML Engineer",
                            "organization": "Neural IT Pvt Ltd",
                            "location": "Mumbai, India",
                            "start_date": "Apr 2024",
                            "end_date": "Present",
                            "bullets": [],
                        }
                    ]
                ),
                "gold_education_json": json.dumps(
                    [
                        {
                            "degree": "B.Tech. Computer Engineering",
                            "institution": "Bharati Vidyapeeth College of Engineering",
                            "location": "",
                            "start_date": "2018",
                            "end_date": "2022",
                            "gpa_or_score": "",
                        }
                    ]
                ),
                "gold_projects_json": json.dumps(
                    [
                        {
                            "name": "RAGume",
                            "summary": "Evidence-backed resume generation workspace.",
                            "technologies": ["Python", "FastAPI"],
                            "links": ["https://github.com/divyesh1099/ragume"],
                        }
                    ]
                ),
                "gold_certifications_json": "[]",
                "gold_achievements_json": "[]",
                "review_status": "partial_review",
                "reviewer_notes": "fixture",
            }
        )
        writer.writerow(
            {
                "resume_id": "1002",
                "category": "DESIGNER",
                "local_pdf_name": resume_two.name,
                "gold_name": "PRIYA SHARMA",
                "gold_email": "priyasharma@example.com",
                "gold_phone": "+91 9876543210",
                "gold_location": "Bengaluru, India",
                "gold_links_json": json.dumps(
                    [
                        {"label": "LinkedIn", "url": "https://www.linkedin.com/in/priya-sharma"},
                        {"label": "Portfolio", "url": "https://priyasharma.design"},
                    ]
                ),
                "gold_summary": "Product designer focused on design systems, user research, and web experiences.",
                "gold_skills_json": json.dumps(["Figma", "Adobe XD", "Design Systems", "CSS", "HTML", "User Research"]),
                "gold_experience_json": json.dumps(
                    [
                        {
                            "title": "Product Designer",
                            "organization": "Pixel Labs",
                            "location": "Bengaluru, India",
                            "start_date": "Jan 2023",
                            "end_date": "Present",
                            "bullets": [],
                        }
                    ]
                ),
                "gold_education_json": json.dumps(
                    [
                        {
                            "degree": "Bachelor of Design",
                            "institution": "NIFT Bengaluru",
                            "location": "",
                            "start_date": "2018",
                            "end_date": "2022",
                            "gpa_or_score": "",
                        }
                    ]
                ),
                "gold_projects_json": json.dumps(
                    [
                        {
                            "name": "Design Sprint Kit",
                            "summary": "Figma starter kit for workshop facilitation.",
                            "technologies": ["Figma"],
                            "links": ["https://www.figma.com/community/file/123456"],
                        }
                    ]
                ),
                "gold_certifications_json": "[]",
                "gold_achievements_json": "[]",
                "review_status": "partial_review",
                "reviewer_notes": "fixture",
            }
        )

    return dataset_dir


def test_benchmark_runner_scores_fixture_dataset_and_saves_report(tmp_path: Path) -> None:
    dataset_dir = _write_benchmark_dataset(tmp_path)
    settings = Settings(
        benchmark_dataset_dir=str(dataset_dir),
        benchmark_reports_dir=str(tmp_path / "reports"),
        database_url=f"sqlite:///{tmp_path / 'bench.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        benchmark_default_limit=10,
        enable_llm_extractor=False,
        enable_embedding_retrieval=False,
        enable_resume_ner=False,
        enable_resume_gpt_formatter=False,
    )

    summary = benchmark_dataset_summary(settings)
    assert summary["available"] is True
    assert summary["total_cases"] == 2
    assert summary["field_coverage"]["skills"] == 2

    report = run_resume_benchmark(settings, parser_backend="auto", limit=2)
    assert report["processed_cases"] == 2
    assert report["success_cases"] == 2
    assert report["failed_cases"] == 0
    assert report["overall_score"] is not None
    assert Path(report["saved_report_path"]).exists()
    assert any(metric["field"] == "skills" and metric["scored_cases"] == 2 for metric in report["field_metrics"])
    assert any(case["status"] == "ok" and case["field_scores"] for case in report["cases"])

    latest = load_latest_benchmark_report(settings)
    assert latest is not None
    assert latest["processed_cases"] == 2
    assert latest["saved_report_path"] == report["saved_report_path"]


def test_benchmark_routes_and_latest_report(tmp_path: Path) -> None:
    async def scenario() -> None:
        dataset_dir = _write_benchmark_dataset(tmp_path)
        settings = Settings(
            benchmark_dataset_dir=str(dataset_dir),
            benchmark_reports_dir=str(tmp_path / "reports"),
            database_url=f"sqlite:///{tmp_path / 'bench-routes.db'}",
            uploads_dir=str(tmp_path / "uploads"),
            benchmark_default_limit=10,
            enable_llm_extractor=False,
            enable_embedding_retrieval=False,
            enable_resume_ner=False,
            enable_resume_gpt_formatter=False,
        )
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page_response = await client.get("/benchmarks")
            assert page_response.status_code == 200
            assert "text/html" in page_response.headers["content-type"]

            unauthorized = await client.get("/benchmark/dataset")
            assert unauthorized.status_code == 401

            register_response = await client.post(
                "/auth/register",
                json={
                    "full_name": "Benchmark User",
                    "email": "bench@example.com",
                    "password": "supersecure123",
                },
            )
            assert register_response.status_code == 200

            dataset_response = await client.get("/benchmark/dataset")
            assert dataset_response.status_code == 200
            dataset_payload = dataset_response.json()
            assert dataset_payload["available"] is True
            assert dataset_payload["total_cases"] == 2

            run_response = await client.post(
                "/benchmark/run",
                json={
                    "parser_backend": "auto",
                    "limit": 2,
                    "allow_remote_models": False,
                },
            )
            assert run_response.status_code == 200
            run_payload = run_response.json()
            assert run_payload["processed_cases"] == 2
            assert run_payload["success_cases"] == 2

            latest_response = await client.get("/benchmark/latest")
            assert latest_response.status_code == 200
            latest_payload = latest_response.json()
            assert latest_payload["saved_report_path"] == run_payload["saved_report_path"]

    asyncio.run(scenario())


def test_real_dataset_benchmark_smoke_if_available(tmp_path: Path) -> None:
    dataset_dir = Path("/home/divyesh-nandlal-vishwakarma/Downloads/ragume_benchmark_gold_v0")
    if not dataset_dir.exists():
        return

    settings = Settings(
        benchmark_dataset_dir=str(dataset_dir),
        benchmark_reports_dir=str(tmp_path / "reports"),
        database_url=f"sqlite:///{tmp_path / 'real-bench.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        benchmark_default_limit=2,
        enable_llm_extractor=False,
        enable_embedding_retrieval=False,
        enable_resume_gpt_formatter=False,
    )

    report = run_resume_benchmark(settings, parser_backend="auto", limit=2, allow_remote_models=False)
    assert report["processed_cases"] == 2
    assert report["success_cases"] + report["failed_cases"] == 2
    assert any(metric["field"] == "skills" and metric["scored_cases"] > 0 for metric in report["field_metrics"])
