const page = document.body.dataset.page || "evidence";

const state = {
  user: null,
  profiles: [],
  selectedProfileId: window.localStorage.getItem("resume_workspace_profile_id") || null,
  parserBackends: [],
  selectedParserBackend: window.localStorage.getItem("resume_workspace_parser_backend") || null,
  parserComparisons: {},
  managedProfileId: null,
  summary: null,
  profileOverview: null,
  documents: [],
  selectedDocumentId: null,
  claims: [],
  approvedClaims: [],
  profileGraph: { nodes: [], edges: [] },
  retrievedChunks: [],
  lastExtractionMode: null,
  lastWarnings: [],
  jdText: window.localStorage.getItem("resume_workspace_jd") || "",
  wiki: { generated_at: null, articles: [] },
  currentArticleSlug: "profile",
  wikiQuery: "",
};

const presetFocusAreas = ["python", "rag", "ocr", "document ai", "backend", "llm", "ml", "automation"];
const AUTO_PARSER_BACKEND = {
  id: "auto",
  label: "Auto (Recommended)",
  description: "Uses Docling Structured for PDFs and images when available, and Layout + NER for text-like uploads.",
  available: true,
  is_default: true,
};
const parserRichMediaSuffixes = new Set(["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"]);
const jdStopwords = new Set([
  "about", "also", "and", "are", "build", "candidate", "company", "data", "experience", "from",
  "have", "help", "into", "looking", "must", "need", "our", "role", "team", "that", "their",
  "this", "using", "with", "will", "work", "you", "your",
]);

const elements = {
  toastRegion: document.querySelector("#toast-region"),
  authUserPill: document.querySelector("#auth-user-pill"),
  logoutButton: document.querySelector("#logout-button"),
  switchProfileButton: document.querySelector("#switch-profile-button"),

  loginForm: document.querySelector("#login-form"),
  loginEmail: document.querySelector("#login-email"),
  loginPassword: document.querySelector("#login-password"),
  loginButton: document.querySelector("#login-button"),

  registerForm: document.querySelector("#register-form"),
  registerName: document.querySelector("#register-name"),
  registerEmail: document.querySelector("#register-email"),
  registerPassword: document.querySelector("#register-password"),
  registerButton: document.querySelector("#register-button"),

  profileSelectorGrid: document.querySelector("#profile-selector-grid"),
  profileSelectMeta: document.querySelector("#profile-select-meta"),
  profileForm: document.querySelector("#profile-form"),
  profileNameInput: document.querySelector("#profile-name-input"),
  createProfileButton: document.querySelector("#create-profile-button"),
  profileUpdateForm: document.querySelector("#profile-update-form"),
  profileEditInput: document.querySelector("#profile-edit-input"),
  saveProfileButton: document.querySelector("#save-profile-button"),
  deleteProfileButton: document.querySelector("#delete-profile-button"),

  currentProfileName: document.querySelector("#current-profile-name"),
  currentProfileMeta: document.querySelector("#current-profile-meta"),
  metricDocuments: document.querySelector("#metric-documents"),
  metricPending: document.querySelector("#metric-pending"),
  metricApproved: document.querySelector("#metric-approved"),
  metricGraph: document.querySelector("#metric-graph"),
  engineSummary: document.querySelector("#engine-summary"),

  uploadForm: document.querySelector("#upload-form"),
  fileInput: document.querySelector("#file-input"),
  selectedFileLabel: document.querySelector("#selected-file-label"),
  uploadButton: document.querySelector("#upload-button"),
  parserBackendSelect: document.querySelector("#parser-backend-select"),
  parserBackendHint: document.querySelector("#parser-backend-hint"),
  dropzone: document.querySelector("#dropzone"),
  uploadStatus: document.querySelector("#upload-status"),
  selectedDocumentSummary: document.querySelector("#selected-document-summary"),
  selectedDocumentValidation: document.querySelector("#selected-document-validation"),
  selectedDocumentStructuredOutput: document.querySelector("#selected-document-structured-output"),
  selectedDocumentParserComparison: document.querySelector("#selected-document-parser-comparison"),
  deleteDocumentButton: document.querySelector("#delete-document-button"),
  reparseDocumentButton: document.querySelector("#reparse-document-button"),
  compareParsersButton: document.querySelector("#compare-parsers-button"),
  selectedDocumentSignals: document.querySelector("#selected-document-signals"),
  selectedDocumentHighlights: document.querySelector("#selected-document-highlights"),
  evidenceEmptyState: document.querySelector("#evidence-empty-state"),
  profileIdentityCard: document.querySelector("#profile-identity-card"),
  profileContactCard: document.querySelector("#profile-contact-card"),
  profileSkills: document.querySelector("#profile-skills"),
  profileExperienceList: document.querySelector("#profile-experience-list"),
  profileEducationList: document.querySelector("#profile-education-list"),
  profileProjectList: document.querySelector("#profile-project-list"),
  profileSourceList: document.querySelector("#profile-source-list"),
  focusInput: document.querySelector("#focus-input"),
  presetTags: document.querySelector("#preset-tags"),
  maxClaimsInput: document.querySelector("#max-claims-input"),
  extractButton: document.querySelector("#extract-button"),
  documentHint: document.querySelector("#document-hint"),
  documentList: document.querySelector("#document-list"),
  queueSummary: document.querySelector("#queue-summary"),
  claimList: document.querySelector("#claim-list"),
  approvedList: document.querySelector("#approved-list"),
  contextMeta: document.querySelector("#context-meta"),
  contextList: document.querySelector("#context-list"),
  graphMeta: document.querySelector("#graph-meta"),
  graphList: document.querySelector("#graph-list"),

  jdInput: document.querySelector("#jd-input"),
  jdFileInput: document.querySelector("#jd-file-input"),
  jdFileLabel: document.querySelector("#jd-file-label"),
  jdUploadButton: document.querySelector("#jd-upload-button"),
  jdSourceMeta: document.querySelector("#jd-source-meta"),
  analyzeJdButton: document.querySelector("#analyze-jd-button"),
  jdStatus: document.querySelector("#jd-status"),
  jdAngle: document.querySelector("#jd-angle"),
  jdAngleCopy: document.querySelector("#jd-angle-copy"),
  jdMatchedSkills: document.querySelector("#jd-matched-skills"),
  jdMissingTerms: document.querySelector("#jd-missing-terms"),
  jdMatchedClaims: document.querySelector("#jd-matched-claims"),
  jdProfileContext: document.querySelector("#jd-profile-context"),

  profileOverviewForm: document.querySelector("#profile-overview-form"),
  profileIdentityName: document.querySelector("#profile-identity-name"),
  profileIdentityHeadline: document.querySelector("#profile-identity-headline"),
  profileIdentityLocation: document.querySelector("#profile-identity-location"),
  profileIdentitySummary: document.querySelector("#profile-identity-summary"),
  profileEmailsInput: document.querySelector("#profile-emails-input"),
  profilePhonesInput: document.querySelector("#profile-phones-input"),
  profileLinksInput: document.querySelector("#profile-links-input"),
  profileSkillsInput: document.querySelector("#profile-skills-input"),
  saveProfileOverviewButton: document.querySelector("#save-profile-overview-button"),
  resetProfileOverviewButton: document.querySelector("#reset-profile-overview-button"),
  profileAutoExperience: document.querySelector("#profile-auto-experience"),
  profileAutoEducation: document.querySelector("#profile-auto-education"),
  profileAutoProjects: document.querySelector("#profile-auto-projects"),
  profileAutoCertifications: document.querySelector("#profile-auto-certifications"),
  profileAutoSources: document.querySelector("#profile-auto-sources"),

  wikiArticleCount: document.querySelector("#wiki-article-count"),
  wikiSearchInput: document.querySelector("#wiki-search-input"),
  wikiArticleList: document.querySelector("#wiki-article-list"),
  wikiTitle: document.querySelector("#wiki-title"),
  wikiLede: document.querySelector("#wiki-lede"),
  wikiGeneratedAt: document.querySelector("#wiki-generated-at"),
  wikiToc: document.querySelector("#wiki-toc"),
  wikiBody: document.querySelector("#wiki-body"),
  wikiInfobox: document.querySelector("#wiki-infobox"),
  wikiSources: document.querySelector("#wiki-sources"),
  wikiCategories: document.querySelector("#wiki-categories"),
  wikiRelated: document.querySelector("#wiki-related"),
  wikiReferences: document.querySelector("#wiki-references"),
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function showToast(message, type = "info") {
  if (!elements.toastRegion) {
    return;
  }
  const toast = document.createElement("div");
  toast.className = `toast${type === "error" ? " error" : ""}`;
  toast.textContent = message;
  elements.toastRegion.appendChild(toast);
  window.setTimeout(() => toast.remove(), 3600);
}

async function apiFetch(url, options = {}) {
  const config = {
    ...options,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers || {}) },
  };
  if (config.body && !(config.body instanceof FormData) && !config.headers["Content-Type"]) {
    config.headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, config);
  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.message || message;
    } catch {
      const text = await response.text();
      if (text) {
        message = text;
      }
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function setLoading(button, isLoading, label) {
  if (!button) {
    return;
  }
  if (isLoading) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = label;
    button.disabled = true;
    return;
  }
  button.textContent = button.dataset.originalLabel || button.textContent;
  button.disabled = false;
}

function formatDate(value) {
  if (!value) {
    return "Unknown time";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function confidencePercent(value) {
  return Math.round((value || 0) * 100);
}

function tokenize(text) {
  return String(text).toLowerCase().match(/[a-z0-9+#._-]+/g) || [];
}

function unique(values) {
  return [...new Set(values)];
}

function formatSectionLabel(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function currentProfile() {
  return state.profiles.find((profile) => profile.id === state.selectedProfileId) || null;
}

function managedProfile() {
  return state.profiles.find((profile) => profile.id === state.managedProfileId) || null;
}

function rememberSelectedProfile(profileId) {
  state.selectedProfileId = profileId;
  if (profileId) {
    window.localStorage.setItem("resume_workspace_profile_id", profileId);
    return;
  }
  window.localStorage.removeItem("resume_workspace_profile_id");
}

function rememberSelectedParserBackend(backendId) {
  state.selectedParserBackend = backendId;
  if (backendId) {
    window.localStorage.setItem("resume_workspace_parser_backend", backendId);
    return;
  }
  window.localStorage.removeItem("resume_workspace_parser_backend");
}

function parserBackendMeta(backendId) {
  if (backendId === AUTO_PARSER_BACKEND.id) {
    return AUTO_PARSER_BACKEND;
  }
  return state.parserBackends.find((item) => item.id === backendId) || null;
}

function defaultParserBackendId() {
  return AUTO_PARSER_BACKEND.id;
}

function ensureSelectedParserBackend() {
  if (
    state.selectedParserBackend
    && (
      state.selectedParserBackend === AUTO_PARSER_BACKEND.id
      || parserBackendMeta(state.selectedParserBackend)?.available
    )
  ) {
    return state.selectedParserBackend;
  }
  const nextBackend = defaultParserBackendId();
  rememberSelectedParserBackend(nextBackend);
  return nextBackend;
}

function selectedUploadFile() {
  return elements.fileInput?.files?.[0] || null;
}

function parserTargetLooksLikePdfOrImage({ filename = "", mimeType = "", parserName = "" } = {}) {
  const normalizedFilename = String(filename).toLowerCase();
  const suffix = normalizedFilename.includes(".") ? normalizedFilename.split(".").pop() : "";
  const normalizedMime = String(mimeType).toLowerCase();
  const normalizedParser = String(parserName).toLowerCase();
  return parserRichMediaSuffixes.has(suffix)
    || normalizedMime === "application/pdf"
    || normalizedMime.startsWith("image/")
    || normalizedParser.includes("pdf")
    || normalizedParser.includes("ocr");
}

function recommendedParserBackendIdForTarget({ filename = "", mimeType = "", parserName = "" } = {}) {
  const doclingAvailable = parserBackendMeta("docling_structured")?.available;
  if (doclingAvailable && parserTargetLooksLikePdfOrImage({ filename, mimeType, parserName })) {
    return "docling_structured";
  }
  return "layout_ner";
}

function parserRecommendationContext(document = getSelectedDocument()) {
  const file = selectedUploadFile();
  if (file) {
    return {
      scope: "file",
      label: file.name,
      filename: file.name,
      mimeType: file.type,
      parserName: "",
    };
  }
  if (document) {
    return {
      scope: "document",
      label: document.filename,
      filename: document.filename,
      mimeType: document.mime_type,
      parserName: document.parse_metadata?.parser || "",
    };
  }
  return {
    scope: "general",
    label: "",
    filename: "",
    mimeType: "",
    parserName: "",
  };
}

function recommendedParserBackendId(document = getSelectedDocument()) {
  return recommendedParserBackendIdForTarget(parserRecommendationContext(document));
}

function effectiveParserBackendId(document = getSelectedDocument()) {
  const selectedBackendId = ensureSelectedParserBackend();
  if (selectedBackendId !== AUTO_PARSER_BACKEND.id) {
    return selectedBackendId;
  }
  return recommendedParserBackendId(document);
}

function parserRecommendationHint(document = getSelectedDocument()) {
  const selectedBackendId = ensureSelectedParserBackend();
  if (selectedBackendId !== AUTO_PARSER_BACKEND.id) {
    const selectedBackend = parserBackendMeta(selectedBackendId);
    return selectedBackend
      ? `${selectedBackend.label}: ${selectedBackend.description}`
      : "Choose how resume-like evidence should be structured before it updates the profile.";
  }

  const context = parserRecommendationContext(document);
  const recommendedBackend = parserBackendMeta(recommendedParserBackendId(document));
  const targetLabel = context.scope === "file"
    ? `${context.label} will use`
    : context.scope === "document"
      ? `${context.label} would use`
      : "New uploads use";
  const reason = recommendedBackend?.id === "docling_structured"
    ? "because it looks like a PDF or image-heavy source."
    : "because it looks text-like and the lighter parser is faster."
  return `${AUTO_PARSER_BACKEND.label}: ${targetLabel} ${recommendedBackend?.label || "the recommended parser"} ${reason}`;
}

function currentParserBackendForDocument(document = getSelectedDocument()) {
  const backendId = document?.parse_metadata?.profile_parser_backend;
  return backendId && parserBackendMeta(backendId) ? backendId : null;
}

function withProfileQuery(path, extraParams = {}) {
  const url = new URL(path, window.location.origin);
  const profile = currentProfile();
  if (profile) {
    url.searchParams.set("profile_id", profile.id);
  }
  for (const [key, value] of Object.entries(extraParams)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return `${url.pathname}${url.search}`;
}

function getSelectedDocument() {
  return state.documents.find((document) => document.id === state.selectedDocumentId) || null;
}

function articleSlugForSourceDocument(documentName) {
  const normalized = String(documentName)
    .trim()
    .toLowerCase()
    .replaceAll(" ", "-")
    .replaceAll("_", "-")
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "");
  return `source-${normalized || "article"}`;
}

function focusAreas() {
  if (!elements.focusInput) {
    return [];
  }
  return elements.focusInput.value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function resetProfileScopedState() {
  state.summary = null;
  state.profileOverview = null;
  state.documents = [];
  state.selectedDocumentId = null;
  state.parserComparisons = {};
  state.claims = [];
  state.approvedClaims = [];
  state.profileGraph = { nodes: [], edges: [] };
  state.retrievedChunks = [];
  state.lastExtractionMode = null;
  state.lastWarnings = [];
  state.wiki = { generated_at: null, articles: [] };
  state.currentArticleSlug = "profile";
}

function renderUserIdentity() {
  if (elements.authUserPill) {
    elements.authUserPill.textContent = state.user?.full_name || "Account";
  }
}

function renderCurrentProfileMeta() {
  const profile = currentProfile();
  if (elements.currentProfileName) {
    elements.currentProfileName.textContent = profile?.name || "No profile selected";
  }
  if (elements.currentProfileMeta) {
    if (!profile) {
      elements.currentProfileMeta.textContent = "Choose a profile to enter the workspace.";
      return;
    }
    if (state.profileOverview) {
      elements.currentProfileMeta.textContent = `${state.profileOverview.documents_total} sources · ${state.profileOverview.work_experience.length} experience entries · ${state.profileOverview.projects.length} projects · ${state.profileOverview.skills.length} skills`;
      return;
    }
    const profileBits = [
      `${profile.document_count} source${profile.document_count === 1 ? "" : "s"}`,
      `${profile.work_experience_total || 0} experience`,
      `${profile.projects_total || 0} projects`,
      `${profile.skills_total || 0} skills`,
    ];
    elements.currentProfileMeta.textContent = profileBits.join(" · ");
  }
}

function renderParserBackendControls() {
  if (!elements.parserBackendSelect) {
    return;
  }

  ensureSelectedParserBackend();
  const options = [
    AUTO_PARSER_BACKEND,
    ...(state.parserBackends.length
      ? state.parserBackends
      : [{ id: "layout_ner", label: "Layout + NER", description: "Default parser.", available: true, is_default: true }]),
  ];

  elements.parserBackendSelect.innerHTML = options
    .map((backend) => `
      <option value="${escapeHtml(backend.id)}" ${backend.id === state.selectedParserBackend ? "selected" : ""} ${backend.available ? "" : "disabled"}>
        ${escapeHtml(backend.label)}${backend.id !== AUTO_PARSER_BACKEND.id && backend.is_default ? " (Default)" : ""}${backend.available ? "" : " (Unavailable)"}
      </option>
    `)
    .join("");

  if (elements.parserBackendHint) {
    elements.parserBackendHint.textContent = parserRecommendationHint();
  }
}

function renderSummary() {
  if (!state.summary) {
    return;
  }
  if (elements.metricDocuments) {
    elements.metricDocuments.textContent = String(state.summary.documents_total);
  }
  if (elements.metricPending) {
    elements.metricPending.textContent = String(state.summary.work_experience_total);
  }
  if (elements.metricApproved) {
    elements.metricApproved.textContent = String(state.summary.projects_total);
  }
  if (elements.metricGraph) {
    elements.metricGraph.textContent = String(state.summary.skills_total);
  }
  if (elements.engineSummary) {
    const selectedBackendId = ensureSelectedParserBackend();
    const effectiveBackend = parserBackendMeta(effectiveParserBackendId()) || parserBackendMeta(state.summary.parser_backend);
    const parserLabel = effectiveBackend?.label || "local parser";
    const extractorMode = state.summary.extractor_mode || "";
    const parserLead = selectedBackendId === AUTO_PARSER_BACKEND.id
      ? `Auto parser selection is on. The current source would use ${parserLabel}.`
      : `${parserLabel} is selected for uploads and re-runs.`;
    const extractorText = extractorMode.endsWith("_gpt")
      ? `${parserLead} Resume NER and GPT refinement are enabled.`
      : extractorMode.includes("_ner")
        ? `${parserLead} Resume NER is enabled.`
        : state.summary.llm_available
          ? `${parserLead} ${state.summary.openai_model} is available as fallback extraction.`
          : parserLead;
    const retrievalText = state.summary.embedding_retrieval_available
      ? ` Retrieval is enhanced with ${state.summary.openai_embedding_model}.`
      : " Retrieval currently uses lexical and structural matching only.";
    elements.engineSummary.textContent = `${extractorText}${retrievalText}`;
  }
}

function selectedDocumentInsights() {
  return getSelectedDocument()?.parse_metadata?.profile_insights || null;
}

function selectedDocumentValidation() {
  return getSelectedDocument()?.parse_metadata?.profile_validation || null;
}

function selectedDocumentDiagnostics() {
  return getSelectedDocument()?.parse_metadata?.profile_parser_diagnostics || null;
}

function selectedDocumentParserComparison() {
  const document = getSelectedDocument();
  if (!document) {
    return null;
  }
  return state.parserComparisons[document.id] || null;
}

function assessmentChip(assessment) {
  const label = String(assessment?.label || "weak").toLowerCase();
  const className = label === "strong" || label === "good"
    ? "success"
    : label === "moderate"
      ? "warning"
      : "danger";
  return `<span class="chip ${className}">${escapeHtml(label.toUpperCase())} evidence</span>`;
}

function statusChipClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "strong" || normalized === "usable" || normalized === "ok") {
    return "success";
  }
  if (normalized === "warning" || normalized === "review" || normalized === "needs_review") {
    return "warning";
  }
  return "danger";
}

function fieldPreviewCard(title, items) {
  return `
    <article class="detail-card">
      <div class="detail-card-title">${escapeHtml(title)}</div>
      ${items.length
        ? items.map((item) => `<div class="detail-line">${escapeHtml(item)}</div>`).join("")
        : '<div class="empty-inline">No data detected.</div>'}
    </article>
  `;
}

function comparisonPreviewLines(run) {
  const identity = run.insights?.identity || {};
  const summary = run.summary || {};
  const lines = [
    identity.full_name ? `Name: ${identity.full_name}` : null,
    identity.headline ? `Headline: ${identity.headline}` : null,
    (identity.emails || []).length ? `Emails: ${identity.emails.join(", ")}` : null,
    (identity.phones || []).length ? `Phones: ${identity.phones.join(", ")}` : null,
    summary.work_titles?.length ? `Work: ${summary.work_titles.slice(0, 2).join(" • ")}` : null,
    summary.project_names?.length ? `Projects: ${summary.project_names.slice(0, 3).join(", ")}` : null,
    summary.top_skills?.length ? `Skills: ${summary.top_skills.slice(0, 6).join(", ")}` : null,
  ].filter(Boolean);
  return lines.slice(0, 6);
}

function renderParserComparison() {
  if (!elements.selectedDocumentParserComparison) {
    return;
  }
  const document = getSelectedDocument();
  if (!document) {
    elements.selectedDocumentParserComparison.innerHTML = '<div class="empty-state">Select a document to compare parser outputs.</div>';
    if (elements.compareParsersButton) {
      elements.compareParsersButton.disabled = true;
    }
    return;
  }

  if (elements.compareParsersButton) {
    elements.compareParsersButton.disabled = false;
  }

  const comparison = selectedDocumentParserComparison();
  if (!comparison) {
    elements.selectedDocumentParserComparison.innerHTML = '<div class="empty-state">Run parser comparison to inspect side-by-side extraction quality for this source.</div>';
    return;
  }

  elements.selectedDocumentParserComparison.innerHTML = `
    <div class="comparison-grid">
      ${comparison.comparisons.map((run) => {
        const validation = run.diagnostics?.validation || {};
        const lines = comparisonPreviewLines(run);
        const counts = run.summary || {};
        const isActive = run.backend === comparison.active_backend;
        return `
          <article class="detail-card parser-run-card${isActive ? " is-active" : ""}">
            <div class="meta-row">
              <strong>${escapeHtml(run.label)}</strong>
              ${isActive ? '<span class="chip success">Active</span>' : '<span class="chip">Compare</span>'}
              ${validation.status ? `<span class="chip ${statusChipClass(validation.status)}">${escapeHtml(String(validation.status).replaceAll("_", " ").toUpperCase())}</span>` : ""}
            </div>
            <div class="subtle">${escapeHtml(run.description || "")}</div>
            ${run.error
              ? `<div class="detail-line warning-line">${escapeHtml(run.error)}</div>`
              : `
                <div class="tag-row">
                  <span class="tag">Work · ${escapeHtml(String(counts.work_count || 0))}</span>
                  <span class="tag">Projects · ${escapeHtml(String(counts.project_count || 0))}</span>
                  <span class="tag">Education · ${escapeHtml(String(counts.education_count || 0))}</span>
                  <span class="tag">Skills · ${escapeHtml(String(counts.skill_count || 0))}</span>
                </div>
                <div class="stack-list compact-stack">
                  ${lines.length
                    ? lines.map((line) => `<div class="detail-line">${escapeHtml(line)}</div>`).join("")
                    : '<div class="empty-inline">No structured fields returned.</div>'}
                </div>
                <div class="stack-list compact-stack">
                  ${(run.warnings || []).length
                    ? run.warnings.slice(0, 3).map((warning) => `<div class="detail-line warning-line">${escapeHtml(warning)}</div>`).join("")
                    : '<div class="detail-line">No major parser warnings recorded.</div>'}
                </div>
              `}
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderProfileSelector() {
  if (!elements.profileSelectorGrid) {
    return;
  }

  if (!state.profiles.length) {
    elements.profileSelectorGrid.innerHTML = '<div class="empty-state">No profiles yet. Create your first profile below.</div>';
    state.managedProfileId = null;
    updateManagedProfilePanel();
    return;
  }

  if (!state.managedProfileId || !state.profiles.some((profile) => profile.id === state.managedProfileId)) {
    state.managedProfileId = state.selectedProfileId && state.profiles.some((profile) => profile.id === state.selectedProfileId)
      ? state.selectedProfileId
      : state.profiles[0].id;
  }

  elements.profileSelectorGrid.innerHTML = state.profiles
    .map((profile) => {
      const initial = profile.name.trim().charAt(0).toUpperCase() || "P";
      const lastUsed = profile.id === state.selectedProfileId ? '<span class="tag">Last used</span>' : "";
      const subtitle = profile.headline || `${profile.sections_ready || 0} sections filled`;
      return `
        <article class="profile-selector-card${profile.id === state.managedProfileId ? " is-selected" : ""}" data-profile-card="${profile.id}">
          <div class="profile-card-avatar">${escapeHtml(initial)}</div>
          <div class="profile-card-body">
            <strong>${escapeHtml(profile.name)}</strong>
            <span>${escapeHtml(subtitle)}</span>
            <span>${profile.document_count} sources · ${profile.work_experience_total || 0} experience · ${profile.projects_total || 0} projects · ${profile.skills_total || 0} skills</span>
          </div>
          <div class="meta-row">${lastUsed}</div>
          <div class="profile-card-actions">
            <button class="profile-card-button" type="button" data-open-profile="${profile.id}">Open</button>
            <button class="profile-card-button" type="button" data-manage-profile="${profile.id}">Manage</button>
          </div>
        </article>
      `;
    })
    .join("");

  for (const card of elements.profileSelectorGrid.querySelectorAll("[data-profile-card]")) {
    card.addEventListener("click", (event) => {
      if (event.target.closest("[data-open-profile]") || event.target.closest("[data-manage-profile]")) {
        return;
      }
      state.managedProfileId = card.dataset.profileCard;
      renderProfileSelector();
      updateManagedProfilePanel();
    });
  }

  for (const button of elements.profileSelectorGrid.querySelectorAll("[data-open-profile]")) {
    button.addEventListener("click", () => openProfile(button.dataset.openProfile));
  }

  for (const button of elements.profileSelectorGrid.querySelectorAll("[data-manage-profile]")) {
    button.addEventListener("click", () => {
      state.managedProfileId = button.dataset.manageProfile;
      renderProfileSelector();
      updateManagedProfilePanel();
    });
  }

  updateManagedProfilePanel();
}

function updateManagedProfilePanel() {
  if (!elements.profileEditInput || !elements.profileSelectMeta || !elements.saveProfileButton || !elements.deleteProfileButton) {
    return;
  }
  const profile = managedProfile();
  if (!profile) {
    elements.profileSelectMeta.textContent = "Select a profile card to rename or delete it.";
    elements.profileEditInput.value = "";
    elements.profileEditInput.disabled = true;
    elements.saveProfileButton.disabled = true;
    elements.deleteProfileButton.disabled = true;
    return;
  }

  elements.profileSelectMeta.textContent = `${profile.document_count} sources · ${profile.sections_ready || 0} sections filled · ${profile.skills_total || 0} skills tracked`;
  elements.profileEditInput.value = profile.name;
  elements.profileEditInput.disabled = false;
  elements.saveProfileButton.disabled = false;
  elements.deleteProfileButton.disabled = state.profiles.length <= 1;
}

async function openProfile(profileId) {
  rememberSelectedProfile(profileId);
  window.location.href = "/";
}

function renderPresetTags() {
  if (!elements.presetTags) {
    return;
  }
  elements.presetTags.innerHTML = presetFocusAreas
    .map((tag) => `<button class="tag-button" type="button" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`)
    .join("");

  for (const button of elements.presetTags.querySelectorAll("[data-tag]")) {
    button.addEventListener("click", () => {
      if (!elements.focusInput) {
        return;
      }
      const current = focusAreas();
      const tag = button.dataset.tag;
      if (!current.includes(tag)) {
        current.push(tag);
        elements.focusInput.value = current.join(", ");
      }
    });
  }
}

function renderSelectedDocumentSummary() {
  if (!elements.selectedDocumentSummary) {
    return;
  }
  renderParserBackendControls();
  const document = getSelectedDocument();
  if (!document) {
    elements.selectedDocumentSummary.innerHTML = '<div class="empty-state">Pick a document to inspect it here.</div>';
    if (elements.deleteDocumentButton) {
      elements.deleteDocumentButton.disabled = true;
    }
    if (elements.reparseDocumentButton) {
      elements.reparseDocumentButton.disabled = true;
    }
    if (elements.selectedDocumentSignals) {
      elements.selectedDocumentSignals.innerHTML = '<span class="empty-inline">No source selected.</span>';
    }
    if (elements.selectedDocumentHighlights) {
      elements.selectedDocumentHighlights.innerHTML = '<div class="empty-state">Upload evidence to see what was detected from it.</div>';
    }
    if (elements.selectedDocumentValidation) {
      elements.selectedDocumentValidation.innerHTML = '<div class="empty-state">Parser validation will appear here after upload.</div>';
    }
    if (elements.selectedDocumentStructuredOutput) {
      elements.selectedDocumentStructuredOutput.innerHTML = '<div class="empty-state">Structured extraction fields will appear here after upload.</div>';
    }
    renderParserComparison();
    return;
  }

  const pageCount = document.parse_metadata?.page_count;
  const paragraphCount = document.parse_metadata?.paragraph_count;
  const activeBackendId = currentParserBackendForDocument(document);
  const activeBackend = parserBackendMeta(activeBackendId);
  const parseUnit = pageCount
    ? `${pageCount} pages`
    : paragraphCount
      ? `${paragraphCount} paragraphs`
      : document.parse_metadata?.parser || "parsed source";

  elements.selectedDocumentSummary.innerHTML = `
    <div class="selected-evidence-name">${escapeHtml(document.filename)}</div>
    <div class="selected-evidence-meta">${escapeHtml(parseUnit)} · ${escapeHtml(document.mime_type || "unknown type")}</div>
    <div class="selected-evidence-meta">${escapeHtml(formatDate(document.created_at))}</div>
    <div class="selected-evidence-meta">Parser backend: ${escapeHtml(activeBackend?.label || document.parse_metadata?.profile_parser_backend || "default")}</div>
    <div class="selected-evidence-meta">Structuring mode: ${escapeHtml(document.parse_metadata?.profile_extraction_mode || "auto")}</div>
    <div class="selected-evidence-meta">Embeddings: ${escapeHtml(document.parse_metadata?.embedding_status || "not indexed")}</div>
  `;
  if (elements.deleteDocumentButton) {
    elements.deleteDocumentButton.disabled = false;
  }
  if (elements.reparseDocumentButton) {
    elements.reparseDocumentButton.disabled = false;
  }

  const insights = selectedDocumentInsights();
  const validation = selectedDocumentValidation();
  const diagnostics = selectedDocumentDiagnostics();
  const signals = [];
  if (insights?.identity && Object.values(insights.identity || {}).some((value) => Array.isArray(value) ? value.length : value)) {
    signals.push("identity");
  }
  for (const key of ["skills", "education", "work_experience", "projects", "certifications"]) {
    if (insights?.[key]?.length) {
      signals.push(key.replaceAll("_", " "));
    }
  }
  if (elements.selectedDocumentSignals) {
    elements.selectedDocumentSignals.innerHTML = signals.length
      ? signals.map((signal) => `<span class="tag">${escapeHtml(signal)}</span>`).join("")
      : '<span class="empty-inline">No clear profile signals were detected yet.</span>';
  }

  if (elements.selectedDocumentHighlights) {
    const bullets = [];
    if (insights?.identity?.full_name) {
      bullets.push(`Name: ${insights.identity.full_name}`);
    }
    if (insights?.identity?.headline) {
      bullets.push(`Headline: ${insights.identity.headline}`);
    }
    if (insights?.work_experience?.length) {
      bullets.push(...insights.work_experience.slice(0, 2).map((item) => `${item.title || "Role"}${item.organization ? ` at ${item.organization}` : ""}`));
    }
    if (insights?.projects?.length) {
      bullets.push(...insights.projects.slice(0, 2).map((item) => item.name || "Project"));
    }
    elements.selectedDocumentHighlights.innerHTML = bullets.length
      ? bullets.map((bullet) => `<div class="insight-line">${escapeHtml(bullet)}</div>`).join("")
      : '<div class="empty-state">The profile engine will surface detected identity, experience, education, and project details here.</div>';
  }

  if (elements.selectedDocumentValidation) {
    const warnings = validation?.warnings || [];
    const checks = validation?.checks || [];
    const sections = diagnostics?.validation?.detected_sections || {};
    const layout = diagnostics?.layout || {};
    elements.selectedDocumentValidation.innerHTML = `
      <article class="detail-card">
        <div class="meta-row">
          <span class="chip ${statusChipClass(validation?.status)}">${escapeHtml(String(validation?.status || "review").replaceAll("_", " ").toUpperCase())}</span>
          <span class="chip">Score ${escapeHtml(String(validation?.score ?? "--"))}</span>
          <span class="chip">${escapeHtml(document.parse_metadata?.profile_extraction_mode || "parser")}</span>
        </div>
        <div class="meta-row">
          <span class="meta-text">${escapeHtml(parserBackendMeta(document.parse_metadata?.profile_parser_backend)?.label || document.parse_metadata?.profile_parser_backend || "parser backend")}</span>
          <span class="meta-text">${escapeHtml(layout.parser || document.parse_metadata?.parser || "parser")}</span>
          <span class="meta-text">${escapeHtml(String(layout.page_count || document.parse_metadata?.page_count || 0))} pages</span>
          <span class="meta-text">${escapeHtml(String(layout.block_count || document.parse_metadata?.block_count || 0))} blocks</span>
          <span class="meta-text">${escapeHtml(String(layout.link_count || document.parse_metadata?.link_count || 0))} links</span>
        </div>
        <div class="tag-row">
          ${Object.entries(sections).length
            ? Object.entries(sections).map(([section, count]) => `<span class="tag">${escapeHtml(formatSectionLabel(section))} · ${escapeHtml(String(count))}</span>`).join("")
            : '<span class="empty-inline">No structured sections detected.</span>'}
        </div>
        <div class="stack-list compact-stack">
          ${warnings.length
            ? warnings.map((warning) => `<div class="detail-line warning-line">${escapeHtml(warning)}</div>`).join("")
            : '<div class="detail-line">No major parser warnings for this document.</div>'}
        </div>
        <div class="detail-check-grid">
          ${checks.length
            ? checks.map((check) => `
                <div class="detail-check">
                  <span>${escapeHtml(formatSectionLabel(check.field))}</span>
                  <span class="chip ${statusChipClass(check.status)}">${escapeHtml(check.status.toUpperCase())}</span>
                </div>
              `).join("")
            : '<div class="empty-inline">No validation checks recorded.</div>'}
        </div>
      </article>
    `;
  }

  if (elements.selectedDocumentStructuredOutput) {
    const identity = insights?.identity || {};
    const workLines = (insights?.work_experience || []).slice(0, 3).map((item) => {
      const bits = [item.title, item.organization, [item.start_date, item.end_date].filter(Boolean).join(" - ")].filter(Boolean);
      return bits.join(" · ");
    });
    const educationLines = (insights?.education || []).slice(0, 3).map((item) => {
      const bits = [item.degree, item.institution, item.field_of_study].filter(Boolean);
      return bits.join(" · ");
    });
    const projectLines = (insights?.projects || []).slice(0, 3).map((item) => {
      const bits = [item.name, item.summary].filter(Boolean);
      return bits.join(" · ");
    });
    const identityLines = [
      identity.full_name ? `Name: ${identity.full_name}` : null,
      identity.headline ? `Headline: ${identity.headline}` : null,
      identity.location ? `Location: ${identity.location}` : null,
      identity.summary ? `Summary: ${identity.summary}` : null,
      (identity.emails || []).length ? `Emails: ${identity.emails.join(", ")}` : null,
      (identity.phones || []).length ? `Phones: ${identity.phones.join(", ")}` : null,
    ].filter(Boolean);
    const linkLines = (insights?.public_profiles || []).slice(0, 6).map((item) => `${item.label}: ${item.url}`);
    const skillLines = (insights?.skills || []).slice(0, 12);

    elements.selectedDocumentStructuredOutput.innerHTML = `
      <div class="detail-grid">
        ${fieldPreviewCard("Identity", identityLines)}
        ${fieldPreviewCard("Links", linkLines)}
        ${fieldPreviewCard("Skills", skillLines)}
        ${fieldPreviewCard("Work Experience", workLines)}
        ${fieldPreviewCard("Education", educationLines)}
        ${fieldPreviewCard("Projects", projectLines)}
      </div>
    `;
  }

  renderParserComparison();
}

function renderProfileOverviewSnapshot() {
  const overview = state.profileOverview;
  if (!overview) {
    return;
  }

  const identity = overview.identity || {};
  if (elements.profileIdentityCard) {
    elements.profileIdentityCard.innerHTML = `
      <div class="profile-block-title">${escapeHtml(identity.full_name || "No name detected yet")}</div>
      <div class="profile-block-subtitle">${escapeHtml(identity.headline || "Upload stronger profile evidence to capture a headline.")}</div>
      <p class="subtle">${escapeHtml(identity.summary || "A short summary will appear here after the app finds one in your uploaded evidence.")}</p>
    `;
  }

  if (elements.profileContactCard) {
    const contactLines = [];
    if (identity.location) {
      contactLines.push(`Location: ${identity.location}`);
    }
    if ((identity.emails || []).length) {
      contactLines.push(`Email: ${identity.emails.join(", ")}`);
    }
    if ((identity.phones || []).length) {
      contactLines.push(`Phone: ${identity.phones.join(", ")}`);
    }
    if ((overview.public_profiles || []).length) {
      contactLines.push(...overview.public_profiles.map((link) => `${link.label}: ${link.url}`));
    }
    elements.profileContactCard.innerHTML = contactLines.length
      ? contactLines.map((line) => `<div class="profile-line">${escapeHtml(line)}</div>`).join("")
      : '<div class="empty-state">Contact details and links will show up here when found in your evidence.</div>';
  }

  if (elements.profileSkills) {
    elements.profileSkills.innerHTML = overview.skills?.length
      ? overview.skills.map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")
      : '<span class="empty-inline">No skills extracted yet.</span>';
  }

  if (elements.profileExperienceList) {
    elements.profileExperienceList.innerHTML = overview.work_experience?.length
      ? overview.work_experience
          .slice(0, 5)
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.title || "Role")}</strong>
              <span>${escapeHtml(item.organization || "Organization not captured")}</span>
              <p>${escapeHtml(item.summary || "Details will expand as more evidence is uploaded.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Work experience will appear here after upload.</div>';
  }

  if (elements.profileEducationList) {
    elements.profileEducationList.innerHTML = overview.education?.length
      ? overview.education
          .slice(0, 4)
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.degree || "Education entry")}</strong>
              <span>${escapeHtml(item.institution || "Institution not captured")}</span>
              <p>${escapeHtml(item.field_of_study || item.summary || "Field or notes will appear here.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Education details will appear here after upload.</div>';
  }

  if (elements.profileProjectList) {
    elements.profileProjectList.innerHTML = overview.projects?.length
      ? overview.projects
          .slice(0, 5)
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.name || "Project")}</strong>
              <span>${escapeHtml((item.technologies || []).join(", ") || "Technology stack will appear here")}</span>
              <p>${escapeHtml(item.summary || "Project summary will appear here.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Projects will appear here after upload.</div>';
  }

  if (elements.profileSourceList) {
    elements.profileSourceList.innerHTML = overview.source_documents?.length
      ? overview.source_documents
          .map((source) => `
            <article class="source-entry">
              <strong>${escapeHtml(source.filename)}</strong>
              <span>${escapeHtml((source.signals || []).join(", ") || "general evidence")}</span>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Evidence sources will appear here after upload.</div>';
  }
}

function renderDocuments() {
  if (!elements.documentList) {
    return;
  }

  if (!state.documents.length) {
    elements.documentList.innerHTML = '<div class="empty-state">Uploaded documents will appear here.</div>';
    renderSelectedDocumentSummary();
    return;
  }

  elements.documentList.innerHTML = state.documents
    .map((document) => {
      const pageCount = document.parse_metadata?.page_count;
      const parser = document.parse_metadata?.parser || "parser";
      const parserBackend = parserBackendMeta(document.parse_metadata?.profile_parser_backend);
      const embeddingStatus = document.parse_metadata?.embedding_status || "not indexed";
      const parseUnit = pageCount
        ? `${pageCount} pages`
        : document.parse_metadata?.paragraph_count
          ? `${document.parse_metadata.paragraph_count} paragraphs`
          : parser;
      const metaLine = `${parserBackend?.label || document.parse_metadata?.profile_parser_backend || "Parser"} · ${parseUnit}`;

      return `
        <article class="document-card${document.id === state.selectedDocumentId ? " is-active" : ""}" data-document-id="${document.id}">
          <div class="document-title">${escapeHtml(document.filename)}</div>
          <div class="meta-text">${escapeHtml(metaLine)}</div>
          <div class="meta-row">
            <span class="chip">${escapeHtml(embeddingStatus)}</span>
            <span class="meta-text">${escapeHtml(formatDate(document.created_at))}</span>
          </div>
        </article>
      `;
    })
    .join("");

  for (const card of elements.documentList.querySelectorAll("[data-document-id]")) {
    card.addEventListener("click", () => {
      state.selectedDocumentId = card.dataset.documentId;
      renderDocuments();
      renderParserBackendControls();
      renderSelectedDocumentSummary();
    });
  }

  renderSelectedDocumentSummary();
}

function renderQueueSummary() {
  if (!elements.queueSummary) {
    return;
  }
  const document = getSelectedDocument();
  const pendingClaims = state.claims.filter((claim) => claim.status === "pending");
  const approvedClaims = state.claims.filter((claim) => claim.status === "approved");
  elements.queueSummary.textContent = document
    ? `${pendingClaims.length} pending · ${approvedClaims.length} already approved from this source`
    : "No document selected.";
}

function renderClaims() {
  if (!elements.claimList) {
    return;
  }

  const pendingClaims = state.claims.filter((claim) => claim.status === "pending");
  renderQueueSummary();

  if (!pendingClaims.length) {
    elements.claimList.innerHTML = '<div class="empty-state">No pending claims right now. Upload a document or run extraction for the selected source.</div>';
    return;
  }

  elements.claimList.innerHTML = pendingClaims
    .map((claim) => {
      const assessment = claim.evidence_assessment || {};
      const supportingChunks = (claim.supporting_chunks || [])
        .map(
          (chunk) => `
            <details>
              <summary>Evidence chunk ${escapeHtml(chunk.chunk_id.slice(0, 8))} · chars ${chunk.start_char}-${chunk.end_char}</summary>
              <div class="evidence-chunk">${escapeHtml(chunk.text)}</div>
            </details>
          `
        )
        .join("");

      return `
        <article class="claim-card">
          <div class="meta-row">
            <span class="chip">${escapeHtml(claim.category)}</span>
            <span class="meta-text">${confidencePercent(claim.confidence)}% confidence</span>
            ${assessmentChip(assessment)}
          </div>
          <div class="claim-text">${escapeHtml(claim.text)}</div>
          <div class="confidence-track" aria-hidden="true">
            <span style="width: ${confidencePercent(claim.confidence)}%"></span>
          </div>
          <div class="meta-row">
            <span class="meta-text">Risk: ${escapeHtml(assessment.overclaim_risk || "unknown")}</span>
            <span class="meta-text">Chunks: ${escapeHtml(String(assessment.support_chunk_count || 0))}</span>
            <span class="meta-text">${escapeHtml(claim.document_filename)}</span>
          </div>
          <div class="tag-row">
            ${(claim.skills || []).map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")}
          </div>
          ${claim.rationale ? `<div class="subtle">${escapeHtml(claim.rationale)}</div>` : ""}
          <div class="claim-actions">
            <button class="primary-button" type="button" data-review="approved" data-claim-id="${claim.id}">Approve</button>
            <button class="secondary-button danger-button" type="button" data-review="rejected" data-claim-id="${claim.id}">Reject</button>
          </div>
          ${supportingChunks || '<div class="empty-inline">No supporting chunks attached yet.</div>'}
        </article>
      `;
    })
    .join("");

  for (const button of elements.claimList.querySelectorAll("[data-review]")) {
    button.addEventListener("click", () => reviewClaim(button.dataset.claimId, button.dataset.review));
  }
}

function renderApprovedClaims() {
  if (!elements.approvedList) {
    return;
  }
  if (!state.approvedClaims.length) {
    elements.approvedList.innerHTML = '<div class="empty-state">Approved claims will appear here.</div>';
    return;
  }

  elements.approvedList.innerHTML = state.approvedClaims
    .map((claim) => {
      const evidenceCount = claim.evidence?.chunks?.length || 0;
      const sourceName = claim.evidence?.document_filename || "Source document";
      return `
        <article class="approved-card">
          <div class="meta-row">
            <span class="chip">${escapeHtml(claim.category)}</span>
            <span class="meta-text">${confidencePercent(claim.confidence)}% confidence</span>
            ${assessmentChip(claim.evidence_assessment || {})}
          </div>
          <div class="approved-text">${escapeHtml(claim.text)}</div>
          <div class="tag-row">
            ${(claim.skills || []).map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")}
          </div>
          <div class="meta-row">
            <span class="meta-text">${escapeHtml(sourceName)}</span>
            <span class="meta-text">${evidenceCount} evidence chunk${evidenceCount === 1 ? "" : "s"}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderContext() {
  if (!elements.contextList || !elements.contextMeta) {
    return;
  }

  if (!state.retrievedChunks.length) {
    elements.contextMeta.textContent = "No extraction yet.";
    elements.contextList.innerHTML = '<div class="empty-state">Run extraction to inspect the retrieved evidence pack.</div>';
    return;
  }

  const warningText = state.lastWarnings.length ? ` · ${state.lastWarnings.join(" ")}` : "";
  elements.contextMeta.textContent = `${(state.lastExtractionMode || "heuristic").toUpperCase()} context · ${state.retrievedChunks.length} chunks${warningText}`;

  elements.contextList.innerHTML = state.retrievedChunks
    .map(
      (chunk) => `
        <article class="context-card">
          <div class="meta-row">
            <span class="chip">Score ${chunk.score.toFixed(2)}</span>
            <span class="meta-text">${escapeHtml(chunk.filename)}</span>
          </div>
          <div class="meta-row">
            <span class="chip">Lexical ${Number(chunk.score_components?.lexical || 0).toFixed(2)}</span>
            <span class="chip">Semantic ${Number(chunk.score_components?.semantic || 0).toFixed(2)}</span>
            <span class="chip">Structural ${Number(chunk.score_components?.structural || 0).toFixed(2)}</span>
          </div>
          <div class="evidence-chunk">${escapeHtml(chunk.text)}</div>
        </article>
      `
    )
    .join("");
}

function renderProfileGraph() {
  if (!elements.graphList || !elements.graphMeta) {
    return;
  }

  const nodes = state.profileGraph.nodes || [];
  const edges = state.profileGraph.edges || [];
  if (!nodes.length) {
    elements.graphMeta.textContent = "No approved graph yet.";
    elements.graphList.innerHTML = '<div class="empty-state">Approve claims to build the profile graph.</div>';
    return;
  }

  const featureNodes = nodes.filter((node) => node.node_type !== "claim").slice(0, 8);
  const featureEdges = edges.slice(0, 6);
  elements.graphMeta.textContent = `${nodes.length} nodes · ${edges.length} relationships`;
  elements.graphList.innerHTML = `
    <article class="graph-card">
      <div class="tag-row">
        ${featureNodes.map((node) => `<span class="tag">${escapeHtml(node.label)} · ${escapeHtml(node.node_type)}</span>`).join("")}
      </div>
      <div class="graph-lines">
        ${featureEdges
          .map((edge) => {
            const source = nodes.find((node) => node.id === edge.source_node_id);
            const target = nodes.find((node) => node.id === edge.target_node_id);
            return `<div>${escapeHtml(source?.label || edge.source_node_id)} → ${escapeHtml(edge.relation_type.replaceAll("_", " "))} → ${escapeHtml(target?.label || edge.target_node_id)}</div>`;
          })
          .join("")}
      </div>
    </article>
  `;
}

function summarizeJobAngle(matchedSkills, jdText) {
  const lower = jdText.toLowerCase();
  if (matchedSkills.some((skill) => ["OCR", "Docling", "LayoutLMv3"].includes(skill)) || lower.includes("document ai")) {
    return {
      title: "Document AI / extraction angle",
      copy: "Your current profile already contains document-processing and extraction work that can anchor this application.",
    };
  }
  if (matchedSkills.some((skill) => ["RAG", "LLM", "OpenAI"].includes(skill))) {
    return {
      title: "LLM application angle",
      copy: "The strongest fit is around retrieval-backed AI workflows and grounded evidence handling.",
    };
  }
  if (matchedSkills.some((skill) => ["FastAPI", "Docker", "PostgreSQL", "Redis"].includes(skill))) {
    return {
      title: "Backend / platform angle",
      copy: "The clearest fit is backend systems and production pipeline work where Python services and infrastructure matter.",
    };
  }
  return {
    title: "General evidence-backed fit",
    copy: "The role overlaps with your current profile, but the strongest narrative depends on which experiences and projects you emphasize.",
  };
}

function analyzeJobDescription() {
  if (!elements.jdInput) {
    return;
  }

  const jdText = elements.jdInput.value.trim();
  state.jdText = jdText;
  window.localStorage.setItem("resume_workspace_jd", jdText);

  if (!jdText) {
    if (elements.jdStatus) {
      elements.jdStatus.textContent = "Waiting for a job description.";
    }
    if (elements.jdAngle) {
      elements.jdAngle.textContent = "No JD yet";
    }
    if (elements.jdAngleCopy) {
      elements.jdAngleCopy.textContent = "Paste or upload a role description to see where your current profile is strongest.";
    }
    if (elements.jdMatchedSkills) {
      elements.jdMatchedSkills.innerHTML = "";
    }
    if (elements.jdMissingTerms) {
      elements.jdMissingTerms.innerHTML = "";
    }
    if (elements.jdMatchedClaims) {
      elements.jdMatchedClaims.innerHTML = '<div class="empty-state">Matched profile entries will appear here.</div>';
    }
    return;
  }

  const jdTokens = tokenize(jdText).filter((token) => token.length > 2 && !jdStopwords.has(token));
  const overviewSkills = state.profileOverview?.skills || [];
  const claimSkills = unique(state.approvedClaims.flatMap((claim) => claim.skills || []));
  const approvedSkills = unique([...overviewSkills, ...claimSkills]);
  const matchedSkills = approvedSkills.filter((skill) => jdText.toLowerCase().includes(skill.toLowerCase()));

  const profileCorpus = [
    state.profileOverview?.identity?.headline,
    state.profileOverview?.identity?.summary,
    ...(state.profileOverview?.work_experience || []).flatMap((item) => [item.title, item.organization, item.summary, ...(item.highlights || [])]),
    ...(state.profileOverview?.projects || []).flatMap((item) => [item.name, item.summary, ...(item.technologies || [])]),
    ...(state.profileOverview?.education || []).flatMap((item) => [item.degree, item.institution, item.field_of_study]),
    ...state.approvedClaims.map((claim) => claim.text),
  ]
    .filter(Boolean)
    .join(" ");
  const profileTokenSet = new Set(tokenize(profileCorpus));

  const missingTerms = unique(jdTokens)
    .filter((token) => !profileTokenSet.has(token) && !matchedSkills.some((skill) => skill.toLowerCase() === token))
    .slice(0, 10);

  const rankedItems = [
    ...(state.profileOverview?.work_experience || []).map((item) => ({
      type: "experience",
      text: [item.title, item.organization, item.summary].filter(Boolean).join(" · "),
      skills: [],
      source: item.organization || "Work experience",
    })),
    ...(state.profileOverview?.projects || []).map((item) => ({
      type: "project",
      text: [item.name, item.summary].filter(Boolean).join(" · "),
      skills: item.technologies || [],
      source: "Project",
    })),
    ...state.approvedClaims.map((claim) => ({
      type: "claim",
      text: claim.text,
      skills: claim.skills || [],
      source: claim.evidence?.document_filename || "Approved evidence",
    })),
  ]
    .map((item) => {
      const claimTokens = new Set(tokenize(`${item.text} ${(item.skills || []).join(" ")}`));
      const overlap = jdTokens.filter((token) => claimTokens.has(token)).length;
      const skillOverlap = (item.skills || []).filter((skill) => jdText.toLowerCase().includes(skill.toLowerCase())).length;
      return { item, score: overlap + skillOverlap * 2 };
    })
    .filter((item) => item.score > 0 && item.item.text)
    .sort((left, right) => right.score - left.score)
    .slice(0, 6);

  const angle = summarizeJobAngle(matchedSkills, jdText);

  if (elements.jdStatus) {
    elements.jdStatus.textContent = `${matchedSkills.length} matched skills · ${missingTerms.length} uncovered terms`;
  }
  if (elements.jdAngle) {
    elements.jdAngle.textContent = angle.title;
  }
  if (elements.jdAngleCopy) {
    elements.jdAngleCopy.textContent = angle.copy;
  }
  if (elements.jdMatchedSkills) {
    elements.jdMatchedSkills.innerHTML = matchedSkills.length
      ? matchedSkills.map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")
      : '<span class="empty-inline">No matched skills yet.</span>';
  }
  if (elements.jdMissingTerms) {
    elements.jdMissingTerms.innerHTML = missingTerms.length
      ? missingTerms.map((term) => `<span class="tag">${escapeHtml(term)}</span>`).join("")
      : '<span class="empty-inline">No obvious uncovered terms were found.</span>';
  }
  if (elements.jdMatchedClaims) {
    elements.jdMatchedClaims.innerHTML = rankedItems.length
      ? rankedItems
          .map(
            ({ item, score }) => `
              <article class="match-card">
                <div class="meta-row">
                  <div class="match-title">${escapeHtml(item.text)}</div>
                  <span class="chip">Match ${score}</span>
                </div>
                <div class="tag-row">
                  ${(item.skills || []).map((skill) => `<span class="tag">${escapeHtml(skill)}</span>`).join("")}
                </div>
                <div class="meta-text">${escapeHtml(item.source)}</div>
              </article>
            `
          )
          .join("")
      : '<div class="empty-state">The current profile does not show strong overlap with this JD yet.</div>';
  }
  if (elements.jdProfileContext) {
    const identity = state.profileOverview?.identity || {};
    const profileSummaryBits = [
      identity.full_name,
      identity.headline,
      `${state.profileOverview?.work_experience?.length || 0} experience entries`,
      `${state.profileOverview?.projects?.length || 0} project entries`,
      `${approvedSkills.length} tracked skills`,
    ].filter(Boolean);
    elements.jdProfileContext.textContent = profileSummaryBits.join(" · ");
  }
}

function currentWikiArticle() {
  return state.wiki.articles.find((article) => article.slug === state.currentArticleSlug) || state.wiki.articles[0] || null;
}

function filteredWikiArticles() {
  const query = state.wikiQuery.trim().toLowerCase();
  if (!query) {
    return state.wiki.articles;
  }
  return state.wiki.articles.filter((article) => {
    const haystack = [
      article.title,
      article.lede,
      ...(article.categories || []),
      ...(article.source_documents || []),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderCitationLinks(referenceIds) {
  if (!referenceIds?.length) {
    return "";
  }
  const referencesById = Object.fromEntries((currentWikiArticle()?.references || []).map((reference) => [reference.id, reference]));
  return referenceIds
    .map((referenceId) => {
      const reference = referencesById[referenceId];
      const label = reference?.label || "?";
      return `<a class="wiki-citation" href="#${escapeHtml(referenceId)}">[${escapeHtml(label)}]</a>`;
    })
    .join("");
}

function renderWikiSidebar() {
  if (!elements.wikiArticleList || !elements.wikiArticleCount) {
    return;
  }
  const articles = filteredWikiArticles();
  elements.wikiArticleCount.textContent = `${articles.length} page${articles.length === 1 ? "" : "s"}`;

  if (!articles.length) {
    elements.wikiArticleList.innerHTML = '<div class="empty-state">Wiki pages will appear here.</div>';
    return;
  }

  elements.wikiArticleList.innerHTML = articles
    .map(
      (article) => `
        <button class="wiki-page-link${article.slug === state.currentArticleSlug ? " is-active" : ""}" type="button" data-article-slug="${article.slug}">
          <strong>${escapeHtml(article.title)}</strong>
          <span>${escapeHtml(article.lede)}</span>
        </button>
      `
    )
    .join("");

  for (const button of elements.wikiArticleList.querySelectorAll("[data-article-slug]")) {
    button.addEventListener("click", () => {
      state.currentArticleSlug = button.dataset.articleSlug;
      renderWiki();
    });
  }
}

function renderWiki() {
  if (!elements.wikiTitle) {
    return;
  }

  renderWikiSidebar();
  const article = currentWikiArticle();

  if (!article) {
    elements.wikiTitle.textContent = "Profile";
    elements.wikiLede.textContent = "No wiki content available yet.";
    elements.wikiBody.innerHTML = '<div class="empty-state">Upload evidence to build this wiki.</div>';
    elements.wikiInfobox.innerHTML = "";
    elements.wikiSources.innerHTML = "";
    elements.wikiCategories.innerHTML = "";
    elements.wikiRelated.innerHTML = "";
    elements.wikiReferences.innerHTML = '<li class="empty-state">No references listed yet.</li>';
    return;
  }

  elements.wikiTitle.textContent = article.title;
  elements.wikiLede.textContent = article.lede;
  elements.wikiGeneratedAt.textContent = state.wiki.generated_at ? `Updated ${formatDate(state.wiki.generated_at)}` : "Generated";
  elements.wikiToc.innerHTML = article.sections
    .map((section) => `<a class="wiki-source-link" href="#section-${escapeHtml(section.id)}">${escapeHtml(section.title)}</a>`)
    .join("");
  elements.wikiBody.innerHTML = article.sections
    .map(
      (section) => `
        <section id="section-${escapeHtml(section.id)}">
          <h3>${escapeHtml(section.title)}</h3>
          ${(section.paragraphs || []).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}
          ${(section.bullet_items || []).length
            ? `<ul>${section.bullet_items
                .map(
                  (item) => `
                    <li>
                      ${escapeHtml(item.text)}
                      ${renderCitationLinks(item.reference_ids)}
                    </li>
                  `
                )
                .join("")}</ul>`
            : ""}
        </section>
      `
    )
    .join("");
  elements.wikiInfobox.innerHTML = Object.entries(article.infobox || {})
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
  elements.wikiSources.innerHTML = article.source_documents?.length
    ? article.source_documents
        .map((documentName) => {
          const slug = articleSlugForSourceDocument(documentName);
          const hasArticle = state.wiki.articles.some((entry) => entry.slug === slug);
          return hasArticle
            ? `<a class="wiki-source-link" href="#" data-related-slug="${escapeHtml(slug)}"><strong>${escapeHtml(documentName)}</strong><span>Open source page</span></a>`
            : `<div class="wiki-source-link"><strong>${escapeHtml(documentName)}</strong><span>Source document</span></div>`;
        })
        .join("")
    : '<div class="empty-inline">No source documents listed.</div>';
  elements.wikiCategories.innerHTML = (article.categories || [])
    .map((category) => `<span class="tag">${escapeHtml(category)}</span>`)
    .join("");
  elements.wikiRelated.innerHTML = article.related_articles?.length
    ? article.related_articles
        .map(
          (related) => `
            <a class="wiki-related-link" href="#" data-related-slug="${escapeHtml(related.slug)}">
              <strong>${escapeHtml(related.title)}</strong>
              ${related.description ? `<span>${escapeHtml(related.description)}</span>` : ""}
            </a>
          `
        )
        .join("")
    : '<div class="empty-inline">No related pages listed.</div>';
  elements.wikiReferences.innerHTML = article.references?.length
    ? article.references
        .map(
          (reference) => `
            <li id="${escapeHtml(reference.id)}">
              <strong>[${escapeHtml(reference.label)}]</strong> ${escapeHtml(reference.title)}. ${escapeHtml(reference.document)}. ${escapeHtml(reference.excerpt)}
            </li>
          `
        )
        .join("")
    : '<li class="empty-state">No references listed yet.</li>';

  for (const link of document.querySelectorAll("[data-related-slug]")) {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      state.currentArticleSlug = link.dataset.relatedSlug;
      renderWiki();
    });
  }
}

function renderProfileEditor() {
  if (!elements.profileOverviewForm || !state.profileOverview) {
    return;
  }
  const identity = state.profileOverview.identity || {};
  if (elements.profileIdentityName) {
    elements.profileIdentityName.value = identity.full_name || "";
  }
  if (elements.profileIdentityHeadline) {
    elements.profileIdentityHeadline.value = identity.headline || "";
  }
  if (elements.profileIdentityLocation) {
    elements.profileIdentityLocation.value = identity.location || "";
  }
  if (elements.profileIdentitySummary) {
    elements.profileIdentitySummary.value = identity.summary || "";
  }
  if (elements.profileEmailsInput) {
    elements.profileEmailsInput.value = (identity.emails || []).join(", ");
  }
  if (elements.profilePhonesInput) {
    elements.profilePhonesInput.value = (identity.phones || []).join(", ");
  }
  if (elements.profileLinksInput) {
    elements.profileLinksInput.value = (state.profileOverview.public_profiles || [])
      .map((item) => item.url)
      .join("\n");
  }
  if (elements.profileSkillsInput) {
    elements.profileSkillsInput.value = (state.profileOverview.skills || []).join(", ");
  }

  if (elements.profileAutoExperience) {
    elements.profileAutoExperience.innerHTML = state.profileOverview.work_experience?.length
      ? state.profileOverview.work_experience
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.title || "Role")}</strong>
              <span>${escapeHtml(item.organization || "Organization not captured")}</span>
              <p>${escapeHtml(item.summary || "No extra summary yet.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Work experience entries will appear here after upload.</div>';
  }

  if (elements.profileAutoEducation) {
    elements.profileAutoEducation.innerHTML = state.profileOverview.education?.length
      ? state.profileOverview.education
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.degree || "Education entry")}</strong>
              <span>${escapeHtml(item.institution || "Institution not captured")}</span>
              <p>${escapeHtml(item.field_of_study || item.summary || "No extra notes yet.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Education entries will appear here after upload.</div>';
  }

  if (elements.profileAutoProjects) {
    elements.profileAutoProjects.innerHTML = state.profileOverview.projects?.length
      ? state.profileOverview.projects
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.name || "Project")}</strong>
              <span>${escapeHtml((item.technologies || []).join(", ") || "Technologies not captured")}</span>
              <p>${escapeHtml(item.summary || "No project summary yet.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Projects will appear here after upload.</div>';
  }

  if (elements.profileAutoCertifications) {
    elements.profileAutoCertifications.innerHTML = state.profileOverview.certifications?.length
      ? state.profileOverview.certifications
          .map((item) => `
            <article class="profile-entry-card">
              <strong>${escapeHtml(item.name || "Certification")}</strong>
              <span>${escapeHtml(item.issuer || "Issuer not captured")}</span>
              <p>${escapeHtml(item.summary || item.credential_id || "No extra details yet.")}</p>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Certifications will appear here after upload.</div>';
  }

  if (elements.profileAutoSources) {
    elements.profileAutoSources.innerHTML = state.profileOverview.source_documents?.length
      ? state.profileOverview.source_documents
          .map((item) => `
            <article class="source-entry">
              <strong>${escapeHtml(item.filename)}</strong>
              <span>${escapeHtml((item.signals || []).join(", ") || "general evidence")}</span>
            </article>
          `)
          .join("")
      : '<div class="empty-state">Source evidence will appear here after upload.</div>';
  }
}

async function loadProfileOverview() {
  state.profileOverview = await apiFetch(withProfileQuery("/profile/overview"));
  renderCurrentProfileMeta();
  renderProfileOverviewSnapshot();
  renderProfileEditor();
}

async function loadAuthSession() {
  const payload = await apiFetch("/auth/session");
  state.user = payload.user;
  renderUserIdentity();
}

async function loadProfiles() {
  state.profiles = await apiFetch("/profiles");
  if (state.selectedProfileId && !state.profiles.some((profile) => profile.id === state.selectedProfileId)) {
    rememberSelectedProfile(null);
  }
  if (state.managedProfileId && !state.profiles.some((profile) => profile.id === state.managedProfileId)) {
    state.managedProfileId = null;
  }
  renderCurrentProfileMeta();
  renderProfileSelector();
}

async function loadResumeParsers() {
  if (!elements.parserBackendSelect && page !== "evidence") {
    return;
  }
  state.parserBackends = await apiFetch("/resume-parsers");
  ensureSelectedParserBackend();
  renderParserBackendControls();
  renderSummary();
}

async function loadSummary() {
  state.summary = await apiFetch(withProfileQuery("/dashboard/summary"));
  renderSummary();
}

async function loadDocuments() {
  state.documents = await apiFetch(withProfileQuery("/documents"));
  state.parserComparisons = Object.fromEntries(
    Object.entries(state.parserComparisons).filter(([documentId]) =>
      state.documents.some((document) => document.id === documentId)
    )
  );
  if (!state.selectedDocumentId && state.documents.length) {
    state.selectedDocumentId = state.documents[0].id;
  }
  if (state.selectedDocumentId && !state.documents.some((document) => document.id === state.selectedDocumentId)) {
    state.selectedDocumentId = state.documents[0]?.id || null;
  }
  renderDocuments();
}

async function loadClaimsForSelection() {
  if (!elements.claimList) {
    return;
  }
  if (!state.selectedDocumentId) {
    state.claims = [];
    renderClaims();
    return;
  }
  state.claims = await apiFetch(withProfileQuery(`/documents/${state.selectedDocumentId}/claims`));
  renderClaims();
}

async function loadApprovedClaims() {
  state.approvedClaims = await apiFetch(withProfileQuery("/profile/claims"));
  renderApprovedClaims();
}

async function loadProfileGraph() {
  state.profileGraph = await apiFetch(withProfileQuery("/profile/graph"));
  renderProfileGraph();
}

async function loadWiki() {
  state.wiki = await apiFetch(withProfileQuery("/profile/wiki"));
  if (!state.wiki.articles.some((article) => article.slug === state.currentArticleSlug)) {
    state.currentArticleSlug = state.wiki.articles[0]?.slug || "profile";
  }
  renderWiki();
}

async function refreshEvidencePage() {
  await Promise.all([loadResumeParsers(), loadSummary(), loadDocuments(), loadProfileOverview()]);
  renderSelectedDocumentSummary();
}

async function refreshJobPage() {
  await Promise.all([loadSummary(), loadProfileOverview(), loadApprovedClaims()]);
  analyzeJobDescription();
}

async function refreshWikiPage() {
  await Promise.all([loadSummary(), loadProfileOverview(), loadWiki()]);
}

async function refreshProfilePage() {
  await Promise.all([loadSummary(), loadProfileOverview()]);
}

async function logout() {
  try {
    await apiFetch("/auth/logout", { method: "POST" });
  } catch {
    // Ignore logout errors and continue redirecting.
  }
  rememberSelectedProfile(null);
  window.location.href = "/login";
}

async function handleLogin(event) {
  event.preventDefault();
  try {
    setLoading(elements.loginButton, true, "Signing in...");
    await apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: elements.loginEmail.value.trim(),
        password: elements.loginPassword.value,
      }),
    });
    window.location.href = "/profiles/select";
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.loginButton, false, "Log In");
  }
}

async function handleRegister(event) {
  event.preventDefault();
  try {
    setLoading(elements.registerButton, true, "Creating...");
    await apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        full_name: elements.registerName.value.trim(),
        email: elements.registerEmail.value.trim(),
        password: elements.registerPassword.value,
      }),
    });
    window.location.href = "/profiles/select";
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.registerButton, false, "Create Account");
  }
}

async function createProfileSubmit(event) {
  event.preventDefault();
  const name = elements.profileNameInput?.value.trim();
  if (!name) {
    showToast("Enter a profile name first.", "error");
    return;
  }

  try {
    setLoading(elements.createProfileButton, true, "Creating...");
    const createdProfile = await apiFetch("/profiles", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    if (elements.profileNameInput) {
      elements.profileNameInput.value = "";
    }
    state.managedProfileId = createdProfile.id;
    if (!state.selectedProfileId) {
      rememberSelectedProfile(createdProfile.id);
    }
    await loadProfiles();
    showToast(`Created profile ${createdProfile.name}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.createProfileButton, false, "Create profile");
  }
}

async function updateManagedProfile(event) {
  event.preventDefault();
  const profile = managedProfile();
  if (!profile) {
    showToast("Select a profile to edit.", "error");
    return;
  }

  const nextName = elements.profileEditInput?.value.trim();
  if (!nextName) {
    showToast("Enter a profile name before saving.", "error");
    return;
  }
  if (nextName === profile.name) {
    return;
  }

  try {
    setLoading(elements.saveProfileButton, true, "Saving...");
    await apiFetch(`/profiles/${profile.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name: nextName }),
    });
    await loadProfiles();
    showToast("Profile updated.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.saveProfileButton, false, "Save changes");
  }
}

async function deleteManagedProfile() {
  const profile = managedProfile();
  if (!profile) {
    showToast("Select a profile to delete.", "error");
    return;
  }
  if (state.profiles.length <= 1) {
    showToast("At least one profile must remain.", "error");
    return;
  }

  const confirmed = window.confirm(
    `Delete profile "${profile.name}" and all of its evidence, profile data, and wiki output? This cannot be undone.`
  );
  if (!confirmed) {
    return;
  }

  try {
    setLoading(elements.deleteProfileButton, true, "Deleting...");
    await apiFetch(`/profiles/${profile.id}`, { method: "DELETE" });
    if (state.selectedProfileId === profile.id) {
      rememberSelectedProfile(null);
    }
    state.managedProfileId = null;
    await loadProfiles();
    showToast(`Deleted profile ${profile.name}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.deleteProfileButton, false, "Delete profile");
  }
}

async function uploadEvidence(event) {
  event.preventDefault();
  const file = elements.fileInput?.files?.[0];
  const profile = currentProfile();
  if (!file) {
    showToast("Pick a file before uploading.", "error");
    return;
  }
  if (!profile) {
    showToast("Choose a profile first.", "error");
    window.location.href = "/profiles/select";
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("profile_id", profile.id);
  formData.append("parser_backend", ensureSelectedParserBackend());

  try {
    setLoading(elements.uploadButton, true, "Uploading...");
    const response = await apiFetch("/documents/upload", {
      method: "POST",
      body: formData,
    });
    delete state.parserComparisons[response.document.id];
    state.selectedDocumentId = response.document.id;
    if (elements.fileInput) {
      elements.fileInput.value = "";
    }
    if (elements.selectedFileLabel) {
      elements.selectedFileLabel.textContent = "Nothing selected yet.";
    }
    await refreshEvidencePage();
    if (elements.uploadStatus) {
      const detected = response.auto_profile_sections?.length
        ? `Updated ${response.auto_profile_sections.map(formatSectionLabel).join(", ")}.`
        : "Upload completed, but only light profile signals were found.";
      elements.uploadStatus.textContent = `${detected} The current profile was refreshed automatically.`;
    }
    const warningCopy = response.warnings?.length ? ` ${response.warnings.join(" ")}` : "";
    showToast(`Uploaded ${response.document.filename}. The profile was updated automatically.${warningCopy}`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.uploadButton, false, "Upload evidence");
  }
}

async function extractClaims() {
  if (!state.selectedDocumentId) {
    showToast("Select a document first.", "error");
    return;
  }

  try {
    setLoading(elements.extractButton, true, "Extracting...");
    const response = await apiFetch(withProfileQuery(`/documents/${state.selectedDocumentId}/extract-claims`), {
      method: "POST",
      body: JSON.stringify({
        focus_areas: focusAreas(),
        max_claims: Number(elements.maxClaimsInput?.value || 8),
      }),
    });

    state.retrievedChunks = response.retrieved_chunks || [];
    state.lastExtractionMode = response.extractor_mode;
    state.lastWarnings = response.warnings || [];

    await Promise.all([loadSummary(), loadClaimsForSelection(), loadApprovedClaims(), loadProfileGraph()]);
    renderContext();
    showToast(
      response.claims.length
        ? `Created ${response.claims.length} new claim${response.claims.length === 1 ? "" : "s"} using ${response.extractor_mode}.`
        : "No new claims were created. Try different focus areas or check if similar claims already exist."
    );
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.extractButton, false, "Extract claims");
  }
}

async function reviewClaim(claimId, status) {
  try {
    await apiFetch(withProfileQuery(`/claims/${claimId}/review`), {
      method: "POST",
      body: JSON.stringify({ status }),
    });
    await Promise.all([loadSummary(), loadClaimsForSelection(), loadApprovedClaims(), loadProfileGraph()]);
    showToast(status === "approved" ? "Claim approved and saved to the profile." : "Claim rejected from the profile.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteSelectedDocument() {
  const document = getSelectedDocument();
  if (!document) {
    showToast("Select a document before deleting evidence.", "error");
    return;
  }

  const confirmed = window.confirm(
    `Delete evidence "${document.filename}" and remove the profile data derived from it? This cannot be undone.`
  );
  if (!confirmed) {
    return;
  }

  try {
    setLoading(elements.deleteDocumentButton, true, "Deleting...");
    await apiFetch(withProfileQuery(`/documents/${document.id}`), { method: "DELETE" });
    delete state.parserComparisons[document.id];
    if (state.selectedDocumentId === document.id) {
      state.selectedDocumentId = null;
    }
    state.retrievedChunks = [];
    state.lastExtractionMode = null;
    state.lastWarnings = [];
    await refreshEvidencePage();
    showToast(`Deleted evidence ${document.filename}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.deleteDocumentButton, false, "Delete Evidence");
  }
}

async function reparseSelectedDocument() {
  const document = getSelectedDocument();
  if (!document) {
    showToast("Select a document before re-running the parser.", "error");
    return;
  }

  try {
    setLoading(elements.reparseDocumentButton, true, "Re-running...");
    const response = await apiFetch(withProfileQuery(`/documents/${document.id}/reparse`, {
      parser_backend: ensureSelectedParserBackend(),
    }), {
      method: "POST",
    });
    delete state.parserComparisons[document.id];
    state.selectedDocumentId = response.document.id;
    await refreshEvidencePage();
    if (elements.uploadStatus) {
      const detected = response.auto_profile_sections?.length
        ? `Updated ${response.auto_profile_sections.map(formatSectionLabel).join(", ")}.`
        : "Parser completed, but only light profile signals were found.";
      elements.uploadStatus.textContent = `${detected} The current profile was refreshed automatically.`;
    }
    showToast(`Re-ran the parser for ${response.document.filename}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.reparseDocumentButton, false, "Re-run Parser");
  }
}

async function compareSelectedDocumentParsers() {
  const document = getSelectedDocument();
  if (!document) {
    showToast("Select a document before comparing parsers.", "error");
    return;
  }

  try {
    setLoading(elements.compareParsersButton, true, "Comparing...");
    const response = await apiFetch(withProfileQuery(`/documents/${document.id}/parser-comparisons`));
    state.parserComparisons[document.id] = response;
    renderParserComparison();
    showToast(`Compared ${response.comparisons.length} parser outputs for ${document.filename}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.compareParsersButton, false, "Compare Parsers");
  }
}

async function uploadJobDescriptionFile() {
  const file = elements.jdFileInput?.files?.[0];
  if (!file) {
    showToast("Choose a JD file before uploading.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  try {
    setLoading(elements.jdUploadButton, true, "Parsing...");
    const response = await apiFetch("/job-description/parse", {
      method: "POST",
      body: formData,
    });
    if (elements.jdInput) {
      elements.jdInput.value = response.text;
    }
    if (elements.jdSourceMeta) {
      const parser = response.parse_metadata?.parser || "parser";
      const pageCount = response.parse_metadata?.page_count;
      const paragraphCount = response.parse_metadata?.paragraph_count;
      const unit = pageCount
        ? `${pageCount} pages`
        : paragraphCount
          ? `${paragraphCount} paragraphs`
          : parser;
      elements.jdSourceMeta.textContent = `Loaded ${response.filename} using ${parser}${unit !== parser ? ` · ${unit}` : ""}.`;
    }
    analyzeJobDescription();
    showToast(`Loaded job description from ${response.filename}.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.jdUploadButton, false, "Upload JD file");
  }
}

async function saveProfileOverview(event) {
  event.preventDefault();
  try {
    setLoading(elements.saveProfileOverviewButton, true, "Saving...");
    const payload = {
      identity: {
        full_name: elements.profileIdentityName?.value.trim() || null,
        headline: elements.profileIdentityHeadline?.value.trim() || null,
        location: elements.profileIdentityLocation?.value.trim() || null,
        summary: elements.profileIdentitySummary?.value.trim() || null,
        emails: (elements.profileEmailsInput?.value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        phones: (elements.profilePhonesInput?.value || "")
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      },
      skills: (elements.profileSkillsInput?.value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      public_profiles: (elements.profileLinksInput?.value || "")
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean)
        .map((url) => ({ label: "Link", url })),
    };
    state.profileOverview = await apiFetch(withProfileQuery("/profile/overview"), {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    renderProfileOverviewSnapshot();
    renderProfileEditor();
    await loadSummary();
    showToast("Saved profile edits.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.saveProfileOverviewButton, false, "Save profile");
  }
}

async function resetProfileOverviewEdits() {
  const confirmed = window.confirm("Reset manual profile edits and return to the auto-extracted profile?");
  if (!confirmed) {
    return;
  }

  try {
    setLoading(elements.resetProfileOverviewButton, true, "Resetting...");
    state.profileOverview = await apiFetch(withProfileQuery("/profile/overview/manual"), {
      method: "DELETE",
    });
    renderProfileOverviewSnapshot();
    renderProfileEditor();
    await loadSummary();
    showToast("Manual profile edits were reset.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.resetProfileOverviewButton, false, "Reset to auto");
  }
}

function bindSharedWorkspaceActions() {
  elements.logoutButton?.addEventListener("click", logout);
  elements.switchProfileButton?.addEventListener("click", () => {
    window.location.href = "/profiles/select";
  });
}

function bindEvidencePage() {
  bindSharedWorkspaceActions();

  elements.uploadForm?.addEventListener("submit", uploadEvidence);
  elements.deleteDocumentButton?.addEventListener("click", deleteSelectedDocument);
  elements.reparseDocumentButton?.addEventListener("click", reparseSelectedDocument);
  elements.compareParsersButton?.addEventListener("click", compareSelectedDocumentParsers);
  elements.parserBackendSelect?.addEventListener("change", () => {
    rememberSelectedParserBackend(elements.parserBackendSelect.value);
    renderParserBackendControls();
    renderSummary();
  });

  if (elements.fileInput) {
    elements.fileInput.addEventListener("change", () => {
      const file = elements.fileInput.files?.[0];
      if (elements.selectedFileLabel) {
        elements.selectedFileLabel.textContent = file ? `${file.name} is ready to upload.` : "Nothing selected yet.";
      }
      renderParserBackendControls();
      renderSummary();
    });
  }
  if (elements.dropzone) {
    for (const eventName of ["dragenter", "dragover"]) {
      elements.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        elements.dropzone.classList.add("is-dragover");
      });
    }
    for (const eventName of ["dragleave", "drop"]) {
      elements.dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        elements.dropzone.classList.remove("is-dragover");
      });
    }
    elements.dropzone.addEventListener("drop", (event) => {
      const files = event.dataTransfer?.files;
      if (files?.length && elements.fileInput) {
        elements.fileInput.files = files;
        if (elements.selectedFileLabel) {
          elements.selectedFileLabel.textContent = `${files[0].name} is ready to upload.`;
        }
        renderParserBackendControls();
        renderSummary();
      }
    });
  }
}

function bindJobPage() {
  bindSharedWorkspaceActions();
  if (elements.jdInput) {
    elements.jdInput.value = state.jdText;
    elements.jdInput.addEventListener("input", analyzeJobDescription);
  }
  elements.analyzeJdButton?.addEventListener("click", analyzeJobDescription);
  elements.jdUploadButton?.addEventListener("click", uploadJobDescriptionFile);
  if (elements.jdFileInput && elements.jdFileLabel) {
    elements.jdFileInput.addEventListener("change", () => {
      const file = elements.jdFileInput.files?.[0];
      elements.jdFileLabel.textContent = file ? file.name : "Choose a JD file";
    });
  }
}

function bindWikiPage() {
  bindSharedWorkspaceActions();
  elements.wikiSearchInput?.addEventListener("input", () => {
    state.wikiQuery = elements.wikiSearchInput.value;
    renderWikiSidebar();
  });
}

function bindProfileSelectorPage() {
  elements.logoutButton?.addEventListener("click", logout);
  elements.profileForm?.addEventListener("submit", createProfileSubmit);
  elements.profileUpdateForm?.addEventListener("submit", updateManagedProfile);
  elements.deleteProfileButton?.addEventListener("click", deleteManagedProfile);
}

function bindProfilePage() {
  bindSharedWorkspaceActions();
  elements.profileOverviewForm?.addEventListener("submit", saveProfileOverview);
  elements.resetProfileOverviewButton?.addEventListener("click", resetProfileOverviewEdits);
}

function bindAuthPages() {
  elements.loginForm?.addEventListener("submit", handleLogin);
  elements.registerForm?.addEventListener("submit", handleRegister);
}

function redirectToLogin() {
  if (page !== "login") {
    window.location.href = "/login";
  }
}

async function ensureAuthenticated() {
  try {
    await loadAuthSession();
    await loadProfiles();
    return true;
  } catch (error) {
    if (error.status === 401) {
      state.user = null;
      if (page === "login" || page === "register") {
        return false;
      }
      redirectToLogin();
      return false;
    }
    throw error;
  }
}

function ensureSelectedProfileOrRedirect() {
  if (!state.profiles.length) {
    window.location.href = "/profiles/select";
    return false;
  }
  if (!state.selectedProfileId || !state.profiles.some((profile) => profile.id === state.selectedProfileId)) {
    window.location.href = "/profiles/select";
    return false;
  }
  renderCurrentProfileMeta();
  return true;
}

async function initLoginPage() {
  bindAuthPages();
  const authenticated = await ensureAuthenticated();
  if (authenticated) {
    window.location.href = "/profiles/select";
  }
}

async function initRegisterPage() {
  bindAuthPages();
  const authenticated = await ensureAuthenticated();
  if (authenticated) {
    window.location.href = "/profiles/select";
  }
}

async function initProfileSelectorPage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated) {
    return;
  }
  bindProfileSelectorPage();
  renderUserIdentity();
  renderProfileSelector();
}

async function initEvidencePage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated || !ensureSelectedProfileOrRedirect()) {
    return;
  }
  bindEvidencePage();
  await refreshEvidencePage();
}

async function initJobPage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated || !ensureSelectedProfileOrRedirect()) {
    return;
  }
  bindJobPage();
  await refreshJobPage();
}

async function initProfilePage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated || !ensureSelectedProfileOrRedirect()) {
    return;
  }
  bindProfilePage();
  await refreshProfilePage();
}

async function initWikiPage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated || !ensureSelectedProfileOrRedirect()) {
    return;
  }
  bindWikiPage();
  await refreshWikiPage();
}

async function init() {
  try {
    if (page === "login") {
      await initLoginPage();
      return;
    }
    if (page === "register") {
      await initRegisterPage();
      return;
    }
    if (page === "profile-select") {
      await initProfileSelectorPage();
      return;
    }
    if (page === "job") {
      await initJobPage();
      return;
    }
    if (page === "profile") {
      await initProfilePage();
      return;
    }
    if (page === "wiki") {
      await initWikiPage();
      return;
    }
    await initEvidencePage();
  } catch (error) {
    showToast(error.message || "Something went wrong.", "error");
  }
}

init();
