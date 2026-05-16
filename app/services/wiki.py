import datetime as dt
import re
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, Profile, ProfileClaim
from app.services.profile_memory import profile_overview_payload


CATEGORY_TITLES = {
    "project": "Projects",
    "work_experience": "Work Experience",
    "education": "Education",
    "certification": "Certifications",
    "general": "General",
}


def _article_slug(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-").replace("_", "-")
    normalized = re.sub(r"[^a-z0-9-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "article"


def _truncate(text: str, limit: int = 180) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1].rstrip()}..."


def _document_name(claim: ProfileClaim) -> str:
    return (claim.evidence or {}).get("document_filename") or claim.document_id


def _reference_excerpt(claim: ProfileClaim) -> str:
    chunks = (claim.evidence or {}).get("chunks") or []
    if chunks:
        return _truncate(chunks[0].get("text", claim.text), 220)
    return _truncate(claim.text, 220)


def _related(slug: str, title: str, description: str) -> dict:
    return {"slug": slug, "title": title, "description": description}


def _build_references(claims: list[ProfileClaim]) -> tuple[dict[str, str], list[dict]]:
    seen_claim_ids: set[str] = set()
    reference_map: dict[str, str] = {}
    references: list[dict] = []

    for claim in claims:
        if claim.claim_id in seen_claim_ids:
            continue
        label = str(len(references) + 1)
        reference_id = f"ref-{label}"
        reference_map[claim.claim_id] = reference_id
        references.append(
            {
                "id": reference_id,
                "label": label,
                "title": _truncate(claim.text, 110),
                "document": _document_name(claim),
                "excerpt": _reference_excerpt(claim),
                "kind": "approved-claim",
            }
        )
        seen_claim_ids.add(claim.claim_id)

    return reference_map, references


def _claim_bullets(claims: list[ProfileClaim], reference_map: dict[str, str]) -> list[dict]:
    return [
        {
            "text": claim.text,
            "reference_ids": [reference_map[claim.claim_id]] if claim.claim_id in reference_map else [],
        }
        for claim in claims
    ]


def _plain_bullets(items: list[str]) -> list[dict]:
    return [{"text": item, "reference_ids": []} for item in items]


def _structured_bullets(items: list[dict], kind: str) -> list[dict]:
    bullets: list[dict] = []
    for item in items:
        if kind == "work_experience":
            title = item.get("title") or "Role"
            organization = item.get("organization")
            date_text = " - ".join(part for part in (item.get("start_date"), item.get("end_date")) if part)
            summary = item.get("summary")
            text = title
            if organization:
                text = f"{text} at {organization}"
            if date_text:
                text = f"{text} ({date_text})"
            if summary:
                text = f"{text}: {summary}"
        elif kind == "education":
            degree = item.get("degree") or "Education"
            institution = item.get("institution")
            text = degree
            if institution:
                text = f"{text}, {institution}"
            if item.get("field_of_study"):
                text = f"{text} in {item['field_of_study']}"
        elif kind == "projects":
            name = item.get("name") or "Project"
            text = name
            if item.get("summary"):
                text = f"{text}: {item['summary']}"
            if item.get("technologies"):
                text = f"{text} ({', '.join(item['technologies'][:5])})"
        else:
            name = item.get("name") or "Certification"
            issuer = item.get("issuer")
            text = f"{name}, {issuer}" if issuer else name
        bullets.append({"text": text, "reference_ids": []})
    return bullets


def _sorted_article_catalog(articles: list[dict]) -> list[dict]:
    order = {
        "profile": 0,
        "skills": 1,
        "projects": 2,
        "work-experience": 3,
        "education": 4,
        "certifications": 5,
        "general": 6,
    }
    return sorted(articles, key=lambda article: (order.get(article["slug"], 20), article["title"].lower()))


def build_profile_wiki(session: Session, profile_id: str) -> dict:
    profile = session.get(Profile, profile_id)
    overview = profile_overview_payload(profile, profile.user) if profile is not None else None
    claims = list(
        session.scalars(
            select(ProfileClaim)
            .join(Document, ProfileClaim.document_id == Document.id)
            .where(Document.profile_id == profile_id)
            .order_by(ProfileClaim.created_at.desc())
        ).all()
    )
    generated_at = dt.datetime.now(dt.UTC)
    identity = (overview or {}).get("identity", {})
    structured_work = list((overview or {}).get("work_experience", []))
    structured_education = list((overview or {}).get("education", []))
    structured_projects = list((overview or {}).get("projects", []))
    structured_certifications = list((overview or {}).get("certifications", []))
    structured_skills = list((overview or {}).get("skills", []))
    structured_sources = list((overview or {}).get("source_documents", []))
    has_structured_profile = any(
        [
            any(identity.get(field) for field in ("full_name", "headline", "summary", "emails", "phones")),
            structured_work,
            structured_education,
            structured_projects,
            structured_certifications,
            structured_skills,
        ]
    )

    if not claims and not has_structured_profile:
        return {
            "generated_at": generated_at,
            "articles": [
                {
                    "slug": "profile",
                    "title": "Profile",
                    "lede": "No profile data is available yet. Upload evidence to start building the wiki.",
                    "infobox": {
                        "Evidence notes": "0",
                        "Documents": "0",
                    },
                    "sections": [
                        {
                            "id": "overview",
                            "title": "Overview",
                            "paragraphs": [
                                "This wiki is generated from uploaded evidence and the structured profile built from it. It is meant to behave like a source-backed career memory rather than a promotional summary."
                            ],
                            "bullet_items": [],
                        }
                    ],
                    "categories": ["Profile"],
                    "source_documents": [],
                    "references": [],
                    "related_articles": [],
                }
            ],
        }

    skills_counter: Counter[str] = Counter()
    document_counter: Counter[str] = Counter()
    claims_by_category: dict[str, list[ProfileClaim]] = defaultdict(list)
    claims_by_document: dict[str, list[ProfileClaim]] = defaultdict(list)

    for claim in claims:
        claims_by_category[claim.category].append(claim)
        skills_counter.update(claim.skills)
        document_name = _document_name(claim)
        document_counter[document_name] += 1
        claims_by_document[document_name].append(claim)

    articles: list[dict] = []
    top_skills = [skill for skill, _ in skills_counter.most_common(8)]
    top_documents = [document for document, _ in document_counter.most_common(8)]
    top_skill_articles = top_skills[:6]
    if structured_skills:
        for skill in structured_skills:
            if skill not in top_skills:
                top_skills.append(skill)
        top_skills = top_skills[:8]
    if structured_sources:
        structured_document_names = [item["filename"] for item in structured_sources if item.get("filename")]
        for document_name in structured_document_names:
            if document_name not in top_documents:
                top_documents.append(document_name)
        top_documents = top_documents[:8]

    profile_reference_map, profile_references = _build_references(claims[:14])
    profile_sections = [
        {
            "id": "overview",
            "title": "Overview",
            "paragraphs": [
                (
                    f"The current profile contains {len(structured_work)} experience entr{'y' if len(structured_work) == 1 else 'ies'}, "
                    f"{len(structured_projects)} project{'s' if len(structured_projects) != 1 else ''}, and "
                    f"{len(structured_education)} education entr{'y' if len(structured_education) == 1 else 'ies'}. "
                    f"The strongest recurring skills are {', '.join(top_skills[:5]) or 'still being established'}."
                )
            ],
            "bullet_items": [],
        },
        {
            "id": "evidence-notes",
            "title": "Evidence Notes",
            "paragraphs": [
                "The statements below were grounded in uploaded evidence and are kept as reusable notes for later resume generation and job matching."
            ],
            "bullet_items": _claim_bullets(claims[:12], profile_reference_map),
        },
        {
            "id": "skills",
            "title": "Skills",
            "paragraphs": [
                "These skills were inferred from the current profile and its supporting evidence."
            ],
            "bullet_items": _plain_bullets([f"{skill} ({count} evidence note{'s' if count != 1 else ''})" for skill, count in skills_counter.most_common(16)]),
        },
        {
            "id": "sources",
            "title": "Sources",
            "paragraphs": [
                "Each source below contributed evidence to the current profile."
            ],
            "bullet_items": _plain_bullets(
                [f"{document} ({count} evidence note{'s' if count != 1 else ''})" for document, count in document_counter.most_common(16)]
            ),
        },
    ]
    if any(identity.get(field) for field in ("full_name", "headline", "summary", "location", "emails", "phones")):
        identity_bits = []
        if identity.get("headline"):
            identity_bits.append(identity["headline"])
        if identity.get("location"):
            identity_bits.append(identity["location"])
        if identity.get("emails"):
            identity_bits.append(f"Email: {', '.join(identity['emails'])}")
        if identity.get("phones"):
            identity_bits.append(f"Phone: {', '.join(identity['phones'])}")
        profile_sections.insert(
            1,
            {
                "id": "identity",
                "title": "Identity",
                "paragraphs": [identity["summary"]] if identity.get("summary") else [],
                "bullet_items": _plain_bullets(identity_bits),
            },
        )
    if structured_work:
        profile_sections.append(
            {
                "id": "experience",
                "title": "Work Experience",
                "paragraphs": ["These entries were inferred from uploaded evidence and merged into the current profile."],
                "bullet_items": _structured_bullets(structured_work[:8], "work_experience"),
            }
        )
    if structured_projects:
        profile_sections.append(
            {
                "id": "projects",
                "title": "Projects",
                "paragraphs": ["Projects are grouped from evidence that looked like portfolio or implementation work."],
                "bullet_items": _structured_bullets(structured_projects[:8], "projects"),
            }
        )
    if structured_education:
        profile_sections.append(
            {
                "id": "education",
                "title": "Education",
                "paragraphs": ["Academic details extracted from uploaded resumes, CVs, or certificates appear here."],
                "bullet_items": _structured_bullets(structured_education[:8], "education"),
            }
        )
    articles.append(
        {
            "slug": "profile",
            "title": "Profile",
            "lede": (
                f"{identity.get('full_name') or 'This profile'} contains structured profile details derived from uploaded evidence"
                f"{f' plus {len(claims)} evidence-backed note' if len(claims) == 1 else f' plus {len(claims)} evidence-backed notes' if claims else ''}."
                if has_structured_profile
                else (
                    f"The current profile contains {len(claims)} evidence-backed notes across "
                    f"{len(claims_by_category)} categories, with recurring emphasis on {', '.join(top_skills[:4]) or 'verified work'}."
                )
            ),
            "infobox": {
                "Name": identity.get("full_name") or "Not captured yet",
                "Headline": identity.get("headline") or "Not captured yet",
                "Evidence notes": str(len(claims)),
                "Categories": str(len(claims_by_category)),
                "Documents": str(len(top_documents)),
                "Top skills": ", ".join(top_skills[:5]) or "None yet",
            },
            "sections": profile_sections,
            "categories": ["Profile", "Evidence-backed"],
            "source_documents": top_documents,
            "references": profile_references,
            "related_articles": [
                _related("skills", "Skills", "Browse recurring skills inferred from the current profile."),
                *(
                    [_related("work-experience", "Work Experience", "Browse extracted experience entries.")]
                    if structured_work
                    else []
                ),
                *(
                    [_related("education", "Education", "Browse extracted education entries.")]
                    if structured_education
                    else []
                ),
                *(
                    [_related("projects", "Projects", "Browse extracted project entries.")]
                    if structured_projects
                    else []
                ),
                *[
                    _related(_article_slug(category), CATEGORY_TITLES.get(category, category.title()), "View evidence notes by category.")
                    for category in claims_by_category
                ],
            ],
        }
    )

    if structured_work:
        articles.append(
            {
                "slug": "work-experience",
                "title": "Work Experience",
                "lede": "This article lists work entries inferred from uploaded evidence.",
                "infobox": {
                    "Entries": str(len(structured_work)),
                    "Sources": str(
                        len(
                            {
                                source_id
                                for item in structured_work
                                for source_id in item.get("source_document_ids", [])
                            }
                        )
                    ),
                },
                "sections": [
                    {
                        "id": "entries",
                        "title": "Entries",
                        "paragraphs": [],
                        "bullet_items": _structured_bullets(structured_work, "work_experience"),
                    }
                ],
                "categories": ["Work Experience"],
                "source_documents": [item["filename"] for item in structured_sources if item.get("filename")],
                "references": [],
                "related_articles": [_related("profile", "Profile", "Return to the profile overview.")],
            }
        )

    if structured_education:
        articles.append(
            {
                "slug": "education",
                "title": "Education",
                "lede": "This article lists education entries inferred from uploaded evidence.",
                "infobox": {
                    "Entries": str(len(structured_education)),
                },
                "sections": [
                    {
                        "id": "entries",
                        "title": "Entries",
                        "paragraphs": [],
                        "bullet_items": _structured_bullets(structured_education, "education"),
                    }
                ],
                "categories": ["Education"],
                "source_documents": [item["filename"] for item in structured_sources if item.get("filename")],
                "references": [],
                "related_articles": [_related("profile", "Profile", "Return to the profile overview.")],
            }
        )

    if structured_projects:
        articles.append(
            {
                "slug": "projects",
                "title": "Projects",
                "lede": "This article lists project entries inferred from uploaded evidence.",
                "infobox": {
                    "Entries": str(len(structured_projects)),
                },
                "sections": [
                    {
                        "id": "entries",
                        "title": "Entries",
                        "paragraphs": [],
                        "bullet_items": _structured_bullets(structured_projects, "projects"),
                    }
                ],
                "categories": ["Projects"],
                "source_documents": [item["filename"] for item in structured_sources if item.get("filename")],
                "references": [],
                "related_articles": [_related("profile", "Profile", "Return to the profile overview.")],
            }
        )

    skill_overview_sections = []
    skill_page_claims: list[ProfileClaim] = []
    for skill, count in skills_counter.most_common(16):
        matching_claims = [claim for claim in claims if skill in claim.skills][:6]
        skill_page_claims.extend(matching_claims)
        skill_reference_map, _ = _build_references(matching_claims)
        skill_overview_sections.append(
            {
                "id": _article_slug(skill),
                "title": skill,
                "paragraphs": [f"This skill appears in {count} evidence note{'s' if count != 1 else ''}."],
                "bullet_items": _claim_bullets(matching_claims, skill_reference_map),
            }
        )

    skill_page_reference_map, skill_page_references = _build_references(skill_page_claims)
    for section in skill_overview_sections:
        section["bullet_items"] = [
            {
                "text": item["text"],
                "reference_ids": [
                    skill_page_reference_map.get(ref_claim.claim_id)
                    for ref_claim in [next(claim for claim in skill_page_claims if claim.text == item["text"])]
                    if skill_page_reference_map.get(ref_claim.claim_id)
                ],
            }
            for item in section["bullet_items"]
        ]

    if skills_counter:
        articles.append(
            {
                "slug": "skills",
                "title": "Skills",
                "lede": "This article lists the strongest recurring skills found across the current profile and its evidence notes.",
                "infobox": {
                    "Tracked skills": str(len(skills_counter)),
                    "Most frequent": top_skills[0] if top_skills else "None yet",
                    "Skill articles": str(len(top_skill_articles)),
                },
                "sections": skill_overview_sections,
                "categories": ["Skills"],
                "source_documents": top_documents,
                "references": skill_page_references,
                "related_articles": [
                    _related("profile", "Profile", "Return to the master overview article."),
                    *[
                        _related(f"skill-{_article_slug(skill)}", skill, "Open the dedicated skill article.")
                        for skill in top_skill_articles
                    ],
                ],
            }
        )

    for skill in top_skill_articles:
        matching_claims = [claim for claim in claims if skill in claim.skills][:10]
        skill_reference_map, skill_references = _build_references(matching_claims)
        skill_documents = sorted({_document_name(claim) for claim in matching_claims})
        categories_for_skill = Counter(claim.category for claim in matching_claims)
        articles.append(
            {
                "slug": f"skill-{_article_slug(skill)}",
                "title": skill,
                "lede": f"{skill} is a recurring skill across the current profile and its supporting evidence.",
                "infobox": {
                    "Evidence notes": str(len(matching_claims)),
                    "Source documents": str(len(skill_documents)),
                    "Common categories": ", ".join(
                        CATEGORY_TITLES.get(category, category.replace("_", " ").title())
                        for category, _ in categories_for_skill.most_common(3)
                    ) or "Not classified",
                },
                "sections": [
                    {
                        "id": "overview",
                        "title": "Overview",
                        "paragraphs": [
                            f"The current profile currently links {skill} to {len(matching_claims)} evidence note{'s' if len(matching_claims) != 1 else ''}."
                        ],
                        "bullet_items": [],
                    },
                    {
                        "id": "evidence-notes",
                        "title": "Evidence Notes",
                        "paragraphs": [
                            "The following evidence notes explicitly mention or strongly imply this skill."
                        ],
                        "bullet_items": _claim_bullets(matching_claims, skill_reference_map),
                    },
                ],
                "categories": ["Skills", "Evidence notes"],
                "source_documents": skill_documents,
                "references": skill_references,
                "related_articles": [
                    _related("skills", "Skills", "Return to the aggregated skills article."),
                    _related("profile", "Profile", "Return to the master profile article."),
                ],
            }
        )

    for category, category_claims in sorted(
        claims_by_category.items(),
        key=lambda item: CATEGORY_TITLES.get(item[0], item[0]),
    ):
        title = CATEGORY_TITLES.get(category, category.replace("_", " ").title())
        article_documents = sorted({_document_name(claim) for claim in category_claims})
        category_skills = Counter(skill for claim in category_claims for skill in claim.skills)
        category_reference_map, category_references = _build_references(category_claims[:12])
        articles.append(
            {
                "slug": _article_slug(category),
                "title": title,
                "lede": f"This article collects evidence-backed notes classified under {title.lower()}.",
                "infobox": {
                    "Evidence notes": str(len(category_claims)),
                    "Source documents": str(len(article_documents)),
                    "Common skills": ", ".join(skill for skill, _ in category_skills.most_common(4)) or "Not tagged",
                },
                "sections": [
                    {
                        "id": "overview",
                        "title": "Overview",
                        "paragraphs": [
                            f"This topic groups evidence notes that were categorized as {title.lower()} during ingestion."
                        ],
                        "bullet_items": [],
                    },
                    {
                        "id": "evidence-notes",
                        "title": "Evidence Notes",
                        "paragraphs": [
                            "The following statements were retained from supporting evidence."
                        ],
                        "bullet_items": _claim_bullets(category_claims[:12], category_reference_map),
                    },
                ],
                "categories": [title, "Evidence notes"],
                "source_documents": article_documents,
                "references": category_references,
                "related_articles": [
                    _related("profile", "Profile", "Return to the profile overview."),
                    _related("skills", "Skills", "Review the recurring skills article."),
                ],
            }
        )

    for document_name, document_claims in sorted(claims_by_document.items(), key=lambda item: item[0].lower()):
        document_reference_map, document_references = _build_references(document_claims[:12])
        document_skills = Counter(skill for claim in document_claims for skill in claim.skills)
        articles.append(
            {
                "slug": f"source-{_article_slug(document_name)}",
                "title": document_name,
                "lede": f"This article lists evidence-backed notes grounded in the source document {document_name}.",
                "infobox": {
                    "Evidence notes": str(len(document_claims)),
                    "Common skills": ", ".join(skill for skill, _ in document_skills.most_common(4)) or "Not tagged",
                },
                "sections": [
                    {
                        "id": "overview",
                        "title": "Overview",
                        "paragraphs": [
                            "Source-document pages are useful when you want to audit exactly what one file contributed to the profile."
                        ],
                        "bullet_items": [],
                    },
                    {
                        "id": "supported-notes",
                        "title": "Supported Notes",
                        "paragraphs": [
                            "These evidence notes were grounded in this source document."
                        ],
                        "bullet_items": _claim_bullets(document_claims[:12], document_reference_map),
                    },
                ],
                "categories": ["Sources", "Evidence notes"],
                "source_documents": [document_name],
                "references": document_references,
                "related_articles": [
                    _related("profile", "Profile", "Return to the profile overview."),
                    *[
                        _related(_article_slug(category), CATEGORY_TITLES.get(category, category.title()), "Jump to the relevant category article.")
                        for category in unique_categories(document_claims)
                    ],
                ],
            }
        )

    return {
        "generated_at": generated_at,
        "articles": _sorted_article_catalog(articles),
    }


def unique_categories(claims: list[ProfileClaim]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for claim in claims:
        if claim.category in seen:
            continue
        ordered.append(claim.category)
        seen.add(claim.category)
    return ordered
