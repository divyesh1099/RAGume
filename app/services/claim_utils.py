import re
from difflib import SequenceMatcher


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9+#._-]+")
METRIC_PATTERN = re.compile(
    r"\b(?:\d[\d,]*(?:\.\d+)?\+?\s?(?:%|percent|pages?|users?|docs?|documents?|hours?|days?|weeks?|months?|years?|x|ms|s))\b",
    flags=re.IGNORECASE,
)
ROLE_PATTERN = re.compile(
    r"\b(machine learning engineer|ml engineer|software engineer|backend engineer|data engineer|developer|manager|intern|researcher)\b",
    flags=re.IGNORECASE,
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "using",
    "with",
}
ACTION_VERBS = {
    "built",
    "developed",
    "implemented",
    "designed",
    "launched",
    "optimized",
    "created",
    "automated",
    "deployed",
    "improved",
    "managed",
    "integrated",
    "trained",
    "fine-tuned",
    "led",
    "delivered",
}
SKILL_PATTERNS = {
    "Python": r"\bpython\b",
    "C#": r"\bc#\b|\bcsharp\b",
    "C++": r"\bc\+\+\b",
    "FastAPI": r"\bfastapi\b",
    "RAG": r"\brag\b|\bretrieval[- ]augmented\b",
    "LLM": r"\bllm\b|\blarge language model",
    "OpenAI": r"\bopenai\b",
    "OCR": r"\bocr\b|\boptical character recognition\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Redis": r"\bredis\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "SQL": r"\bsql\b",
    "CSS": r"\bcss\b",
    "PyMuPDF": r"\bpymupdf\b",
    "Docling": r"\bdocling\b",
    "LayoutLMv3": r"\blayoutlmv3\b",
    "NSQ": r"\bnsq\b",
    "Kafka": r"\bkafka\b",
    "PyTorch": r"\bpytorch\b",
    "TensorFlow": r"\btensorflow\b",
    "BERT": r"\bbert\b",
    "Flask": r"\bflask\b",
    "Helm": r"\bhelm\b",
    "MLflow": r"\bmlflow\b",
    "MVC": r"\bmvc\b",
    "React": r"\breact\b",
    "Next.js": r"\bnext\.?js\b",
    "TypeScript": r"\btypescript\b",
    "JavaScript": r"\bjavascript\b",
    "AWS": r"\baws\b|\bamazon web services\b",
    "GCP": r"\bgcp\b|\bgoogle cloud\b",
    "CI/CD": r"\bci/cd\b|\bcontinuous integration\b",
    "Playwright": r"\bplaywright\b",
    "Selenium": r"\bselenium\b",
    "NLP": r"\bnlp\b|\bnatural language processing\b",
}


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def normalize_claim(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", collapsed)


def extract_skills(text: str) -> list[str]:
    matches: list[str] = []
    lowered = text.lower()
    for skill, pattern in SKILL_PATTERNS.items():
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            matches.append(skill)
    return sorted(set(matches))


def infer_category(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("bachelor", "master", "university", "college")):
        return "education"
    if any(term in lowered for term in ("certificate", "certification", "certified")):
        return "certification"
    if any(term in lowered for term in ("intern", "engineer", "manager", "worked as", "company")):
        return "work_experience"
    if any(term in lowered for term in ("project", "pipeline", "system", "application", "platform", "tool")):
        return "project"
    return "general"


def content_token_set(text: str) -> set[str]:
    return {token for token in tokenize(text) if token not in STOPWORDS and len(token) > 2}


def claim_similarity(left: str, right: str) -> float:
    left_norm = normalize_claim(left)
    right_norm = normalize_claim(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = content_token_set(left_norm)
    right_tokens = content_token_set(right_norm)
    if not left_tokens or not right_tokens:
        return sequence_score

    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    jaccard = intersection / union if union else 0.0
    return max(sequence_score, jaccard)


def claims_are_duplicates(
    left: str,
    right: str,
    left_skills: list[str] | None = None,
    right_skills: list[str] | None = None,
) -> bool:
    similarity = claim_similarity(left, right)
    if similarity >= 0.93:
        return True

    left_tokens = content_token_set(left)
    right_tokens = content_token_set(right)
    if not left_tokens or not right_tokens:
        return False

    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    shared_skills = set(left_skills or []) & set(right_skills or [])
    return overlap >= 0.8 and (len(shared_skills) >= 1 or similarity >= 0.86)


def merge_support_chunk_ids(existing_ids: list[str], new_ids: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for chunk_id in [*existing_ids, *new_ids]:
        if chunk_id in seen:
            continue
        merged.append(chunk_id)
        seen.add(chunk_id)
    return merged


def extract_metrics(text: str) -> list[str]:
    return sorted({match.group(0).strip() for match in METRIC_PATTERN.finditer(text)})


def extract_roles(text: str) -> list[str]:
    return sorted({match.group(1).strip().title() for match in ROLE_PATTERN.finditer(text)})


def extract_claim_entities(text: str, skills: list[str], category: str) -> list[dict]:
    entities: list[dict] = []

    for skill in skills:
        entities.append(
            {
                "type": "skill",
                "name": skill,
                "normalized": normalize_claim(skill),
            }
        )

    for metric in extract_metrics(text):
        entities.append(
            {
                "type": "metric",
                "name": metric,
                "normalized": normalize_claim(metric),
            }
        )

    for role in extract_roles(text):
        entities.append(
            {
                "type": "role",
                "name": role,
                "normalized": normalize_claim(role),
            }
        )

    entities.append(
        {
            "type": "category",
            "name": category.replace("_", " "),
            "normalized": normalize_claim(category),
        }
    )

    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entity in entities:
        key = (entity["type"], entity["normalized"])
        if key in seen:
            continue
        deduped.append(entity)
        seen.add(key)
    return deduped


def assess_claim_evidence(
    claim_text: str,
    supporting_chunks: list[dict],
    confidence: float,
    skills: list[str],
) -> dict:
    support_chunks = len(supporting_chunks)
    support_chars = sum(len(chunk.get("text", "")) for chunk in supporting_chunks)
    quantified = bool(re.search(r"\d", claim_text))
    action_signal = any(verb in claim_text.lower() for verb in ACTION_VERBS)
    metric_entities = extract_metrics(claim_text)

    score = 32.0
    score += min(18.0, support_chunks * 8.0)
    score += min(16.0, len(skills) * 4.0)
    if quantified:
        score += 12.0
    if action_signal:
        score += 8.0
    if support_chars >= 220:
        score += 8.0
    if metric_entities:
        score += 4.0
    score += min(8.0, confidence * 10.0)
    score = round(min(score, 98.0), 1)

    if score >= 80:
        label = "strong"
        overclaim_risk = "low"
    elif score >= 65:
        label = "good"
        overclaim_risk = "low"
    elif score >= 50:
        label = "moderate"
        overclaim_risk = "medium"
    else:
        label = "weak"
        overclaim_risk = "high"

    return {
        "score": score,
        "label": label,
        "overclaim_risk": overclaim_risk,
        "support_chunk_count": support_chunks,
        "support_characters": support_chars,
        "quantified": quantified,
        "metric_entities": metric_entities,
        "action_signal": action_signal,
        "skill_signal_count": len(skills),
    }
