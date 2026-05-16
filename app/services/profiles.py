import datetime as dt
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Claim, Document, Profile, ProfileClaim, ProfileGraphEdge, ProfileGraphNode, User
from app.services.documents import delete_document_evidence
from app.services.profile_memory import profile_overview_payload

def normalize_profile_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Profile name cannot be empty.")
    if len(cleaned) > 120:
        raise HTTPException(status_code=422, detail="Profile name must be 120 characters or fewer.")
    return cleaned


def get_default_profile(session: Session, user: User) -> Profile | None:
    return session.scalar(
        select(Profile)
        .where(Profile.user_id == user.id)
        .order_by(Profile.created_at.asc(), Profile.name.asc())
    )


def resolve_profile(session: Session, user: User, profile_id: str | None = None) -> Profile:
    if profile_id:
        profile = session.get(Profile, profile_id)
        if profile is None or profile.user_id != user.id:
            raise HTTPException(status_code=404, detail="Profile not found.")
        return profile
    profile = get_default_profile(session, user)
    if profile is None:
        raise HTTPException(status_code=404, detail="No profiles available for this account yet.")
    return profile


def ensure_unique_profile_name(
    session: Session,
    user: User,
    profile_name: str,
    exclude_profile_id: str | None = None,
) -> None:
    existing = list(
        session.scalars(
            select(Profile)
            .where(Profile.user_id == user.id, func.lower(Profile.name) == profile_name.lower())
        ).all()
    )
    for profile in existing:
        if exclude_profile_id and profile.id == exclude_profile_id:
            continue
        raise HTTPException(status_code=409, detail="A profile with that name already exists.")


def create_profile(session: Session, user: User, name: str) -> Profile:
    normalized_name = normalize_profile_name(name)
    ensure_unique_profile_name(session, user, normalized_name)
    profile = Profile(name=normalized_name, user_id=user.id)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def rename_profile(session: Session, user: User, profile: Profile, name: str) -> Profile:
    normalized_name = normalize_profile_name(name)
    ensure_unique_profile_name(session, user, normalized_name, exclude_profile_id=profile.id)
    profile.name = normalized_name
    profile.updated_at = dt.datetime.now(dt.UTC)
    session.commit()
    session.refresh(profile)
    return profile


def delete_profile(session: Session, user: User, profile: Profile, uploads_dir: str) -> str:
    profile_count = session.scalar(select(func.count(Profile.id)).where(Profile.user_id == user.id)) or 0
    if profile_count <= 1:
        raise HTTPException(status_code=409, detail="At least one profile must remain in the workspace.")

    documents = list(
        session.scalars(
            select(Document)
            .where(Document.profile_id == profile.id)
            .order_by(Document.created_at.desc())
        ).all()
    )

    for document in documents:
        delete_document_evidence(session, document)

    session.execute(delete(ProfileGraphEdge).where(ProfileGraphEdge.profile_id == profile.id))
    session.execute(delete(ProfileGraphNode).where(ProfileGraphNode.profile_id == profile.id))
    session.delete(profile)
    session.flush()

    profile_upload_dir = Path(uploads_dir) / profile.id
    return str(profile_upload_dir)


def build_profile_summaries_for_user(session: Session, user: User) -> list[dict]:
    profiles = list(
        session.scalars(
            select(Profile)
            .where(Profile.user_id == user.id)
            .order_by(Profile.updated_at.desc(), Profile.created_at.asc())
        ).all()
    )
    if not profiles:
        return []

    document_counts = dict(
        session.execute(
            select(Document.profile_id, func.count(Document.id))
            .join(Profile, Document.profile_id == Profile.id)
            .where(Profile.user_id == user.id)
            .group_by(Document.profile_id)
        ).all()
    )
    pending_counts = dict(
        session.execute(
            select(Document.profile_id, func.count(Claim.id))
            .join(Claim, Claim.document_id == Document.id)
            .join(Profile, Document.profile_id == Profile.id)
            .where(Profile.user_id == user.id, Claim.status == "pending")
            .group_by(Document.profile_id)
        ).all()
    )
    approved_counts = dict(
        session.execute(
            select(Document.profile_id, func.count(ProfileClaim.id))
            .join(ProfileClaim, ProfileClaim.document_id == Document.id)
            .join(Profile, Document.profile_id == Profile.id)
            .where(Profile.user_id == user.id)
            .group_by(Document.profile_id)
        ).all()
    )

    summaries: list[dict] = []
    for profile in profiles:
        overview = profile_overview_payload(profile, user)
        sections_ready = sum(
            1
            for available in (
                any(overview["identity"].get(field) for field in ("full_name", "headline", "summary", "emails", "phones")),
                bool(overview["skills"]),
                bool(overview["work_experience"]),
                bool(overview["education"]),
                bool(overview["projects"]),
                bool(overview["certifications"]),
            )
            if available
        )
        summaries.append(
            {
                "id": profile.id,
                "name": profile.name,
                "headline": overview["identity"].get("headline"),
                "document_count": int(document_counts.get(profile.id, 0)),
                "pending_claim_count": int(pending_counts.get(profile.id, 0)),
                "approved_claim_count": int(approved_counts.get(profile.id, 0)),
                "skills_total": len(overview["skills"]),
                "work_experience_total": len(overview["work_experience"]),
                "education_total": len(overview["education"]),
                "projects_total": len(overview["projects"]),
                "sections_ready": sections_ready,
                "created_at": profile.created_at,
                "updated_at": profile.updated_at,
            }
        )
    return summaries
