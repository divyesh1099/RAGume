from pathlib import Path

from app.config import Settings
from app.db import init_db, init_engine, session_scope
from app.models import ClaimGroup, Document, Profile, StructuredProfileClaim, User
from app.services.claim_admission import evaluate_claim_admission
from app.services.evidence_fusion import build_canonical_profile, dedupe_claims
from app.services.profile_compiler import compile_profile_views
from app.services.profile_memory import _normalize_overview_data


def _create_profile_fixture(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'claim-admission.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        enable_embedding_retrieval=False,
    )
    init_engine(settings.database_url)
    init_db()
    with session_scope() as session:
        user = User(full_name="Divyesh Vishwakarma", email="compiler-unit@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        profile = Profile(user_id=user.id, name="Compiler Test", profile_data={})
        session.add(profile)
        session.flush()
        current_doc = Document(
            profile_id=profile.id,
            filename="latest_ai_resume.pdf",
            storage_path=str(tmp_path / "latest_ai_resume.pdf"),
            source_type="upload",
            mime_type="application/pdf",
            checksum="current-doc",
            extracted_text="resume",
            parse_metadata={"document_role": "latest_ai_resume", "profile_focus": "ai_ml", "source_quality": 0.97},
        )
        web_doc = Document(
            profile_id=profile.id,
            filename="asp_react_resume.pdf",
            storage_path=str(tmp_path / "asp_react_resume.pdf"),
            source_type="upload",
            mime_type="application/pdf",
            checksum="web-doc",
            extracted_text="resume",
            parse_metadata={"document_role": "asp_react_resume", "profile_focus": "web_dev", "source_quality": 0.9},
        )
        session.add_all([current_doc, web_doc])
        session.flush()
        session.commit()
        return settings, user.id, profile.id, current_doc.id, web_doc.id


def _make_claim(
    *,
    profile_id: str,
    document_id: str,
    section: str,
    field_name: str,
    value_json: dict,
) -> StructuredProfileClaim:
    return StructuredProfileClaim(
        profile_id=profile_id,
        document_id=document_id,
        section=section,
        field_name=field_name,
        raw_value_json=dict(value_json),
        value_json=dict(value_json),
        value_text=str(value_json),
        normalized_value="normalized",
        source_text=str(value_json),
        source_page=1,
        source_bbox={},
        parser_name="test",
        confidence=0.82,
        resolver_confidence=0.84,
        resolver_action="keep",
        resolver_evidence=[],
        admission_status="needs_review",
        admission_reason=None,
        admission_score=0.0,
        suggested_section=None,
        status="pending",
        position=0,
    )


def test_claim_admission_rejects_skill_noise_and_project_fragments(tmp_path: Path) -> None:
    _settings, _user_id, profile_id, current_doc_id, _web_doc_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        assert profile is not None

        noisy_skill = _make_claim(
            profile_id=profile_id,
            document_id=current_doc_id,
            section="skills",
            field_name="skill",
            value_json={"name": "/CD"},
        )
        short_real_skill = _make_claim(
            profile_id=profile_id,
            document_id=current_doc_id,
            section="skills",
            field_name="skill",
            value_json={"name": "C#"},
        )
        fragment_project = _make_claim(
            profile_id=profile_id,
            document_id=current_doc_id,
            section="projects",
            field_name="entry",
            value_json={"name": "app that auto", "summary": "", "technologies": [], "links": []},
        )

        noisy_skill_decision = evaluate_claim_admission(session, profile, noisy_skill, peer_claims=[noisy_skill])
        short_skill_decision = evaluate_claim_admission(session, profile, short_real_skill, peer_claims=[short_real_skill])
        fragment_project_decision = evaluate_claim_admission(session, profile, fragment_project, peer_claims=[fragment_project])

    assert noisy_skill_decision.status == "reject_noise"
    assert short_skill_decision.status == "admit"
    assert fragment_project_decision.status == "reject_noise"


def test_claim_admission_keeps_real_taxonomy_skills_and_rejects_bullet_summary(tmp_path: Path) -> None:
    _settings, _user_id, profile_id, current_doc_id, _web_doc_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        assert profile is not None

        real_skills = ["NumPy", "Pandas", "RoBERTa", "Terraform", "MongoDB", "RabbitMQ", "XGBoost"]
        decisions = []
        for skill in real_skills:
            claim = _make_claim(
                profile_id=profile_id,
                document_id=current_doc_id,
                section="skills",
                field_name="skill",
                value_json={"name": skill},
            )
            decisions.append(evaluate_claim_admission(session, profile, claim, peer_claims=[claim]))

        summary_claim = _make_claim(
            profile_id=profile_id,
            document_id=current_doc_id,
            section="identity",
            field_name="summary",
            value_json={"value": "Worked on Angular components and optimized SQL queries for internal portals."},
        )
        summary_decision = evaluate_claim_admission(session, profile, summary_claim, peer_claims=[summary_claim])

    assert all(decision.status == "admit" for decision in decisions)
    assert summary_decision.status == "reject_noise"
    assert summary_decision.reason == "summary_misclassified_experience"


def test_profile_compiler_separates_current_position_from_target_headline_and_views(tmp_path: Path) -> None:
    _settings, user_id, _profile_id, current_doc_id, web_doc_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        user = session.get(User, user_id)
        current_doc = session.get(Document, current_doc_id)
        web_doc = session.get(Document, web_doc_id)
        assert user is not None and current_doc is not None and web_doc is not None

        master = _normalize_overview_data(
            {
                "identity": {
                    "full_name": "DIVYESH VISHWAKARMA",
                    "headline": "Software Developer · Zeus Learning",
                    "summary": "General profile summary.",
                },
                "skills": [
                    "Python",
                    "FastAPI",
                    "RAG",
                    "OCR",
                    "BERT",
                    "NumPy",
                    "Redis",
                    "Docker",
                    "JavaScript",
                    "TypeScript",
                    "Angular",
                    "React",
                    "ASP.NET",
                    "Django",
                    "SQL",
                ],
                "work_experience": [
                    {
                        "title": "Senior Python Developer",
                        "organization": "Neural IT Pvt. Ltd.",
                        "start_date": "Apr 2024",
                        "end_date": "Present",
                        "summary": "Built RAG, OCR, and FastAPI systems.",
                        "technologies": ["Python", "FastAPI", "RAG", "OCR", "Redis", "Docker"],
                        "highlights": [],
                        "links": [],
                        "source_document_ids": [current_doc_id],
                    },
                    {
                        "title": "Software Developer",
                        "organization": "Zeus Learning",
                        "start_date": "2022",
                        "end_date": "2024",
                        "summary": "Built Angular and ASP.NET products.",
                        "technologies": ["Angular", "ASP.NET", "React", "SQL", "Django"],
                        "highlights": [],
                        "links": [],
                        "source_document_ids": [web_doc_id],
                    },
                ],
                "projects": [
                    {"name": "Bertify", "summary": "LLM and RAG assistant", "technologies": ["Python", "RAG", "BERT"], "links": []},
                    {"name": "Bulky Books", "summary": "Angular and ASP.NET app", "technologies": ["Angular", "ASP.NET", "SQL"], "links": []},
                    {"name": "Dumphy", "summary": "React storefront", "technologies": ["React", "JavaScript"], "links": []},
                ],
                "public_profiles": [{"label": "GitHub", "url": "https://github.com/divyesh1099"}],
                "education": [],
                "certifications": [],
                "profile_focus": "web_dev",
                "mode_summaries": {
                    "ai_ml": "AI summary.",
                    "web_dev": "Web summary.",
                    "master": "Master summary.",
                },
                "source_documents": [],
            }
        )

        groups = [
            ClaimGroup(
                profile_id="profile",
                group_type="work_experience",
                canonical_key="work:neural-it",
                canonical_value="Senior Python Developer · Neural IT Pvt. Ltd.",
                canonical_value_json=master["work_experience"][0],
                confidence=0.96,
                merge_action="merged",
                status="merged",
                claim_ids_json=["claim-1"],
                group_metadata={"source_document_ids": [current_doc_id]},
            ),
            ClaimGroup(
                profile_id="profile",
                group_type="work_experience",
                canonical_key="work:zeus-learning",
                canonical_value="Software Developer · Zeus Learning",
                canonical_value_json=master["work_experience"][1],
                confidence=0.88,
                merge_action="merged",
                status="merged",
                claim_ids_json=["claim-2"],
                group_metadata={"source_document_ids": [web_doc_id]},
            ),
        ]

        compiled = compile_profile_views(master, groups, {current_doc_id: current_doc, web_doc_id: web_doc}, user)

    assert compiled["ai_ml"]["identity"]["current_position"] == "Senior Python Developer · Neural IT Pvt. Ltd."
    assert compiled["web_dev"]["identity"]["headline"] != "Software Developer · Zeus Learning"
    assert "Angular" in compiled["web_dev"]["skills"]
    assert "React" in compiled["web_dev"]["skills"]
    assert "ASP.NET" in compiled["web_dev"]["skills"]
    assert "Python" in compiled["ai_ml"]["skills"]
    assert "FastAPI" in compiled["ai_ml"]["skills"]
    assert "RAG" in compiled["ai_ml"]["skills"]
    assert "NumPy" in compiled["master"]["skills"]
    assert compiled["web_dev"]["identity"]["summary"] == "Web summary."
    assert compiled["ai_ml"]["identity"]["summary"] == "AI summary."


def test_experience_different_organizations_and_dates_are_not_deduped(tmp_path: Path) -> None:
    settings, _user_id, profile_id, _current_doc_id, _web_doc_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        assert profile is not None

        first = ClaimGroup(
            profile_id=profile_id,
            group_type="work_experience",
            canonical_key="work:neural-it:2024",
            canonical_value="Senior Python Developer · Neural IT Pvt. Ltd.",
            canonical_value_json={
                "title": "Senior Python Developer",
                "organization": "Neural IT Pvt. Ltd.",
                "start_date": "Apr 2024",
                "end_date": "Present",
                "summary": "Built RAG systems.",
            },
            confidence=0.96,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-1"],
            group_metadata={"source_document_ids": ["doc-current"]},
        )
        second = ClaimGroup(
            profile_id=profile_id,
            group_type="work_experience",
            canonical_key="work:zeus:2022",
            canonical_value="Software Developer · Zeus Learning",
            canonical_value_json={
                "title": "Software Developer",
                "organization": "Zeus Learning",
                "start_date": "2022",
                "end_date": "2024",
                "summary": "Built Angular apps.",
            },
            confidence=0.88,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-2"],
            group_metadata={"source_document_ids": ["doc-web"]},
        )

        groups, anomalies = dedupe_claims(session, profile, [first, second], settings=settings)

    assert all(group.status == "merged" for group in groups)
    assert anomalies == []


def test_identity_summary_beats_experience_bullet_for_mode_summary(tmp_path: Path) -> None:
    _settings, user_id, profile_id, current_doc_id, _web_doc_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        user = session.get(User, user_id)
        profile = session.get(Profile, profile_id)
        current_doc = session.get(Document, current_doc_id)
        assert user is not None and profile is not None and current_doc is not None

        groups = [
            ClaimGroup(
                profile_id=profile_id,
                group_type="identity",
                canonical_key="identity:summary",
                canonical_value="AI summary",
                canonical_value_json={
                    "value": "GenAI-oriented Python Engineer with 3.5 years of shipping AI production and cloud back-ends. Highlights include OCR, RAG, FastAPI, and production LLM systems."
                },
                confidence=0.94,
                merge_action="merged",
                status="merged",
                claim_ids_json=["summary-1"],
                group_metadata={"field_name": "summary", "source_document_ids": [current_doc_id]},
            ),
            ClaimGroup(
                profile_id=profile_id,
                group_type="work_experience",
                canonical_key="work:pal-india",
                canonical_value="Machine Learning Developer · Pal India",
                canonical_value_json={
                    "organization": "Pal India",
                    "title": "Machine Learning Developer",
                    "start_date": "May 2023",
                    "end_date": "Feb 2024",
                    "summary": "Hybrid ARIMA plus HOLT-TSB engine cut stock-out penalties and introduced REST plus gRPC services for secure deployments.",
                    "technologies": ["Python", "gRPC"],
                    "highlights": [],
                    "links": [],
                },
                confidence=0.98,
                merge_action="merged",
                status="merged",
                claim_ids_json=["work-1"],
                group_metadata={"source_document_ids": [current_doc_id]},
            ),
        ]

        canonical = build_canonical_profile(profile, groups, user, {current_doc_id: current_doc})

    assert canonical["mode_summaries"]["ai_ml"].startswith("GenAI-oriented Python Engineer")
    assert canonical["identity"]["summary"].startswith("GenAI-oriented Python Engineer")
