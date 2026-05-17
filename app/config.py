from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RAG Resume Customizer"
    database_url: str = "sqlite:///./data/app.db"
    uploads_dir: str = "./data/uploads"
    resume_parser_backend: str = "auto"
    max_chunk_chars: int = Field(default=1200, ge=400, le=5000)
    chunk_overlap_chars: int = Field(default=160, ge=0, le=1000)
    claim_context_top_k: int = Field(default=6, ge=1, le=20)
    max_claims_per_run: int = Field(default=10, ge=1, le=30)
    enable_llm_extractor: bool = True
    enable_embedding_retrieval: bool = True
    enable_correction_llm_arbiter: bool = False
    enable_resume_ner: bool = True
    enable_resume_gpt_formatter: bool = False
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    correction_embedding_provider: str = "openai"
    correction_local_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    correction_local_embedding_cache_dir: str | None = "./data/model-cache"
    correction_arbiter_provider: str = "openai"
    correction_arbiter_model: str | None = None
    correction_arbiter_min_score: float = Field(default=0.65, ge=0.0, le=1.0)
    correction_arbiter_max_score: float = Field(default=0.9, ge=0.0, le=1.0)
    correction_arbiter_margin: float = Field(default=0.12, ge=0.0, le=1.0)
    correction_arbiter_candidate_limit: int = Field(default=4, ge=2, le=8)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_arbiter_model: str | None = None
    resume_formatter_model: str | None = None
    resume_ner_model_id: str = "oksomu/resume-ner"
    resume_ner_cache_dir: str | None = "./data/model-cache"
    resume_ner_max_tokens: int = Field(default=512, ge=128, le=512)
    hybrid_lexical_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    hybrid_semantic_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    hybrid_structural_weight: float = Field(default=0.15, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
