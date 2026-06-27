"""Resume and CV text generation from profile_data."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models import Profile


def _auto(profile_data: dict) -> dict:
    return (profile_data or {}).get("auto") or {}


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def _date_sort_key(entry: dict) -> str:
    end = (entry.get("end_date") or "").strip().lower()
    start = (entry.get("start_date") or "").strip()
    if end in ("present", "current", "now", ""):
        year = re.search(r"\d{4}", start)
        return f"9999-{year.group() if year else '0000'}"
    year_match = re.search(r"\d{4}", end)
    if not year_match:
        return "0000"
    year = year_match.group()
    month_match = re.search(r"\b(0?[1-9]|1[0-2])\b", end)
    month = month_match.group().zfill(2) if month_match else "00"
    return f"{year}-{month}"


# ---------------------------------------------------------------------------
# Basic cleaning helpers
# ---------------------------------------------------------------------------

_GARBAGE_VALUES = {"n/a", "na", "none", "null", "-", "tbd", "?", "", "unknown", "not specified"}
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _is_garbage(value: str | None) -> bool:
    if not value:
        return True
    return value.strip().lower() in _GARBAGE_VALUES


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).strip(".,;:–-·/")


def _detail_score(entry: dict) -> int:
    return (
        len(entry.get("highlights") or []) * 3
        + len(entry.get("summary") or "")
        + len(entry.get("description") or "")
    )


# ---------------------------------------------------------------------------
# Phone deduplication
# ---------------------------------------------------------------------------

def _phone_digits(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits


def _dedup_phones(phones: list) -> list[str]:
    seen: dict[str, str] = {}
    for p in phones:
        s = str(p).strip()
        if not s:
            continue
        key = _phone_digits(s)
        if key not in seen:
            seen[key] = s
    return list(seen.values())


# ---------------------------------------------------------------------------
# URL deduplication + capping
# ---------------------------------------------------------------------------

_PREFERRED_DOMAINS = ["linkedin.com", "github.com"]
_EXCLUDED_DOMAINS = [
    "play.google.com", "apps.apple.com", "itch.io",
    "youtube.com", "twitter.com", "facebook.com", "instagram.com",
    "reddit.com",
]


def _url_canonical_key(url: str) -> str:
    url = url.strip().rstrip("/")
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower().removeprefix("www.")
        path = p.path.rstrip("/")
        return f"{host}{path}"
    except Exception:
        return url.lower()


def _dedup_and_cap_urls(profiles: list, max_urls: int = 5) -> list[dict]:
    def _priority(item: dict) -> int:
        key = _url_canonical_key(item.get("url", ""))
        for i, domain in enumerate(_PREFERRED_DOMAINS):
            if domain in key:
                return i
        return len(_PREFERRED_DOMAINS)

    seen_keys: set[str] = set()
    result: list[dict] = []

    for item in sorted(profiles, key=_priority):
        url = (item.get("url") or "").strip()
        if not url:
            continue
        key = _url_canonical_key(url)
        if any(ex in key for ex in _EXCLUDED_DOMAINS):
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(item)
        if len(result) >= max_urls:
            break

    return result


# ---------------------------------------------------------------------------
# Fuzzy name similarity (for work/education/project dedup)
# ---------------------------------------------------------------------------

_ORG_NOISE = {"pvt", "ltd", "limited", "inc", "llc", "corp", "co", "the", "and",
              "of", "for", "a", "an", "is", "consultants", "consultant", "technologies",
              "tech", "solutions", "services", "pvt", "private"}


def _key_tokens(name: str) -> frozenset[str]:
    tokens = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return frozenset(t for t in tokens if t not in _ORG_NOISE and len(t) > 1)


def _names_similar(a: str, b: str, threshold: float = 0.4) -> bool:
    """True if two names likely refer to the same entity (fuzzy token overlap)."""
    an = _normalize_text(a)
    bn = _normalize_text(b)
    if not an or not bn:
        return False
    if an == bn:
        return True
    # Substring: shorter contained in longer (e.g. "Suvens" in "Suvens Consultant Pvt Ltd")
    shorter, longer = (an, bn) if len(an) <= len(bn) else (bn, an)
    if len(shorter) > 5 and shorter in longer:
        return True
    # Significant token match: any important token (≥5 chars) shared → same entity
    ta = _key_tokens(a)
    tb = _key_tokens(b)
    sig_a = {t for t in ta if len(t) >= 5}
    sig_b = {t for t in tb if len(t) >= 5}
    if sig_a and sig_b and (sig_a & sig_b):
        return True
    # Jaccard fallback
    if ta and tb:
        return len(ta & tb) / len(ta | tb) >= threshold
    return False


# ---------------------------------------------------------------------------
# Date utilities for overlap detection
# ---------------------------------------------------------------------------

def _ym(date_str: str) -> int:
    """Convert a date string to year*12+month int. 'present'→ very large number."""
    if not date_str:
        return 9999 * 12
    low = date_str.strip().lower()
    if low in ("present", "current", "now", ""):
        return 9999 * 12
    year_m = re.search(r"\d{4}", date_str)
    if not year_m:
        return 0
    y = int(year_m.group())
    m_text = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", date_str, re.I)
    if m_text:
        m = _MONTH_MAP.get(m_text.group()[:3].lower(), 6)
    else:
        m_num = re.search(r"\b(0?[1-9]|1[0-2])\b", date_str)
        m = int(m_num.group()) if m_num else 6
    return y * 12 + m


def _ranges_overlap(sa: str, ea: str, sb: str, eb: str, tolerance: int = 6) -> bool:
    """True if two [start, end] date ranges overlap (with a tolerance in months)."""
    a0 = _ym(sa)
    a1 = _ym(ea or "present")
    b0 = _ym(sb)
    b1 = _ym(eb or "present")
    if a0 == 0 or b0 == 0:
        return False
    return a0 - tolerance <= b1 and b0 - tolerance <= a1


# ---------------------------------------------------------------------------
# Work experience: fuzzy-match + date-overlap merge
# ---------------------------------------------------------------------------

def _is_stub_work(entry: dict) -> bool:
    title = (entry.get("title") or "").strip()
    summary = (entry.get("summary") or "").strip()
    highlights = entry.get("highlights") or []
    return not title and not summary and not highlights


def _merge_work_group(group: list[dict]) -> dict:
    """Merge a cluster of entries representing the same role at the same company."""
    if len(group) == 1:
        return group[0]

    org = max((e.get("organization") or e.get("institution") or "" for e in group), key=len)
    title = max((e.get("title") or "" for e in group), key=len)
    location = next((e.get("location") for e in group if e.get("location")), None)

    # Widest date range
    starts = [e.get("start_date") for e in group if e.get("start_date")]
    ends_raw = [e.get("end_date") for e in group]
    start = min(starts, key=_ym) if starts else ""
    has_present = any((e.get("end_date") or "").strip().lower() in ("present", "current", "now", "")
                      for e in group)
    if has_present:
        end = "Present"
    elif ends_raw:
        end = max((d for d in ends_raw if d), key=_ym, default="")
    else:
        end = ""

    # Best summary: longest; append others if they contain substantially new content
    summaries = list(dict.fromkeys(
        e.get("summary", "").strip() for e in group if e.get("summary", "").strip()
    ))
    if not summaries:
        merged_summary = ""
    elif len(summaries) == 1:
        merged_summary = summaries[0]
    else:
        primary = max(summaries, key=len)
        p_words = set(_normalize_text(primary).split())
        extras = []
        for s in summaries:
            if s == primary:
                continue
            s_words = set(_normalize_text(s).split())
            # Only append if it brings >25% genuinely new words
            if len(s_words - p_words) / max(len(s_words), 1) > 0.25:
                extras.append(s)
        merged_summary = (" ".join([primary] + extras)).strip()

    # Union of all highlights, deduped
    seen_h: set[str] = set()
    merged_highlights: list[str] = []
    for e in group:
        for h in (e.get("highlights") or []):
            h_str = str(h).strip()
            h_norm = _normalize_text(h_str)
            if h_norm and h_norm not in seen_h and len(h_norm) > 5:
                seen_h.add(h_norm)
                merged_highlights.append(h_str)

    return {
        "organization": org,
        "institution": org,
        "title": title,
        "location": location,
        "start_date": start,
        "end_date": end,
        "summary": merged_summary,
        "highlights": merged_highlights,
    }


def _merge_work_experience(entries: list) -> list:
    """Group entries by fuzzy org similarity + date overlap, merge each group."""
    clean = [e for e in entries if not _is_stub_work(e)]
    if not clean:
        return []

    groups: list[list[dict]] = []
    for entry in clean:
        org = entry.get("organization") or entry.get("institution") or ""
        start = entry.get("start_date") or ""
        end = entry.get("end_date") or ""
        placed = False
        for group in groups:
            rep = group[0]
            rep_org = rep.get("organization") or rep.get("institution") or ""
            rep_s = rep.get("start_date") or ""
            rep_e = rep.get("end_date") or ""
            if _names_similar(org, rep_org) and _ranges_overlap(start, end, rep_s, rep_e):
                group.append(entry)
                placed = True
                break
        if not placed:
            groups.append([entry])

    return [_merge_work_group(g) for g in groups]


# ---------------------------------------------------------------------------
# Education: fuzzy-match merge
# ---------------------------------------------------------------------------

_ACHIEVEMENT_RE = re.compile(
    r"\b(hackathon|competition|contest|award|winner|prize|olympiad|championship|tournament|rank)\b",
    re.I,
)


def _is_achievement_entry(entry: dict) -> bool:
    institution = entry.get("institution") or entry.get("organization") or ""
    degree = entry.get("degree") or entry.get("title") or ""
    return bool(_ACHIEVEMENT_RE.search(institution) or _ACHIEVEMENT_RE.search(degree))


def _is_stub_edu(entry: dict) -> bool:
    institution = (entry.get("institution") or entry.get("organization") or "").strip()
    degree = (entry.get("degree") or entry.get("title") or "").strip()
    # Require a real institution — a degree with no institution is useless on a resume
    if _is_garbage(institution):
        return True
    return _is_garbage(degree)


def _merge_edu_group(group: list[dict]) -> dict:
    if len(group) == 1:
        return group[0]
    institution = max((e.get("institution") or e.get("organization") or "" for e in group), key=len)
    degree = max((e.get("degree") or e.get("title") or "" for e in group), key=len)
    field = max((e.get("field_of_study") or "" for e in group), key=len)
    starts = [e.get("start_date") for e in group if e.get("start_date")]
    ends = [e.get("end_date") for e in group if e.get("end_date")]
    start = min(starts, key=_ym) if starts else ""
    end = max(ends, key=_ym) if ends else ""
    seen_h: set[str] = set()
    merged_highlights: list[str] = []
    for e in group:
        for h in (e.get("highlights") or []):
            h_norm = _normalize_text(str(h))
            if h_norm not in seen_h:
                seen_h.add(h_norm)
                merged_highlights.append(str(h).strip())
    return {
        "institution": institution,
        "organization": institution,
        "degree": degree,
        "field_of_study": field,
        "start_date": start,
        "end_date": end,
        "highlights": merged_highlights,
    }


def _merge_education(entries: list) -> list:
    """Group education entries by fuzzy institution similarity, merge each group."""
    clean = [e for e in entries if not _is_stub_edu(e) and not _is_achievement_entry(e)]
    if not clean:
        return []

    groups: list[list[dict]] = []
    for entry in clean:
        institution = entry.get("institution") or entry.get("organization") or ""
        placed = False
        for group in groups:
            rep_inst = group[0].get("institution") or group[0].get("organization") or ""
            if _names_similar(institution, rep_inst, threshold=0.45):
                group.append(entry)
                placed = True
                break
        if not placed:
            groups.append([entry])

    return [_merge_edu_group(g) for g in groups]


# ---------------------------------------------------------------------------
# Project: fuzzy-match merge
# ---------------------------------------------------------------------------

def _merge_project_group(group: list[dict]) -> dict | None:
    if len(group) == 1:
        proj = group[0]
    else:
        best = max(group, key=_detail_score)
        name = max((p.get("name") or "" for p in group), key=len)
        techs_seen: set[str] = set()
        all_techs: list[str] = []
        for p in group:
            for t in (p.get("technologies") or []):
                t_norm = t.strip().lower()
                if t_norm not in techs_seen:
                    techs_seen.add(t_norm)
                    all_techs.append(t.strip())
        seen_h: set[str] = set()
        all_highlights: list[str] = []
        for p in group:
            for h in (p.get("highlights") or []):
                h_norm = _normalize_text(str(h))
                if h_norm not in seen_h and len(h_norm) > 5:
                    seen_h.add(h_norm)
                    all_highlights.append(str(h).strip())
        seen_links: set[str] = set()
        all_links: list = []
        for p in group:
            for link in (p.get("links") or []):
                link_key = str(link)
                if link_key not in seen_links:
                    seen_links.add(link_key)
                    all_links.append(link)
        proj = {
            "name": name,
            "summary": best.get("summary") or "",
            "technologies": all_techs,
            "highlights": all_highlights,
            "links": all_links,
        }

    # Drop stub: name present but zero content
    summary = (proj.get("summary") or "").strip()
    highlights = proj.get("highlights") or []
    # Allow links even if no summary/highlights (link-only projects show something)
    links = [lk for lk in (proj.get("links") or []) if _link_url(lk)]
    if not summary and not highlights and not links:
        return None
    return proj


def _link_url(link) -> str:
    """Extract URL string from a link that may be a str or a dict."""
    if isinstance(link, dict):
        return (link.get("url") or "").strip()
    return str(link).strip() if link else ""


def _merge_projects(projects: list) -> list:
    groups: list[list[dict]] = []
    for proj in projects:
        name = (proj.get("name") or "").strip()
        if _is_garbage(name) or len(name) < 3:
            continue
        placed = False
        for group in groups:
            rep_name = (group[0].get("name") or "").strip()
            if _names_similar(name, rep_name, threshold=0.35):
                group.append(proj)
                placed = True
                break
        if not placed:
            groups.append([proj])

    result = []
    for group in groups:
        merged = _merge_project_group(group)
        if merged:
            result.append(merged)
    return result


# ---------------------------------------------------------------------------
# Bullet cleaning
# ---------------------------------------------------------------------------

_COMPANY_STUB_RE = re.compile(
    r"\b(pvt|ltd|limited|inc|llc|corp|l\.l\.c|navy|army|defence|defense)\b",
    re.I,
)
_ACTION_VERB_RE = re.compile(
    r"^(built|developed|designed|implemented|created|led|managed|optimized|deployed|"
    r"architected|delivered|worked|contributed|maintained|researched|analyzed|improved|"
    r"automated|integrated|launched|coordinated|supported|established|drove|scaled|"
    r"reduced|increased|achieved|spearheaded|extended|diagnosed|fixed|conducted|authored|"
    r"co-authored|migrated|refactored|streamlined|documented|monitored|evaluated|"
    r"trained|fine-tuned|built|ingested|processed)\b",
    re.I,
)


def _is_company_stub_bullet(b: str) -> bool:
    """True if bullet looks like a stray company/org name rather than an achievement."""
    words = b.split()
    if len(words) > 10:
        return False
    if _ACTION_VERB_RE.match(b):
        return False
    return bool(_COMPANY_STUB_RE.search(b))


def _summary_sentences(summary: str) -> set[str]:
    sentences: set[str] = set()
    for sent in re.split(r"(?<=[.!?])\s+", summary):
        s = _normalize_text(sent)
        if len(s) > 15:
            sentences.add(s)
    sentences.add(_normalize_text(summary))
    return sentences


def _dedup_bullets(bullets: list, summary: str = "") -> list[str]:
    seen: set[str] = set()
    summary_sents = _summary_sentences(summary) if summary else set()
    result: list[str] = []

    for bullet in bullets:
        b = str(bullet).strip("•·-–* ").strip()
        if not b or len(b) < 5:
            continue
        if _is_company_stub_bullet(b):
            continue
        b_norm = _normalize_text(b)
        if b_norm in seen:
            continue
        is_summary_dupe = any(
            len(b_norm) > 15 and (b_norm == sent or b_norm in sent or sent in b_norm)
            for sent in summary_sents
        )
        if is_summary_dupe:
            continue
        seen.add(b_norm)
        result.append(b)

    return result


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_resume_text(profile: "Profile") -> str:
    auto = _auto(profile.profile_data)
    identity = auto.get("identity") or {}
    skills = auto.get("skills") or []
    public_profiles = auto.get("public_profiles") or []

    phones = _dedup_phones(identity.get("phones") or [])
    urls = _dedup_and_cap_urls(public_profiles, max_urls=5)

    work_experience = sorted(
        _merge_work_experience(auto.get("work_experience") or []),
        key=_date_sort_key, reverse=True,
    )
    education = sorted(
        _merge_education(auto.get("education") or []),
        key=_date_sort_key, reverse=True,
    )
    projects = _merge_projects(auto.get("projects") or [])

    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────
    name = (identity.get("full_name") or "").strip()
    if name:
        lines.append(name.upper())

    headline = (identity.get("headline") or identity.get("current_position") or "").strip()
    if headline:
        lines.append(headline)

    contact_parts: list[str] = []
    location = (identity.get("location") or "").strip()
    if location:
        contact_parts.append(location)
    for email in (identity.get("emails") or []):
        if email:
            contact_parts.append(str(email).strip())
    for phone in phones:
        contact_parts.append(phone)
    for pub in urls:
        url = (pub.get("url") or "").strip()
        if url:
            contact_parts.append(url)
    if contact_parts:
        lines.append("  ·  ".join(contact_parts))

    # ── Summary ──────────────────────────────────────────────────
    summary = (identity.get("summary") or "").strip()
    if summary:
        lines += ["", "SUMMARY", "─" * 58, summary]

    # ── Experience ───────────────────────────────────────────────
    if work_experience:
        lines += ["", "EXPERIENCE", "─" * 58]
        for exp in work_experience:
            org = (exp.get("organization") or exp.get("institution") or "").strip()
            title = (exp.get("title") or "").strip()
            start = (exp.get("start_date") or "").strip()
            end = (exp.get("end_date") or "Present").strip()
            date_str = f"{start} – {end}".strip(" –") if start else ""
            header = "  |  ".join(p for p in [org, title, date_str] if p)
            if header:
                lines.append(header)
            loc = (exp.get("location") or "").strip()
            if loc:
                lines.append(f"  {loc}")
            desc = (exp.get("summary") or "").strip()
            for line in desc.splitlines():
                s = line.strip()
                if s:
                    lines.append(f"  {s}")
            for bullet in _dedup_bullets(exp.get("highlights") or [], summary=desc):
                lines.append(f"  • {bullet}")
            lines.append("")

    # ── Education ────────────────────────────────────────────────
    if education:
        lines += ["EDUCATION", "─" * 58]
        for edu in education:
            degree = (edu.get("degree") or edu.get("title") or "").strip()
            field = (edu.get("field_of_study") or "").strip()
            institution = (edu.get("institution") or edu.get("organization") or "").strip()
            if degree and field and _normalize_text(degree) == _normalize_text(field):
                degree_full = degree
            else:
                degree_full = f"{degree} in {field}" if degree and field else degree or field
            if _normalize_text(institution) == _normalize_text(degree_full):
                degree_full = ""
            start = (edu.get("start_date") or "").strip()
            end = (edu.get("end_date") or "").strip()
            date_str = f"{start} – {end}".strip(" –") if start else end
            header = "  |  ".join(p for p in [institution, degree_full, date_str] if p)
            if header:
                lines.append(header)
            for bullet in _dedup_bullets(edu.get("highlights") or []):
                lines.append(f"  • {bullet}")
            lines.append("")

    # ── Skills ───────────────────────────────────────────────────
    if skills:
        lines += ["SKILLS", "─" * 58]
        lines.append(", ".join(str(s).strip() for s in skills if s))
        lines.append("")

    # ── Projects ─────────────────────────────────────────────────
    if projects:
        lines += ["PROJECTS", "─" * 58]
        for proj in projects:
            proj_name = (proj.get("name") or "").strip()
            techs = [str(t).strip() for t in (proj.get("technologies") or []) if t]
            tech_str = ", ".join(techs)
            header = f"{proj_name}  [{tech_str}]" if tech_str else proj_name
            if header:
                lines.append(header)
            desc = (proj.get("summary") or "").strip()
            for line in desc.splitlines():
                s = line.strip()
                if s:
                    lines.append(f"  {s}")
            for bullet in _dedup_bullets(proj.get("highlights") or [], summary=desc):
                lines.append(f"  • {bullet}")
            for link in (proj.get("links") or []):
                url = _link_url(link)
                if url:
                    label = link.get("label") if isinstance(link, dict) else ""
                    lines.append(f"  {label + ': ' if label else ''}{url}")
            lines.append("")

    return "\n".join(lines).strip()


def generate_cv_text(profile: "Profile") -> str:
    """CV: resume content plus certifications."""
    base = generate_resume_text(profile)
    auto = _auto(profile.profile_data)
    certifications = auto.get("certifications") or []

    lines = [base]

    if certifications:
        lines += ["", "CERTIFICATIONS", "─" * 58]
        for cert in certifications:
            cert_name = (cert.get("name") or cert.get("title") or "").strip()
            issuer = (cert.get("issuer") or cert.get("organization") or "").strip()
            date = (cert.get("end_date") or cert.get("start_date") or "").strip()
            if _is_garbage(cert_name):
                continue
            header = "  |  ".join(p for p in [cert_name, issuer, date] if p)
            if header:
                lines.append(header)
        lines.append("")

    return "\n".join(lines).strip()


def generate_and_store_resume(session: "Session", profile: "Profile") -> None:
    """Generate resume and CV texts and persist them in profile_data."""
    container = dict(profile.profile_data or {})
    container["generated_resume"] = generate_resume_text(profile)
    container["generated_cv"] = generate_cv_text(profile)
    profile.profile_data = container
    session.flush()
