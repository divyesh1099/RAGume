from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _package_version() -> str:
    try:
        return version("rag-resume-customizer")
    except PackageNotFoundError:
        return "0.1.0"


def _split_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


class Settings(BaseSettings):
    app_name: str = "RAG Resume Customizer"
    app_env: str = "development"
    app_version: str = Field(default_factory=_package_version)
    public_base_url: str | None = None
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "info"
    allowed_hosts: str = "127.0.0.1,localhost,testserver"
    session_cookie_secure: bool | None = None
    session_cookie_domain: str | None = None
    session_cookie_samesite: str = "lax"
    max_upload_size_mb: int = Field(default=25, ge=1, le=200)
    gzip_minimum_size: int = Field(default=512, ge=100, le=500000)
    database_url: str = "sqlite:///./data/app.db"
    uploads_dir: str = "./data/uploads"
    benchmark_dataset_dir: str | None = None
    benchmark_reports_dir: str = "./data/benchmark-reports"
    benchmark_default_limit: int = Field(default=12, ge=1, le=500)
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

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_app_env(cls, value: str | None) -> str:
        cleaned = (value or "development").strip().lower()
        return cleaned or "development"

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str | None) -> str:
        cleaned = (value or "info").strip().lower()
        return cleaned or "info"

    @field_validator("public_base_url", mode="before")
    @classmethod
    def normalize_public_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip().rstrip("/")
        return cleaned or None

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def normalize_allowed_hosts(cls, value: str | None) -> str:
        if value is None:
            return "127.0.0.1,localhost,testserver"
        cleaned = str(value).strip()
        return cleaned or "127.0.0.1,localhost,testserver"

    @field_validator("session_cookie_secure", mode="before")
    @classmethod
    def normalize_cookie_secure(cls, value: bool | str | None) -> bool | None:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip().lower()
            if not cleaned:
                return None
            if cleaned in {"1", "true", "yes", "on"}:
                return True
            if cleaned in {"0", "false", "no", "off"}:
                return False
            raise ValueError("SESSION_COOKIE_SECURE must be true, false, or blank.")
        return bool(value)

    @field_validator("session_cookie_domain", mode="before")
    @classmethod
    def normalize_cookie_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @field_validator("session_cookie_samesite", mode="before")
    @classmethod
    def normalize_cookie_samesite(cls, value: str | None) -> str:
        cleaned = (value or "lax").strip().lower()
        if cleaned not in {"lax", "strict", "none"}:
            raise ValueError("SESSION_COOKIE_SAMESITE must be one of: lax, strict, none.")
        return cleaned

    @property
    def allowed_host_list(self) -> list[str]:
        parsed_hosts = _split_csv(self.allowed_hosts)
        if "*" in parsed_hosts:
            return ["*"]

        public_host = urlparse(self.public_base_url).hostname if self.public_base_url else None
        combined = [*parsed_hosts]
        if public_host:
            combined.append(public_host)
        if self.app_env != "production":
            combined.extend(["127.0.0.1", "localhost", "testserver"])

        deduped: list[str] = []
        for host in combined:
            if host and host not in deduped:
                deduped.append(host)
        return deduped or ["*"]

    @property
    def session_cookie_secure_effective(self) -> bool:
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        if self.public_base_url and self.public_base_url.startswith("https://"):
            return True
        return self.app_env in {"production", "staging", "demo"}

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
