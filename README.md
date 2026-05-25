# RAG Resume Customizer

This repo contains an MVP1 implementation of the resume profile engine:

`documents -> extracted profile review -> canonical profile memory -> wiki / JD context`

The current focus is high-quality evidence ingestion, fast section-wise review, and saving a clean canonical profile memory, with retrieval and claim tooling still available in the backend for later flows.

## What MVP1 does

- Upload source documents such as `.txt`, `.md`, `.json`, `.pdf`, and `.docx`
- Extract text and store it as an evidence record
- Parse resumes with a layout-aware PDF parser, local resume NER, optional GPT refinement, and validation output
- Turn parser output into reviewable section claims for identity, links, skills, education, work experience, projects, and certifications
- Review extracted profile sections in Profile Studio, then save a canonical profile memory
- Auto-update the extracted profile identity, links, skills, education, work experience, and projects from uploaded evidence
- Chunk the text for retrieval
- Retrieve the most claim-rich chunks from the evidence store using lexical, structural, and optional embedding signals
- Extract candidate profile claims from retrieved context
- Deduplicate near-identical claims before they clutter review
- Score evidence strength and overclaim risk for each claim
- Manually approve or reject claims
- Save approved claims to a canonical profile claim store
- Build a lightweight profile graph from approved claims, skills, metrics, documents, and categories
- Manage multiple profiles with isolated evidence, claims, graph output, and wiki pages
- Update profile names, delete evidence, and remove entire profiles when needed
- Use dedicated pages for Evidence, Job Description, and Wiki instead of a single long workspace

## Tech choices

- `FastAPI` for the API
- `SQLite` for local MVP storage
- Hybrid retrieval: lexical BM25 + structural ranking + optional OpenAI embeddings
- Optional `OpenAI` GPT formatter for section-wise JSON cleanup after local parsing
- Optional `OpenAI` claim extraction when `OPENAI_API_KEY` is available
- Heuristic extraction fallback so the MVP works without an LLM
- Optional GPT resume JSON formatter on top of the local parser
- Lightweight entity graph built from approved claims instead of full GraphRAG over raw docs

## Quickstart

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Start the API:

```bash
uvicorn app.main:create_app --factory --reload
```

3. Open the app:

`http://127.0.0.1:8000/`

Pages:

- `http://127.0.0.1:8000/` for evidence upload and claim review
- `http://127.0.0.1:8000/job` for pasting or uploading a job description
- `http://127.0.0.1:8000/wiki` for browsing the approved profile wiki
- `http://127.0.0.1:8000/benchmarks` for running the parser benchmark against a gold resume dataset

4. API docs remain available at:

`http://127.0.0.1:8000/docs`

## Environment variables

All settings are optional for local development.

```bash
DATABASE_URL=sqlite:///./data/app.db
UPLOADS_DIR=./data/uploads
BENCHMARK_DATASET_DIR=
BENCHMARK_REPORTS_DIR=./data/benchmark-reports
BENCHMARK_DEFAULT_LIMIT=12
MAX_CHUNK_CHARS=1200
CHUNK_OVERLAP_CHARS=160
CLAIM_CONTEXT_TOP_K=6
MAX_CLAIMS_PER_RUN=10
ENABLE_LLM_EXTRACTOR=false
ENABLE_EMBEDDING_RETRIEVAL=false
ENABLE_RESUME_NER=true
ENABLE_RESUME_GPT_FORMATTER=true
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
RESUME_FORMATTER_MODEL=
RESUME_NER_MODEL_ID=oksomu/resume-ner
RESUME_NER_CACHE_DIR=./data/model-cache
RESUME_NER_MAX_TOKENS=512
```

If resume cleanup is weaker than expected, first check `ENABLE_RESUME_GPT_FORMATTER=true` in `.env`.
If the home screen shows `Heuristic mode`, the most common cause is `ENABLE_LLM_EXTRACTOR=false` in `.env`.
If document cards show embeddings as disabled or failed, check `ENABLE_EMBEDDING_RETRIEVAL` and your `OPENAI_API_KEY`.
If you want parser-only resume extraction without API refinement, leave `ENABLE_RESUME_GPT_FORMATTER=false`.

## Core API flow

## Benchmarking

If you have a gold dataset such as `~/Downloads/ragume_benchmark_gold_v0`, set:

```bash
BENCHMARK_DATASET_DIR=/home/your-user/Downloads/ragume_benchmark_gold_v0
```

Then open:

`http://127.0.0.1:8000/benchmarks`

The benchmark runner:

- loads `gold_annotation_template.csv` as the source of truth
- resolves files using `sample_pdf_manifest.csv`
- runs the same extraction pipeline the app uses
- scores fields like skills, experience, education, projects, links, and core identity fields
- saves the latest report under `BENCHMARK_REPORTS_DIR`

You can also trigger it by API:

```bash
curl -X POST "http://127.0.0.1:8000/benchmark/run" \
  -H "Content-Type: application/json" \
  -d '{"parser_backend":"auto","limit":12,"allow_remote_models":false}'
```

And inspect the latest saved report:

```bash
curl "http://127.0.0.1:8000/benchmark/latest"
```

### 0. Create or list profiles

```bash
curl "http://127.0.0.1:8000/profiles"

curl -X POST "http://127.0.0.1:8000/profiles" \
  -H "Content-Type: application/json" \
  -d '{"name":"Document AI Profile"}'

curl -X PATCH "http://127.0.0.1:8000/profiles/<profile_id>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Profile Name"}'
```

### 1. Upload a document

```bash
curl -X POST "http://127.0.0.1:8000/documents/upload" \
  -F "profile_id=<profile_id>" \
  -F "parser_backend=auto" \
  -F "file=@sample_resume_source.txt"
```

### 2. Extract claims from retrieved evidence

```bash
curl -X POST "http://127.0.0.1:8000/documents/<document_id>/extract-claims?profile_id=<profile_id>" \
  -H "Content-Type: application/json" \
  -d '{"focus_areas":["python","rag","ocr"],"max_claims":8}'
```

### 3. Approve a claim

```bash
curl -X POST "http://127.0.0.1:8000/claims/<claim_id>/review?profile_id=<profile_id>" \
  -H "Content-Type: application/json" \
  -d '{"status":"approved"}'
```

### 4. View the profile database

```bash
curl "http://127.0.0.1:8000/profile/claims?profile_id=<profile_id>"
```

### 5. View the mini profile graph

```bash
curl "http://127.0.0.1:8000/profile/graph?profile_id=<profile_id>"
```

### 6. Delete evidence or a profile

```bash
curl -X DELETE "http://127.0.0.1:8000/documents/<document_id>?profile_id=<profile_id>"

curl -X DELETE "http://127.0.0.1:8000/profiles/<profile_id>"
```

### 7. Re-run the parser for an uploaded document

```bash
curl -X POST "http://127.0.0.1:8000/documents/<document_id>/reparse?profile_id=<profile_id>&parser_backend=auto"
```

### 7.5. Compare parser backends for one document

```bash
curl "http://127.0.0.1:8000/documents/<document_id>/parser-comparisons?profile_id=<profile_id>"

curl "http://127.0.0.1:8000/resume-parsers"
```

### 8. Parse a JD upload into text

```bash
curl -X POST "http://127.0.0.1:8000/job-description/parse" \
  -F "file=@job_description.pdf"
```

## Suggested next steps after MVP1

- Add OCR and image ingestion
- Add job description matching and explainable bullet selection
- Add wiki page generation from approved claims
- Add AI headshot and professional photo generation using submitted visual evidence
- Add a source-backed 3D face or full-body profile model using submitted photos and videos

## Parser Comparison

To compare the current parser against a Docling-backed parser and real OpenResume parser logic on one resume:

```bash
source .venv/bin/activate
python scripts/compare_resume_parsers.py /path/to/resume.pdf \
  --expect-name "Candidate Name" \
  --expect-email candidate@example.com \
  --expect-phone +15551234567 \
  --expect-work-count 3 \
  --expect-project-count 2 \
  --expect-education-count 1
```

The first OpenResume run will clone the official repository into `data/parser-cache/open-resume/` and install its npm dependencies. If you want to use the Docling comparison path on a fresh environment, install it with:

```bash
pip install docling --extra-index-url https://download.pytorch.org/whl/cpu
```
