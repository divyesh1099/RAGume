import json
from types import SimpleNamespace

from app.config import Settings
from app.services import correction_resolver
from app.services import embeddings
from app.services.correction_resolver import ArbiterChoice, ResolverCandidate


def test_resolved_candidate_uses_embedding_similarity(monkeypatch) -> None:
    settings = Settings(
        enable_embedding_retrieval=True,
        openai_api_key="test-key",
        enable_correction_llm_arbiter=False,
    )

    monkeypatch.setattr(
        correction_resolver,
        "ensure_correction_embeddings",
        lambda *_args, **_kwargs: (
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
            ],
            {"hits": 2, "misses": 1},
        ),
    )
    fake_profile = SimpleNamespace(id="profile-1")

    best, score, action_override, evidence = correction_resolver._resolved_candidate(
        None,
        fake_profile,
        "postgres",
        field_type="skill",
        section="skills",
        source_text="Python, postgres, Docker",
        parser_confidence=0.56,
        candidates=[
            ResolverCandidate(value="PostgreSQL", source="canonical", graph_score=0.55, section_context_score=1.0),
            ResolverCandidate(value="Redis", source="canonical", graph_score=0.45, section_context_score=1.0),
        ],
        settings=settings,
    )

    assert best is not None
    assert best.value == "PostgreSQL"
    assert best.embedding_score > 0.9
    assert score > 0.35
    assert action_override is None
    assert "embedding_similarity" in evidence


def test_resolved_candidate_uses_llm_arbiter_choice(monkeypatch) -> None:
    settings = Settings(
        enable_embedding_retrieval=False,
        enable_correction_llm_arbiter=True,
        openai_api_key="test-key",
    )

    monkeypatch.setattr(correction_resolver, "_should_use_arbiter", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        correction_resolver,
        "_call_llm_arbiter",
        lambda **_kwargs: ArbiterChoice(
            decision="Neural IT",
            action="auto_correct",
            confidence=0.94,
            reason_code="verified_alias_match",
        ),
    )
    fake_profile = SimpleNamespace(id="profile-1")

    best, score, action_override, evidence = correction_resolver._resolved_candidate(
        None,
        fake_profile,
        "NeuralIT",
        field_type="company",
        section="work_experience",
        source_text="AI/ML Developer, NeuralIT, 2024 - Present",
        parser_confidence=0.62,
        candidates=[
            ResolverCandidate(value="Neural IT", source="canonical", fuzzy_score=0.83, graph_score=0.86, section_context_score=0.92),
            ResolverCandidate(value="Neural Institute", source="canonical", fuzzy_score=0.8, graph_score=0.72, section_context_score=0.92),
        ],
        settings=settings,
    )

    assert best is not None
    assert best.value == "Neural IT"
    assert score >= 0.94
    assert action_override == "auto_correct"
    assert "llm_arbiter:verified_alias_match" in evidence


def test_ollama_arbiter_parses_structured_response(monkeypatch) -> None:
    settings = Settings(
        enable_correction_llm_arbiter=True,
        correction_arbiter_provider="ollama",
        ollama_arbiter_model="qwen-local",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "response": json.dumps(
                        {
                            "decision": "PostgreSQL",
                            "action": "auto_correct",
                            "confidence": 0.93,
                            "reason_code": "verified_alias_match",
                        }
                    )
                }
            ).encode("utf-8")

    monkeypatch.setattr(correction_resolver.urllib_request, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    choice = correction_resolver._call_llm_arbiter(
        raw_value="postgres",
        field_type="skill",
        section="skills",
        source_text="Python, postgres, Docker",
        ranked_candidates=[
            ResolverCandidate(value="PostgreSQL", source="canonical", final_score=0.82, evidence=["alias"]),
            ResolverCandidate(value="Redis", source="canonical", final_score=0.77, evidence=["fuzzy"]),
        ],
        parser_confidence=0.58,
        settings=settings,
    )

    assert choice is not None
    assert choice.decision == "PostgreSQL"
    assert choice.action == "auto_correct"
    assert choice.confidence == 0.93


def test_local_correction_embedding_cache_backend(tmp_path, monkeypatch) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'local-cache.db'}",
        correction_embedding_provider="local",
        enable_embedding_retrieval=True,
    )

    class FloatLike:
        def __init__(self, value: float) -> None:
            self.value = value

        def __float__(self) -> float:
            return float(self.value)

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
            assert normalize_embeddings is True
            assert show_progress_bar is False
            vectors = []
            for text in texts:
                score = float(len(text))
                vectors.append([FloatLike(score), FloatLike(score / 10.0)])
            return vectors

    monkeypatch.setattr(embeddings, "SentenceTransformer", object)
    monkeypatch.setattr(embeddings, "_local_sentence_model", lambda *_args, **_kwargs: FakeModel())

    from app.db import init_engine, init_db, session_scope

    init_engine(settings.database_url)
    init_db()
    with session_scope() as session:
        first_vectors, first_stats = embeddings.ensure_correction_embeddings(
            session,
            profile_id="profile-1",
            texts=["postgres", "fast api"],
            settings=settings,
            embedding_kind="resolver:skill",
        )
        second_vectors, second_stats = embeddings.ensure_correction_embeddings(
            session,
            profile_id="profile-1",
            texts=["postgres", "fast api"],
            settings=settings,
            embedding_kind="resolver:skill",
        )

    assert len(first_vectors) == 2
    assert all(isinstance(value, float) for vector in first_vectors for value in vector)
    assert first_stats == {"hits": 0, "misses": 2}
    assert second_vectors == first_vectors
    assert second_stats == {"hits": 2, "misses": 0}


def test_skill_decision_keeps_reasonable_skill_when_dictionary_misses(monkeypatch) -> None:
    settings = Settings(
        enable_embedding_retrieval=False,
        enable_correction_llm_arbiter=False,
    )
    fake_profile = SimpleNamespace(id="profile-1")

    monkeypatch.setattr(correction_resolver, "_existing_canonical_values", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(correction_resolver, "_existing_rules", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(correction_resolver, "_entity_ruler", lambda: None)

    decision = correction_resolver._skill_decision(
        None,
        fake_profile,
        {"name": "PyMuPDF"},
        0.53,
        source_text="Python, PyMuPDF, OCR",
        settings=settings,
    )

    assert decision.corrected_value_json == {"name": "PyMuPDF"}
    assert decision.resolver_action == "keep"
    assert decision.resolver_confidence >= 0.66
    assert "parser_extracted_skill" in decision.resolver_evidence
