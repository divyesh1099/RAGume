"""Company and job research via OpenAI web search."""
from __future__ import annotations

import json
import re

_EXTRACT_SYSTEM = """You extract company name and job title from job descriptions.
Return ONLY valid JSON, no markdown, no explanation."""

_EXTRACT_USER = """From this job description, extract the company name and job title.
If not clearly mentioned, make your best inference from context clues.

Job description:
{jd_text}

Return JSON:
{{"company_name": "...", "job_title": "..."}}"""

_RESEARCH_PROMPT = """You are a job market research assistant with web search access.

Research the following for a job applicant:
- Company: {company_name}
- Position: {job_title}
- Candidate level: {profile_summary}

Job description excerpt (use this to determine the job location and local salary norms):
{jd_excerpt}

Search the web and provide:
1. **Company verification**: Is {company_name} a real, legitimate company? What is their full official name, size (employees), industry, founding year, headquarters location, and website?
2. **Job verification**: Is there an active or recent listing for "{job_title}" at {company_name} on LinkedIn, Indeed, Glassdoor, Naukri, or other job boards?
3. **Salary data**: What is the typical salary range for a "{job_title}" at {company_name} or comparable companies in the same industry and **job location** (not HQ). Use the currency of the job location (e.g. INR for India, USD for USA, GBP for UK, EUR for European countries, AED for UAE). Factor in the candidate's experience level.

Return ONLY a valid JSON object (no markdown fences, no extra text):
{{
    "company": {{
        "full_name": "official company name",
        "is_real": true,
        "is_reliable": true,
        "size": "e.g. 500-1000 employees or startup/mid-size/enterprise",
        "industry": "primary industry",
        "founded": "year or decade",
        "website": "company website URL",
        "headquarters": "city, country",
        "reliability_notes": "brief trust assessment"
    }},
    "job": {{
        "is_verified": true,
        "found_on": ["LinkedIn", "Glassdoor"],
        "job_urls": ["direct URL to listing if found"],
        "location": "city, country where the job is based",
        "notes": "job availability notes"
    }},
    "salary": {{
        "low": 0,
        "mid": 0,
        "high": 0,
        "currency": "currency code matching the job location, e.g. INR/USD/GBP/EUR/AED/SGD/AUD",
        "experience_level": "junior/mid/senior",
        "notes": "salary context, sources, and job location used for the estimate"
    }}
}}"""


def _parse_json_from_text(text: str) -> dict:
    """Extract the first JSON object from a text that may contain extra prose."""
    # Strip markdown fences if present
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def extract_company_from_jd(
    jd_text: str,
    api_key: str,
    model: str = "gpt-4.1-mini",
) -> dict:
    """Extract company name and job title from a job description using GPT."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": _EXTRACT_USER.format(jd_text=jd_text[:3000])},
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        text = response.choices[0].message.content or "{}"
        data = _parse_json_from_text(text)
        return {
            "company_name": (data.get("company_name") or "").strip(),
            "job_title": (data.get("job_title") or "").strip(),
        }
    except Exception as exc:
        return {"company_name": "", "job_title": "", "error": str(exc)}


def research_company_and_job(
    company_name: str,
    job_title: str,
    jd_text: str,
    profile_summary: str,
    api_key: str,
    fallback_model: str = "gpt-4.1-mini",
) -> dict:
    """
    Search the web for company and job info, synthesize into structured data.
    Tries gpt-4o-mini-search-preview (has live web search) first;
    falls back to the configured model if unavailable.
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = _RESEARCH_PROMPT.format(
        company_name=company_name,
        job_title=job_title,
        profile_summary=profile_summary or "experienced professional",
        jd_excerpt=jd_text[:800],
    )

    # Try web-search model first for live data
    for model in ["gpt-4o-mini-search-preview", fallback_model]:
        try:
            kwargs: dict = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200,
            }
            if model == "gpt-4o-mini-search-preview":
                # Enable web search for this model
                kwargs["web_search_options"] = {"search_context_size": "medium"}
            else:
                # Ask the fallback model to do its best from training data
                kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**kwargs)
            text = (response.choices[0].message.content or "").strip()
            result = _parse_json_from_text(text)
            if result and "company" in result:
                result["_model_used"] = model
                result["_web_search"] = (model == "gpt-4o-mini-search-preview")
                return result
        except Exception:
            continue

    return {
        "error": "Research unavailable — check OpenAI API key and quota.",
        "company": {},
        "job": {},
        "salary": {},
    }
