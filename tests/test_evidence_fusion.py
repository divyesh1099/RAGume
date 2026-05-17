from pathlib import Path

from app.config import Settings
from app.db import init_db, init_engine, session_scope
from app.models import Document, Profile, StructuredProfileClaim, User
from app.services import evidence_fusion


def _create_profile_fixture(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'fusion-unit.db'}",
        uploads_dir=str(tmp_path / "uploads"),
        enable_embedding_retrieval=False,
    )
    init_engine(settings.database_url)
    init_db()
    with session_scope() as session:
        user = User(full_name="Divyesh Vishwakarma", email="fusion-unit@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        profile = Profile(user_id=user.id, name="Fusion Test", profile_data={})
        session.add(profile)
        session.flush()
        document = Document(
            profile_id=profile.id,
            filename="resume.txt",
            storage_path=str(tmp_path / "resume.txt"),
            source_type="upload",
            mime_type="text/plain",
            checksum="checksum",
            extracted_text="resume text",
            parse_metadata={"profile_validation": {"score": 86}},
        )
        session.add(document)
        session.flush()
        session.commit()
        return settings, user.id, profile.id, document.id


def _add_structured_claim(
    session,
    *,
    profile_id: str,
    document_id: str,
    section: str,
    field_name: str,
    value_json: dict,
    status: str = "accepted",
    position: int = 0,
) -> StructuredProfileClaim:
    claim = StructuredProfileClaim(
        profile_id=profile_id,
        document_id=document_id,
        section=section,
        field_name=field_name,
        raw_value_json=dict(value_json),
        value_json=dict(value_json),
        value_text=str(value_json),
        normalized_value=f"{section}:{field_name}:{position}",
        source_text=str(value_json),
        source_page=1,
        source_bbox={},
        parser_name="test",
        confidence=0.86,
        resolver_confidence=0.9,
        resolver_action="keep",
        resolver_evidence=[],
        admission_status="admit",
        admission_reason="fixture",
        admission_score=1.0,
        suggested_section=None,
        status=status,
        position=position,
    )
    session.add(claim)
    session.flush()
    return claim


def test_fusion_detects_duplicate_url_format_and_project_inside_experience(tmp_path: Path) -> None:
    settings, user_id, profile_id, document_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        user = session.get(User, user_id)
        profile = session.get(Profile, profile_id)
        assert user is not None
        assert profile is not None

        _add_structured_claim(
            session,
            profile_id=profile_id,
            document_id=document_id,
            section="public_profiles",
            field_name="link",
            value_json={"label": "LinkedIn", "url": "linkedin.com/in/divyesh-vishwakarma"},
            position=1,
        )
        _add_structured_claim(
            session,
            profile_id=profile_id,
            document_id=document_id,
            section="public_profiles",
            field_name="link",
            value_json={"label": "LinkedIn", "url": "https://www.linkedin.com/in/divyesh-vishwakarma/"},
            position=2,
        )
        _add_structured_claim(
            session,
            profile_id=profile_id,
            document_id=document_id,
            section="work_experience",
            field_name="entry",
            value_json={
                "title": "FastPDF Pipeline",
                "organization": "",
                "location": "",
                "start_date": "",
                "end_date": "",
                "summary": "Open source OCR pipeline for PDF processing.",
                "highlights": [],
                "technologies": ["Python", "OCR"],
                "links": ["https://github.com/divyesh/fastpdf-pipeline"],
                "source_document_ids": [document_id],
            },
            position=3,
        )
        session.commit()

        fusion = evidence_fusion.fuse_profile(session, profile, user, settings=settings)

    anomaly_types = {item["anomaly_type"] for item in fusion["anomalies"]}
    review_reasons = {item["review_reason"] for item in fusion["review_groups"]}

    assert "duplicate_url_different_format" in anomaly_types
    assert "project_inside_experience" in anomaly_types
    assert "project_inside_experience" in review_reasons
    assert len(fusion["preview_profile"]["public_profiles"]) == 1


def test_dedupe_claims_does_not_use_semantic_only_similarity_for_projects(tmp_path: Path, monkeypatch) -> None:
    settings, _user_id, profile_id, _document_id = _create_profile_fixture(tmp_path)
    settings.enable_embedding_retrieval = True

    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        assert profile is not None

        first = evidence_fusion.ClaimGroup(
            profile_id=profile_id,
            group_type="project",
            canonical_key="project:resume-customizer",
            canonical_value="Resume Customizer",
            canonical_value_json={"name": "Resume Customizer", "summary": "Tailors resumes for jobs.", "links": []},
            confidence=0.93,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-1"],
            group_metadata={"source_count": 1, "source_document_ids": ["doc-1"]},
        )
        second = evidence_fusion.ClaimGroup(
            profile_id=profile_id,
            group_type="project",
            canonical_key="project:career-memory-engine",
            canonical_value="Career Memory Engine",
            canonical_value_json={"name": "Career Memory Engine", "summary": "Tailors resumes for jobs.", "links": []},
            confidence=0.81,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-2"],
            group_metadata={"source_count": 1, "source_document_ids": ["doc-2"]},
        )
        session.add_all([first, second])
        session.flush()

        monkeypatch.setattr(evidence_fusion, "correction_embedding_available", lambda _settings: True)
        monkeypatch.setattr(
            evidence_fusion,
            "ensure_correction_embeddings",
            lambda *args, **kwargs: (
                [
                    [1.0, 0.0],
                    [0.99, 0.01],
                ],
                {"hits": 2, "misses": 0},
            ),
        )

        groups, anomalies = evidence_fusion.dedupe_claims(session, profile, [first, second], settings=settings)

    ignored_groups = [group for group in groups if group.status == "ignored"]
    review_groups = [group for group in groups if group.status == "review"]
    assert ignored_groups == []
    assert review_groups == []
    assert anomalies == []


def test_dedupe_claims_handles_unflushed_groups_without_ids(tmp_path: Path) -> None:
    settings, _user_id, profile_id, _document_id = _create_profile_fixture(tmp_path)

    with session_scope() as session:
        profile = session.get(Profile, profile_id)
        assert profile is not None

        first = evidence_fusion.ClaimGroup(
            profile_id=profile_id,
            group_type="skill",
            canonical_key="skill:fastapi",
            canonical_value="FastAPI",
            canonical_value_json={"name": "FastAPI"},
            confidence=0.94,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-1"],
            group_metadata={"source_count": 1, "source_document_ids": ["doc-1"]},
        )
        second = evidence_fusion.ClaimGroup(
            profile_id=profile_id,
            group_type="skill",
            canonical_key="skill:fastapi-copy",
            canonical_value="FastAPI",
            canonical_value_json={"name": "FastAPI"},
            confidence=0.82,
            merge_action="merged",
            status="merged",
            claim_ids_json=["claim-2"],
            group_metadata={"source_count": 1, "source_document_ids": ["doc-2"]},
        )

        assert first.id is None
        assert second.id is None

        groups, anomalies = evidence_fusion.dedupe_claims(session, profile, [first, second], settings=settings)

    ignored_groups = [group for group in groups if group.status == "ignored"]
    merged_groups = [group for group in groups if group.status != "ignored"]
    assert len(ignored_groups) == 1
    assert ignored_groups[0].canonical_key == "skill:fastapi-copy"
    assert merged_groups[0].group_metadata["merged_duplicate_group_ids"] == ["skill:fastapi-copy"]
    assert anomalies == []
