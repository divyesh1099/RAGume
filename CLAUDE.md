# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (includes dev extras for pytest/httpx)
pip install -e ".[dev]"

# Run dev server (auto-reload)
uvicorn app.main:create_app --factory --reload

# Run production-style server
./scripts/run_prod.sh

# Run all tests
pytest

# Run a single test file
pytest tests/test_mvp1_flow.py

# Run a single test by name
pytest tests/test_mvp1_flow.py::test_auth_pages_and_auto_profile_flow

# Run parser comparison script against a specific PDF
source .venv/bin/activate
python scripts/compare_resume_parsers.py /path/to/resume.pdf --expect-name "Name"
```

There is no linter configured. The project uses Python 3.12+.

## Architecture Overview

### Application Factory

`app/main.py` exports `create_app()`, which is the FastAPI application factory. All routes are defined inside this function as closures over `resolved_settings`. The app is created fresh for each test by passing a `Settings` instance with an in-memory or tmp SQLite database.

### Configuration

`app/config.py` defines a `Settings` pydantic-settings class. All settings are read from environment variables or `.env`. Settings are accessed via `get_settings()` (LRU-cached singleton) in production, or passed directly to `create_app(settings)` in tests. The `.env.example` shows every available key.

### Database

`app/db.py` manages a module-level SQLAlchemy engine and session factory. There is no migration framework — schema changes are handled by `_run_startup_migrations()` in `db.py`, which performs `ALTER TABLE` / `CREATE INDEX IF NOT EXISTS` at startup. SQLite WAL mode and foreign keys are enabled per-connection.

`init_db()` must be called before any route handlers run; `create_app()` calls it. Tests create a fresh database per test using a `tmp_path` fixture and `Settings(database_url=...)`.

### Data Model (models.py)

Key entities and their relationships:

- **User** → owns many **Profile** (1:N)
- **Profile** → owns many **Document**, **StructuredProfileClaim**, **CanonicalValue**, **CorrectionRule**, **CorrectionEmbedding**, **ClaimGroup**, **ProfileAnomaly** (1:N each)
- **Document** → has many **Chunk** (text windows), **Claim** (free-text evidence claims), **StructuredProfileClaim** (section-parsed fields) — all cascade-deleted with the document
- **Claim** → has one **ProfileClaim** (promoted to the profile claim store when approved)
- **ProfileGraphNode** / **ProfileGraphEdge** — a lightweight skill/entity graph rebuilt from approved claims

`profile_data` on `Profile` is a JSON blob containing the merged canonical profile (identity, skills, experience, education, etc.). This is what the wiki and overview endpoints read.

### Document Processing Pipeline (upload → profile update)

When a document is uploaded (`POST /documents/upload`), `auto_process_document()` in `main.py` runs this sequence:

1. `ingest_uploaded_document()` (services/documents.py) — saves file, extracts raw text (PDF via PyMuPDF/pypdf, docx via python-docx), creates `Document` + `Chunk` rows.
2. `extract_document_profile_insights()` (services/profile_memory.py) — runs the resume parser pipeline to extract structured fields (identity, skills, experience, etc.) and stores results in `document.parse_metadata["profile_insights"]`.
3. `sync_document_structured_profile_claims()` (services/profile_studio.py) — turns parser output into `StructuredProfileClaim` rows for review in Profile Studio.
4. `extract_claims_for_document()` (services/claim_extractor.py) — retrieves top-K chunks via hybrid search, extracts free-text evidence claims (heuristic or via LLM), deduplicates them.
5. All claims are auto-approved and written to `ProfileClaim`.
6. `sync_profile_graph()` (services/profile_graph.py) — rebuilds graph nodes/edges from approved claims.
7. `rebuild_profile_overview()` (services/profile_memory.py) — merges all document insights into `profile.profile_data`.

### Resume Parser Backends (services/parser_backends.py)

Two backends are available, selected via `RESUME_PARSER_BACKEND` or per-request `parser_backend` parameter:

- `layout_ner` (default): PyMuPDF layout parsing → local resume NER (`oksomu/resume-ner` via ONNX/transformers) → optional GPT formatter
- `docling_structured`: Docling section extraction → same NER + formatter pipeline (requires `pip install docling`)

`resolve_resume_parser_backend()` resolves `"auto"` to the best available backend.

### Retrieval (services/retrieval.py)

Hybrid retrieval combines three signals (weights configurable in settings):
- **BM25** lexical score (default weight 0.5)
- **Semantic** cosine similarity via OpenAI embeddings (default weight 0.35, disabled if no API key)
- **Structural** score based on section headers and action-verb density (default weight 0.15)

### Profile Studio (services/profile_studio.py)

Profile Studio is the review layer between raw parser output and the canonical profile. `StructuredProfileClaim` rows represent individual parsed fields (e.g., one row per job, one per skill). Users accept/edit/reject them in the UI. `save_canonical_profile_from_structured_claims()` merges accepted claims into `profile.profile_data`.

`maybe_record_correction_rule()` (services/correction_resolver.py) learns from user edits to auto-correct similar fields in future uploads.

### Claim Admission (services/claim_admission.py)

Before structured claims reach the review queue, `apply_claim_admission()` scores each one for quality and deduplication against existing canonical values. Claims that score below threshold get `admission_status = "reject_noise"` and are hidden from the review UI.

### Evidence Fusion (services/evidence_fusion.py)

`fuse_profile()` merges structured claims across multiple documents for the same section (e.g., deduplicating work entries that appear in both a resume and a cover letter). Called as part of the Profile Studio save flow.

### Authentication

Cookie-based session auth via `services/auth.py`. Sessions are stored as hashed tokens in the `user_sessions` table. `get_current_user` FastAPI dependency reads the `SESSION_COOKIE_NAME` cookie. Auth is required for all API routes except health and static pages.

### Frontend

Vanilla JS/HTML in `app/static/`. Pages:
- `index.html` — evidence upload and free-text claim review
- `profile.html` — Profile Studio (structured section review)
- `wiki.html` — approved profile wiki
- `job.html` — job description upload
- `benchmarks.html` — parser benchmark runner

Static files are served from `/assets/` via `StaticFiles`.

## Testing Patterns

Tests in `tests/` use `httpx.AsyncClient` with `httpx.ASGITransport(app=create_app(settings))`. Each test creates its own `Settings` with a tmp SQLite path and all LLM/NER features disabled:

```python
settings = Settings(
    database_url=f"sqlite:///{tmp_path / 'test.db'}",
    uploads_dir=str(tmp_path / "uploads"),
    enable_llm_extractor=False,
    enable_embedding_retrieval=False,
    enable_resume_ner=False,
    enable_resume_gpt_formatter=False,
)
app = create_app(settings)
```

This ensures tests run offline without model downloads or API calls.

## Feature Flags

The most impactful flags for development:

| Flag | Effect when `true` |
|---|---|
| `ENABLE_LLM_EXTRACTOR` | Uses OpenAI GPT for claim extraction (requires `OPENAI_API_KEY`) |
| `ENABLE_EMBEDDING_RETRIEVAL` | Adds semantic vector search to retrieval (requires `OPENAI_API_KEY`) |
| `ENABLE_RESUME_NER` | Loads the local `oksomu/resume-ner` ONNX model on startup |
| `ENABLE_RESUME_GPT_FORMATTER` | Calls OpenAI to clean up parser JSON output after NER |
| `ENABLE_CORRECTION_LLM_ARBITER` | Uses an LLM to arbitrate correction rule conflicts |
