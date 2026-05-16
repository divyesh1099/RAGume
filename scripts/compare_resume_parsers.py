from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models import Document
from app.services.docling_resume_parser import parse_resume_document_with_docling
from app.services.parsing import compute_checksum, detect_mime_type, extract_text_from_path
from app.services.resume_parser import parse_resume_document


@dataclass
class Expectations:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    work_count: int | None = None
    project_count: int | None = None
    education_count: int | None = None


@dataclass
class ParserResult:
    label: str
    mode: str
    summary: dict[str, Any]
    warnings: list[str]
    score: dict[str, Any] | None
    raw: dict[str, Any]


def _build_document(
    path: Path,
    *,
    document_id: str,
    extracted_text: str,
    parse_metadata: dict[str, Any],
) -> Document:
    document = Document(
        filename=path.name,
        storage_path=str(path),
        source_type="upload",
        mime_type=detect_mime_type(path),
        checksum=compute_checksum(path),
        extracted_text=extracted_text,
        parse_metadata=parse_metadata,
        profile_id="comparison-profile",
    )
    document.id = document_id
    return document


def _normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return None
    if len(digits) == 12 and digits.startswith("91"):
        return digits[-10:]
    return digits[-10:]


def _score_summary(summary: dict[str, Any], expectations: Expectations) -> dict[str, Any] | None:
    checks: list[dict[str, Any]] = []
    if expectations.name:
        actual = (summary.get("full_name") or "").strip().lower()
        expected = expectations.name.strip().lower()
        checks.append(
            {
                "field": "name",
                "ok": bool(actual) and (actual == expected or expected in actual),
                "expected": expectations.name,
                "actual": summary.get("full_name"),
            }
        )
    if expectations.email:
        actual_emails = [str(value).lower() for value in summary.get("emails", [])]
        checks.append(
            {
                "field": "email",
                "ok": expectations.email.lower() in actual_emails,
                "expected": expectations.email,
                "actual": summary.get("emails", []),
            }
        )
    if expectations.phone:
        expected_phone = _normalize_phone(expectations.phone)
        actual_phones = {_normalize_phone(value) for value in summary.get("phones", [])}
        checks.append(
            {
                "field": "phone",
                "ok": expected_phone is not None and expected_phone in actual_phones,
                "expected": expectations.phone,
                "actual": summary.get("phones", []),
            }
        )
    if expectations.work_count is not None:
        checks.append(
            {
                "field": "work_count",
                "ok": int(summary.get("work_count", 0)) >= expectations.work_count,
                "expected": expectations.work_count,
                "actual": summary.get("work_count", 0),
            }
        )
    if expectations.project_count is not None:
        checks.append(
            {
                "field": "project_count",
                "ok": int(summary.get("project_count", 0)) >= expectations.project_count,
                "expected": expectations.project_count,
                "actual": summary.get("project_count", 0),
            }
        )
    if expectations.education_count is not None:
        checks.append(
            {
                "field": "education_count",
                "ok": int(summary.get("education_count", 0)) >= expectations.education_count,
                "expected": expectations.education_count,
                "actual": summary.get("education_count", 0),
            }
        )

    if not checks:
        return None

    passed = sum(1 for check in checks if check["ok"])
    return {"passed": passed, "total": len(checks), "checks": checks}


def _summarize_structured_payload(payload: dict[str, Any]) -> dict[str, Any]:
    identity = payload.get("identity", {})
    return {
        "full_name": identity.get("full_name"),
        "emails": identity.get("emails", []),
        "phones": identity.get("phones", []),
        "links": [item.get("url") for item in payload.get("public_profiles", []) if item.get("url")],
        "work_count": len(payload.get("work_experience", [])),
        "project_count": len(payload.get("projects", [])),
        "education_count": len(payload.get("education", [])),
        "skill_count": len(payload.get("skills", [])),
        "work_titles": [
            " @ ".join(part for part in (item.get("title"), item.get("organization")) if part)
            for item in payload.get("work_experience", [])
        ],
        "project_names": [item.get("name") for item in payload.get("projects", [])],
        "education_institutions": [item.get("institution") for item in payload.get("education", [])],
    }


def _summarize_openresume_payload(payload: dict[str, Any]) -> dict[str, Any]:
    resume = payload.get("resume", {})
    profile = resume.get("profile", {})
    projects = resume.get("projects", [])
    educations = resume.get("educations", [])
    work_experiences = resume.get("workExperiences", [])
    featured_skills = resume.get("skills", {}).get("featuredSkills", [])
    return {
        "full_name": profile.get("name"),
        "emails": [profile.get("email")] if profile.get("email") else [],
        "phones": [profile.get("phone")] if profile.get("phone") else [],
        "links": [profile.get("url")] if profile.get("url") else [],
        "work_count": len(work_experiences),
        "project_count": len(projects),
        "education_count": len(educations),
        "skill_count": len([item for item in featured_skills if item.get("skill")]),
        "work_titles": [item.get("jobTitle") or item.get("company") for item in work_experiences],
        "project_names": [item.get("project") or item.get("name") for item in projects],
        "education_institutions": [item.get("school") for item in educations],
    }


def _run_current_parser(path: Path, expectations: Expectations) -> ParserResult:
    settings = get_settings()
    extracted_text, parse_metadata = extract_text_from_path(path)
    document = _build_document(
        path,
        document_id=f"current:{path.stem}",
        extracted_text=extracted_text,
        parse_metadata=parse_metadata,
    )
    structured, mode, warnings, diagnostics = parse_resume_document(document, settings)
    summary = _summarize_structured_payload(structured)
    return ParserResult(
        label="current_layout_ner",
        mode=mode,
        summary=summary,
        warnings=warnings,
        score=_score_summary(summary, expectations),
        raw={"structured": structured, "diagnostics": diagnostics},
    )


def _run_docling_parser(path: Path, expectations: Expectations) -> ParserResult:
    settings = get_settings()
    document = _build_document(
        path,
        document_id=f"docling:{path.stem}",
        extracted_text="",
        parse_metadata={"parser": "docling_structured"},
    )
    structured, mode, warnings, diagnostics = parse_resume_document_with_docling(document, settings)
    summary = _summarize_structured_payload(structured)
    return ParserResult(
        label="docling_structured_ner",
        mode=mode,
        summary=summary,
        warnings=warnings,
        score=_score_summary(summary, expectations),
        raw={"structured": structured, "diagnostics": diagnostics},
    )


def _ensure_openresume_checkout(openresume_root: Path) -> None:
    if not openresume_root.exists():
        openresume_root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", "https://github.com/xitanggg/open-resume.git", str(openresume_root)],
            check=True,
        )
    if not (openresume_root / "node_modules").exists():
        subprocess.run(["npm", "install"], cwd=openresume_root, check=True)


def _run_openresume_parser(path: Path, expectations: Expectations, openresume_root: Path) -> ParserResult:
    _ensure_openresume_checkout(openresume_root)
    bridge_path = Path(__file__).with_name("openresume_bridge.ts")
    env = os.environ.copy()
    env["OPENRESUME_ROOT"] = str(openresume_root)
    completed = subprocess.run(
        ["npx", "--yes", "tsx", str(bridge_path), str(path)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    summary = _summarize_openresume_payload(payload)
    return ParserResult(
        label="openresume_logic",
        mode="openresume_parser",
        summary=summary,
        warnings=[],
        score=_score_summary(summary, expectations),
        raw=payload,
    )


def _print_result(result: ParserResult) -> None:
    print(result.label)
    print(f"  mode: {result.mode}")
    if result.score:
        print(f"  score: {result.score['passed']}/{result.score['total']}")
    print(f"  name: {result.summary.get('full_name') or '-'}")
    print(f"  emails: {', '.join(result.summary.get('emails', [])) or '-'}")
    print(f"  phones: {', '.join(result.summary.get('phones', [])) or '-'}")
    print(
        "  counts:"
        f" work={result.summary.get('work_count', 0)}"
        f" projects={result.summary.get('project_count', 0)}"
        f" education={result.summary.get('education_count', 0)}"
        f" skills={result.summary.get('skill_count', 0)}"
    )
    work_titles = [title for title in result.summary.get("work_titles", []) if title]
    project_names = [name for name in result.summary.get("project_names", []) if name]
    if work_titles:
        print(f"  work sample: {', '.join(work_titles[:3])}")
    if project_names:
        print(f"  projects: {', '.join(project_names[:4])}")
    if result.warnings:
        print(f"  warnings: {' | '.join(result.warnings)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare current parser, Docling, and OpenResume on one resume PDF.")
    parser.add_argument("resume_path", type=Path, help="Path to the resume PDF.")
    parser.add_argument("--openresume-root", type=Path, default=Path("data/parser-cache/open-resume"))
    parser.add_argument("--expect-name")
    parser.add_argument("--expect-email")
    parser.add_argument("--expect-phone")
    parser.add_argument("--expect-work-count", type=int)
    parser.add_argument("--expect-project-count", type=int)
    parser.add_argument("--expect-education-count", type=int)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of the text report.")
    parser.add_argument("--output", type=Path, help="Optional path to save the JSON result.")
    args = parser.parse_args()

    resume_path = args.resume_path.expanduser().resolve()
    if not resume_path.exists():
        raise SystemExit(f"Resume file was not found: {resume_path}")

    expectations = Expectations(
        name=args.expect_name,
        email=args.expect_email,
        phone=args.expect_phone,
        work_count=args.expect_work_count,
        project_count=args.expect_project_count,
        education_count=args.expect_education_count,
    )

    results = [
        _run_current_parser(resume_path, expectations),
        _run_docling_parser(resume_path, expectations),
        _run_openresume_parser(resume_path, expectations, args.openresume_root.resolve()),
    ]

    payload = {
        "resume_path": str(resume_path),
        "expectations": asdict(expectations),
        "results": [asdict(result) for result in results],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"Parser comparison for {resume_path.name}")
    print()
    for result in results:
        _print_result(result)
        print()
    if args.output:
        print(f"Saved JSON report to {args.output}")


if __name__ == "__main__":
    main()
