from app.models import Document
from app.services.record_assembler import assemble_document_records


AI_RESUME_TEXT = """
DIVYESH VISHWAKARMA
divyeshvishwakarma.com | +91 99201 92856 | divyesh1099@gmail.com

SUMMARY
GenAI-oriented Python Engineer with 3.5 years of shipping AI production and cloud back-ends. Highlights: an LLM+OCR service at ~2 000 RPS, a naval demand-forecast engine, and FastPDF—an Agentic-AI tool that flags blanks/duplicates in 60k medical pages in 30 min.

SKILLS
Languages / Libs Python 3.9+, C#, SQL, Pandas, NumPy, PyTorch, TensorFlow | GenAI / NLP GPT-4o, Azure OpenAI, BERT, RoBERTa, T5, LangChain, LlamaIndex, LangGraph, AutoGen, CrewAI | Data / ML ARIMA, Prophet, XGBoost, Random Forest, MLflow, Weights&Biases | API / Back-end FastAPI, Flask, Django REST, ASP.NET Core, gRPC, Kafka, RabbitMQ | Cloud / DevOps Azure, AWS, GCP, Docker, GitHub Actions, Terraform, Helm

EXPERIENCE
Neural IT Pvt Ltd
Apr 2024 – Present
Senior Python / ML Engineer
Navi Mumbai

• Deployed GPT-4o + Tesseract-OCR pipeline on Azure AKS; 20k notes/day.
• FastPDF—Agentic-AI CLI & micro-service detecting blank/duplicate pages.
• Scaled MedDocClean and LLM chains behind a 12-service FastAPI mesh (Kafka + Redis).

Indian Navy Pal India
May 2023 – Feb 2024
Machine Learning Developer
Mumbai

• Hybrid ARIMA + HOLT-TSB engine cut stock-out penalties.
• Built REST & gRPC services with OAuth2 + rate-limit.
• Presented RoBERTa intent classifier and LangChain RAG to Naval HQ.

Zeus Learning
Jun 2022 – Mar 2023
Software Developer
Mumbai

• Refactored ASP.NET MVC & SQL.
• Migrated jQuery to Angular 13 + RxJS.
• Built Shopify GraphQL plug-ins boosting client GMV.

SELECTED PROJECTS
Bertify–LangChain + LlamaIndex Q&A bot on 50k naval docs (BLEU). Bertify | resumeCustomizer–Django + Gemini API web-app that auto-tailors CVs (500+ users). resumeCustomizer | dQueues–Python NSQ-style task queue, 20k jobs/min (bench). dQueues | Bulky Books–MVC e-commerce store (Stripe, Azure, CI/CD). BulkyBooks

EDUCATION
B.Tech. Computer Engineering, Bharati Vidyapeeth College of Engineering, Navi Mumbai First Class (GPA 8.34 / 10)
2018–2022

OPEN SOURCE & LEADERSHIP
Mentor – AnitaB.org Open Source Day 2021 (CHAOSS Augur).
Student Rep – BVCoE Council 2020–22; managed $4k tech-fest budget, 30 volunteers.
Freelance - six Shopify / Wix stores that generate > 1 M INR revenue for SMB.
""".strip()


FOCUSED_WEB_RESUME_TEXT = """
DIVYESH VISHWAKARMA

WORK EXPERIENCE
Software Developer in Zeus Learning (10 months)(01 Jun 2022 - 23 Mar 2023)
-Worked on Angular and Angular.js Components, Pipes and Forms.
-Worked on ASP.NET MVC API, JWT token, AWS Lambda and SQL Monitor.

Freelancing in MotiDivya (6 months)(01 Jan 2022 - 01 Jun 2022)
-Created and deployed Websites for 6 small business.

PROJECTS
Dumphy
MotiDivya • April 2023 -April 2023
• This was an ASP.NET Core and Angular E-Commerce web store for real estate management.
• Deployed using Firebase (https://dumphy-motidivya.web.app/).
• Repository URL (https://github.com/divyesh1099/dumphy).

Bulky Books
MotiDivya • February 2023 - March 2023
• It is an E-Commerce Web Store For Selling Books.
• Here is the open source project repository url https://github.com/divyesh1099/Bulky_MVC.

Missing Aircraft Locator:
• Assits Search and Resuce operation by Locating missing aircraft.
• Machine Learning | Scikit-Learn | Python | Numpy
""".strip()


def _document() -> Document:
    document = Document(
        profile_id="profile-1",
        filename="AI_Divyesh_Vishwakarma_Post_NeuralIT.pdf",
        storage_path="resume.pdf",
        source_type="upload",
        mime_type="application/pdf",
        checksum="checksum",
        extracted_text=AI_RESUME_TEXT,
        parse_metadata={"profile_focus": "ai_ml", "document_role": "latest_ai_resume"},
    )
    document.id = "doc-1"
    return document


def test_record_assembler_builds_experience_project_and_summary_frames() -> None:
    document = _document()
    insights = {
        "identity": {"summary": "Worked on Angular and SQL delivery for clients."},
        "work_experience": [],
        "projects": [],
        "education": [],
    }

    frames = assemble_document_records(document, insights)

    experience = frames["experience_frames"]
    assert len(experience) == 3
    assert experience[0]["organization"] == "Neural IT Pvt Ltd"
    assert experience[0]["title"] == "Senior Python / ML Engineer"
    assert experience[0]["end_date"] == "Present"
    assert any("FastPDF" in item for item in experience[0]["highlights"])
    assert "FastAPI" in experience[0]["technologies"]

    assert "Pal India" in experience[1]["organization"]
    assert experience[1]["title"] == "Machine Learning Developer"
    assert any("RoBERTa" in item for item in experience[1]["highlights"])

    assert experience[2]["organization"] == "Zeus Learning"
    assert experience[2]["title"] == "Software Developer"
    assert any("Angular" in item for item in experience[2]["highlights"])

    project_names = [frame["name"] for frame in frames["project_frames"]]
    assert project_names == ["Bertify", "resumeCustomizer", "dQueues", "Bulky Books"]
    assert "Python NSQ" not in project_names
    assert "app that auto" not in project_names

    leadership_names = [frame["name"] for frame in frames["leadership_frames"]]
    assert any(name.startswith("Mentor") for name in leadership_names)

    assert len(frames["summary_frames"]) == 1
    assert frames["summary_frames"][0]["text"].startswith("GenAI-oriented Python Engineer")


def test_record_assembler_handles_combined_headers_and_multiline_project_blocks() -> None:
    document = Document(
        profile_id="profile-2",
        filename="Divyesh_Vishwakarma_Resume_Work_Experience_Focussed.pdf",
        storage_path="resume.pdf",
        source_type="upload",
        mime_type="application/pdf",
        checksum="checksum-2",
        extracted_text=FOCUSED_WEB_RESUME_TEXT,
        parse_metadata={"profile_focus": "web_dev", "document_role": "work_experience_resume"},
    )
    document.id = "doc-2"

    frames = assemble_document_records(document, {"identity": {}, "work_experience": [], "projects": [], "education": []})

    experience = frames["experience_frames"]
    assert experience[0]["organization"] == "Zeus Learning"
    assert experience[0]["title"] == "Software Developer"
    assert experience[0]["start_date"] == "01 Jun 2022"
    assert experience[0]["end_date"] == "23 Mar 2023"
    assert any("Angular" in item for item in experience[0]["highlights"])

    assert experience[1]["organization"] == "MotiDivya"
    assert experience[1]["title"] == "Freelancing"

    project_names = [frame["name"] for frame in frames["project_frames"]]
    assert project_names == ["Dumphy", "Bulky Books", "Missing Aircraft Locator"]
    assert "MotiDivya • April 2023" not in project_names
    assert "Web Developer" not in project_names
    assert "N/A" not in project_names
