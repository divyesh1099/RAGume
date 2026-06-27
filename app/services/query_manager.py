"""Resume-specific query understanding: expansion and type classification.

Ported from NITRAG's query_manager.py, adapted for resume/career domain.
Expansion improves recall by matching both the acronym and its full form.
"""

from __future__ import annotations

import re

# Lowercase abbreviation → expanded form (resume/tech domain)
RESUME_EXPANSIONS: dict[str, str] = {
    "ml": "machine learning",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "ai": "artificial intelligence",
    "dl": "deep learning",
    "rl": "reinforcement learning",
    "gan": "generative adversarial network",
    "llm": "large language model",
    "llms": "large language models",
    "rag": "retrieval augmented generation",
    "api": "application programming interface",
    "rest": "representational state transfer",
    "graphql": "graph query language",
    "sql": "structured query language",
    "nosql": "non relational database",
    "ui": "user interface",
    "ux": "user experience",
    "ci": "continuous integration",
    "cd": "continuous deployment",
    "cicd": "continuous integration continuous deployment",
    "oop": "object oriented programming",
    "fp": "functional programming",
    "ds": "data science",
    "etl": "extract transform load",
    "kpi": "key performance indicator",
    "sla": "service level agreement",
    "aws": "amazon web services",
    "gcp": "google cloud platform",
    "azure": "microsoft azure cloud",
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "py": "python programming",
    "mlops": "machine learning operations",
    "devops": "development operations",
    "swe": "software engineer",
    "sde": "software development engineer",
    "sr": "senior",
    "jr": "junior",
    "pm": "product manager",
    "tpm": "technical program manager",
    "eda": "exploratory data analysis",
    "ocr": "optical character recognition",
    "erp": "enterprise resource planning",
    "crm": "customer relationship management",
    "bert": "transformer language model",
    "gpt": "generative pretrained transformer",
    "cnn": "convolutional neural network",
    "rnn": "recurrent neural network",
    "lstm": "long short term memory",
    "svm": "support vector machine",
    "xgb": "gradient boosting",
    "rf": "random forest",
    "ab": "a b testing",
    "fe": "front end",
    "be": "back end",
    "fs": "full stack",
    "spa": "single page application",
    "mvc": "model view controller",
    "orm": "object relational mapping",
    "cdn": "content delivery network",
    "dsa": "data structures and algorithms",
}

# Query type → discriminating keyword signals
_QUERY_TYPE_SIGNALS: dict[str, list[str]] = {
    "skills": [
        "skill", "technology", "tech", "language", "framework", "tool",
        "stack", "proficient", "familiar", "know", "used", "work with",
        "experience with", "expertise",
    ],
    "experience": [
        "work", "job", "role", "position", "company", "employer", "career",
        "year", "history", "previous", "past", "employment", "worked at",
        "joined", "left",
    ],
    "projects": [
        "project", "built", "developed", "created", "implemented", "launched",
        "shipped", "side project", "portfolio", "github", "personal",
    ],
    "education": [
        "degree", "university", "college", "school", "study", "graduate",
        "bachelor", "master", "phd", "gpa", "major", "course", "graduated",
    ],
    "certifications": [
        "certification", "certificate", "certified", "license", "credential",
        "award", "achievement", "exam", "passed",
    ],
    "achievements": [
        "achievement", "accomplish", "award", "recognition", "promoted", "led",
        "managed", "impact", "result", "metric", "percent", "improve", "saved",
        "reduced", "increased", "delivered",
    ],
}


def expand_query(query: str) -> list[str]:
    """Return ``[query]`` or ``[query, expanded_query]`` when abbreviations are found.

    Uses word-boundary matching so "ML pipeline" → "machine learning pipeline"
    without touching "html" inside a longer word.
    """
    expanded = query
    found_any = False

    for abbrev, full_form in RESUME_EXPANSIONS.items():
        pattern = r"\b" + re.escape(abbrev) + r"\b"
        if re.search(pattern, expanded, re.IGNORECASE):
            expanded = re.sub(pattern, full_form, expanded, flags=re.IGNORECASE)
            found_any = True

    if found_any and expanded.strip().lower() != query.strip().lower():
        return [query, expanded]
    return [query]


def classify_query(query: str) -> str:
    """Return the best-matching query type.

    Returns one of: skills | experience | projects | education |
    certifications | achievements | general
    """
    lowered = query.lower()
    best_type = "general"
    best_count = 0

    for query_type, signals in _QUERY_TYPE_SIGNALS.items():
        count = sum(1 for signal in signals if signal in lowered)
        if count > best_count:
            best_count = count
            best_type = query_type

    return best_type
