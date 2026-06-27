const page = document.body.dataset.page || "evidence";

const state = {
  user: null,
  profiles: [],
  selectedProfileId: window.localStorage.getItem("resume_workspace_profile_id") || null,
  profileView: window.localStorage.getItem("resume_workspace_profile_view") || null,
  parserBackends: [],
  selectedParserBackend: window.localStorage.getItem("resume_workspace_parser_backend") || null,
  parserComparisons: {},
  managedProfileId: null,
  summary: null,
  health: null,
  profileOverview: null,
  profileStudioReview: null,
  profileStudioPreview: null,
  profileFusion: null,
  profileStudioBucket: "review",
  profileStudioSectionByBucket: {},
  benchmarkDataset: null,
  benchmarkReport: null,
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
  runtimeHealthBadges: document.querySelector("#runtime-health-badges"),

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
  profileReviewMeta: document.querySelector("#profile-review-meta"),
  profileReviewSections: document.querySelector("#profile-review-sections"),
  acceptAllReviewButton: document.querySelector("#accept-all-review-button"),
  saveCanonicalButton: document.querySelector("#save-canonical-button"),
  resetCanonicalButton: document.querySelector("#reset-canonical-button"),
  profileMemoryMode: document.querySelector("#profile-memory-mode"),
  profileFusionMeta: document.querySelector("#profile-fusion-meta"),
  profileFusionMerged: document.querySelector("#profile-fusion-merged"),
  profileFusionCritical: document.querySelector("#profile-fusion-critical"),
  profileFusionOptional: document.querySelector("#profile-fusion-optional"),
  profileFusionIgnored: document.querySelector("#profile-fusion-ignored"),
  profileViewSelect: document.querySelector("#profile-view-select"),
  profileDiagnosticsSummary: document.querySelector("#profile-diagnostics-summary"),
  profileDiagnosticsSources: document.querySelector("#profile-diagnostics-sources"),
  profileDiagnosticsRecords: document.querySelector("#profile-diagnostics-records"),

  benchmarkMetricCases: document.querySelector("#benchmark-metric-cases"),
  benchmarkMetricCategories: document.querySelector("#benchmark-metric-categories"),
  benchmarkMetricLastRun: document.querySelector("#benchmark-metric-last-run"),
  benchmarkMetricScore: document.querySelector("#benchmark-metric-score"),
  benchmarkBackendSelect: document.querySelector("#benchmark-backend-select"),
  benchmarkCategorySelect: document.querySelector("#benchmark-category-select"),
  benchmarkLimitInput: document.querySelector("#benchmark-limit-input"),
  benchmarkRemoteToggle: document.querySelector("#benchmark-remote-toggle"),
  benchmarkRunButton: document.querySelector("#benchmark-run-button"),
  benchmarkRunStatus: document.querySelector("#benchmark-run-status"),
  benchmarkDatasetSummary: document.querySelector("#benchmark-dataset-summary"),
  benchmarkFieldCoverage: document.querySelector("#benchmark-field-coverage"),
  benchmarkSummaryGrid: document.querySelector("#benchmark-summary-grid"),
  benchmarkFieldMetrics: document.querySelector("#benchmark-field-metrics"),
  benchmarkCaseResults: document.querySelector("#benchmark-case-results"),

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
  const contentType = response.headers.get("content-type") || "";
  const rawBody = await response.text();

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    if (rawBody) {
      if (contentType.includes("application/json")) {
        try {
          const payload = JSON.parse(rawBody);
          message = payload.detail || payload.message || rawBody || message;
        } catch {
          message = rawBody;
        }
      } else {
        message = rawBody;
      }
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  if (!rawBody) {
    return null;
  }
  if (contentType.includes("application/json")) {
    return JSON.parse(rawBody);
  }
  return rawBody;
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
  const numeric = Number.isFinite(Number(value)) ? Number(value) : 0;
  return Math.round(Math.max(0, Math.min(numeric, 1)) * 100);
}

function tokenize(text) {
  return String(text).toLowerCase().match(/[a-z0-9+#._-]+/g) || [];
}

function unique(values) {
  return [...new Set(values)];
}

function formatSectionLabel(value) {
  const mapped = reviewSectionChoices().find((choice) => choice.value === value)?.label;
  if (mapped) {
    return mapped;
  }
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatFusionGroupLabel(value) {
  const mapping = {
    identity: "Personal",
    public_profile: "Link",
    skill: "Skill",
    work_experience: "Experience",
    education: "Education",
    project: "Project",
    certification: "Certification",
    ignored_public_profile: "Ignored Link",
  };
  return mapping[value] || formatSectionLabel(value);
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

function rememberSelectedProfileView(view) {
  state.profileView = view || null;
  if (state.profileView) {
    window.localStorage.setItem("resume_workspace_profile_view", state.profileView);
    return;
  }
  window.localStorage.removeItem("resume_workspace_profile_view");
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

function selectedUploadFiles() {
  return Array.from(elements.fileInput?.files || []);
}

function selectedUploadFile() {
  return selectedUploadFiles()[0] || null;
}

function selectedUploadLabel(files = selectedUploadFiles()) {
  if (!files.length) {
    return "Nothing selected yet.";
  }
  if (files.length === 1) {
    return `${files[0].name} is ready to upload.`;
  }
  const visibleNames = files.slice(0, 3).map((file) => file.name).join(", ");
  const remainder = files.length > 3 ? `, +${files.length - 3} more` : "";
  return `${files.length} files ready: ${visibleNames}${remainder}.`;
}

function refreshSelectedUploadLabel(files = selectedUploadFiles()) {
  if (elements.selectedFileLabel) {
    elements.selectedFileLabel.textContent = selectedUploadLabel(files);
  }
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
  state.profileStudioReview = null;
  state.profileStudioPreview = null;
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

function renderBenchmarkBackendControls() {
  if (!elements.benchmarkBackendSelect) {
    return;
  }

  ensureSelectedParserBackend();
  const options = [
    AUTO_PARSER_BACKEND,
    ...(state.parserBackends.length
      ? state.parserBackends
      : [{ id: "layout_ner", label: "Layout + NER", description: "Default parser.", available: true, is_default: true }]),
  ];

  elements.benchmarkBackendSelect.innerHTML = options
    .map((backend) => `
      <option value="${escapeHtml(backend.id)}" ${backend.id === state.selectedParserBackend ? "selected" : ""} ${backend.available ? "" : "disabled"}>
        ${escapeHtml(backend.label)}${backend.id !== AUTO_PARSER_BACKEND.id && backend.is_default ? " (Default)" : ""}${backend.available ? "" : " (Unavailable)"}
      </option>
    `)
    .join("");
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
    const publicHost = state.health?.public_base_url
      ? state.health.public_base_url.replace(/^https?:\/\//, "")
      : "";
    const publicText = publicHost ? ` Public demo host: ${publicHost}.` : "";
    elements.engineSummary.textContent = `${extractorText}${retrievalText}${publicText}`;
  }
}

function renderRuntimeHealth() {
  if (!elements.runtimeHealthBadges) {
    return;
  }
  if (!state.health) {
    elements.runtimeHealthBadges.innerHTML = '<span class="chip warning">Runtime status unavailable</span>';
    return;
  }

  const ready = state.health.ready_status === "ready";
  const secureCookie = Boolean(state.health.session_cookie_secure);
  const publicHost = state.health.public_base_url
    ? state.health.public_base_url.replace(/^https?:\/\//, "")
    : null;
  const embeddingsEnabled = Boolean(state.health.embedding_retrieval_enabled);
  const parserBackend = state.health.parser_backend || "auto";

  elements.runtimeHealthBadges.innerHTML = [
    `<span class="chip ${ready ? "success" : "warning"}">${ready ? "System ready" : "Warmup checks pending"}</span>`,
    `<span class="chip ${secureCookie ? "success" : "warning"}">${secureCookie ? "Secure session cookie" : "Local cookie mode"}</span>`,
    `<span class="chip">${publicHost ? `Public: ${escapeHtml(publicHost)}` : "Public URL pending"}</span>`,
    `<span class="chip">${escapeHtml(`Parser: ${parserBackend}`)}</span>`,
    `<span class="chip ${embeddingsEnabled ? "success" : ""}">${embeddingsEnabled ? "Embeddings on" : "Lexical retrieval"}</span>`,
  ].join("");
}

function benchmarkCategoryValue() {
  return elements.benchmarkCategorySelect?.value?.trim() || "";
}

function benchmarkLimitValue() {
  const raw = Number(elements.benchmarkLimitInput?.value || "");
  if (!Number.isFinite(raw) || raw <= 0) {
    return null;
  }
  return Math.round(raw);
}

function benchmarkStatusChipClass(status) {
  if (status === "match") {
    return "success";
  }
  if (status === "close") {
    return "warning";
  }
  if (status === "miss" || status === "error") {
    return "danger";
  }
  return "";
}

function benchmarkPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return `${confidencePercent(value)}%`;
}

function benchmarkFieldMetricCard(metric) {
  return `
    <article class="detail-card benchmark-field-card">
      <div class="meta-row">
        <strong>${escapeHtml(metric.label)}</strong>
        <span class="chip ${benchmarkStatusChipClass((metric.average_score || 0) >= 0.95 ? "match" : (metric.average_score || 0) >= 0.75 ? "close" : "miss")}">${benchmarkPercent(metric.average_score)}</span>
      </div>
      <div class="detail-line">Scored cases: ${escapeHtml(String(metric.scored_cases || 0))}</div>
      <div class="detail-line">Matches: ${escapeHtml(String(metric.match_cases || 0))} · Close: ${escapeHtml(String(metric.close_cases || 0))} · Misses: ${escapeHtml(String(metric.miss_cases || 0))}</div>
      <div class="detail-line">Skipped: ${escapeHtml(String(metric.skipped_cases || 0))}</div>
    </article>
  `;
}

function benchmarkFieldScoreCard(fieldScore) {
  const goldPreview = (fieldScore.gold_preview || []).length
    ? (fieldScore.gold_preview || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")
    : '<span class="empty-inline">No gold value.</span>';
  const extractedPreview = (fieldScore.extracted_preview || []).length
    ? (fieldScore.extracted_preview || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")
    : '<span class="empty-inline">Nothing extracted.</span>';
  return `
    <article class="detail-card benchmark-case-field-card">
      <div class="meta-row">
        <strong>${escapeHtml(fieldScore.label)}</strong>
        <span class="chip ${benchmarkStatusChipClass(fieldScore.status)}">${escapeHtml(String(fieldScore.status || "not_scored").replaceAll("_", " ").toUpperCase())}</span>
        <span class="meta-text">${benchmarkPercent(fieldScore.score)}</span>
      </div>
      <div class="detail-line">Gold ${escapeHtml(String(fieldScore.gold_count || 0))} · Extracted ${escapeHtml(String(fieldScore.extracted_count || 0))} · Matched ${escapeHtml(String(fieldScore.matched_count || 0))}</div>
      <div class="stack-list compact-stack">
        <div>
          <div class="field-label">Gold</div>
          <div class="tag-row">${goldPreview}</div>
        </div>
        <div>
          <div class="field-label">Extracted</div>
          <div class="tag-row">${extractedPreview}</div>
        </div>
      </div>
      ${(fieldScore.notes || []).length
        ? `<div class="stack-list compact-stack">${(fieldScore.notes || []).map((note) => `<div class="detail-line">${escapeHtml(note)}</div>`).join("")}</div>`
        : ""}
    </article>
  `;
}

function renderBenchmarkDataset() {
  const dataset = state.benchmarkDataset;
  const report = state.benchmarkReport;

  if (elements.currentProfileName && page === "benchmarks") {
    elements.currentProfileName.textContent = dataset?.available
      ? `${dataset.total_cases} benchmark resumes ready`
      : "Benchmark dataset not available";
  }
  if (elements.currentProfileMeta && page === "benchmarks") {
    elements.currentProfileMeta.textContent = dataset?.dataset_dir
      ? dataset.dataset_dir
      : "Set BENCHMARK_DATASET_DIR or place the dataset in ~/Downloads/ragume_benchmark_gold_v0.";
  }
  if (elements.engineSummary && page === "benchmarks") {
    if (report) {
      elements.engineSummary.textContent = `Latest run: ${report.processed_cases} resumes · ${benchmarkPercent(report.overall_score)} overall · ${report.parser_backend} backend${report.allow_remote_models ? " · remote models allowed" : " · local-safe mode"}.`;
    } else if (dataset?.available) {
      elements.engineSummary.textContent = "The benchmark runner compares parser output against the gold template and saves the latest report for this page.";
    } else {
      elements.engineSummary.textContent = "Benchmark runner is waiting for the gold dataset.";
    }
  }

  if (elements.benchmarkMetricCases) {
    elements.benchmarkMetricCases.textContent = String(dataset?.total_cases || 0);
  }
  if (elements.benchmarkMetricCategories) {
    elements.benchmarkMetricCategories.textContent = String(dataset?.categories?.length || 0);
  }
  if (elements.benchmarkMetricLastRun) {
    elements.benchmarkMetricLastRun.textContent = report ? String(report.processed_cases || 0) : "0";
  }
  if (elements.benchmarkMetricScore) {
    elements.benchmarkMetricScore.textContent = benchmarkPercent(report?.overall_score);
  }

  if (elements.benchmarkRunStatus) {
    if (!dataset?.available) {
      elements.benchmarkRunStatus.textContent = "Benchmark dataset not found. Add BENCHMARK_DATASET_DIR to .env or place the dataset in ~/Downloads/ragume_benchmark_gold_v0.";
    } else if (report) {
      elements.benchmarkRunStatus.textContent = `Last run saved at ${report.saved_report_path || "latest.json"} · ${report.success_cases} succeeded · ${report.failed_cases} failed · ${report.duration_seconds}s.`;
    } else {
      elements.benchmarkRunStatus.textContent = "The benchmark runner will compare extracted output against the gold template at the configured dataset path.";
    }
  }

  if (elements.benchmarkCategorySelect) {
    const currentValue = benchmarkCategoryValue();
    const categories = dataset?.categories || [];
    elements.benchmarkCategorySelect.innerHTML = `
      <option value="">All categories</option>
      ${categories.map((category) => `<option value="${escapeHtml(category)}" ${category === currentValue ? "selected" : ""}>${escapeHtml(category)}</option>`).join("")}
    `;
  }

  if (elements.benchmarkDatasetSummary) {
    if (!dataset) {
      elements.benchmarkDatasetSummary.innerHTML = '<div class="empty-state">Dataset coverage details will appear here.</div>';
    } else {
      elements.benchmarkDatasetSummary.innerHTML = `
        <div class="detail-line">Gold template: ${escapeHtml(dataset.gold_template_path || "Not found")}</div>
        <div class="detail-line">Manifest: ${escapeHtml(dataset.manifest_path || "Not found")}</div>
        <div class="detail-line">Review status counts: ${escapeHtml(Object.entries(dataset.review_status_counts || {}).map(([status, count]) => `${status} ${count}`).join(" · ") || "No review metadata")}</div>
        <div class="detail-line">Latest saved report: ${escapeHtml(dataset.latest_report_generated_at ? formatDate(dataset.latest_report_generated_at) : "None yet")}</div>
      `;
    }
  }

  if (elements.benchmarkFieldCoverage) {
    const coverage = dataset?.field_coverage || {};
    const entries = Object.entries(coverage).filter(([, count]) => count > 0);
    elements.benchmarkFieldCoverage.innerHTML = entries.length
      ? entries
          .sort((left, right) => right[1] - left[1])
          .map(([field, count]) => `<span class="tag">${escapeHtml(formatSectionLabel(field))} · ${escapeHtml(String(count))}</span>`)
          .join("")
      : '<span class="empty-inline">Coverage tags will appear here.</span>';
  }
}

function renderBenchmarkReport() {
  const report = state.benchmarkReport;
  if (!elements.benchmarkSummaryGrid || !elements.benchmarkFieldMetrics || !elements.benchmarkCaseResults) {
    return;
  }

  if (!report) {
    elements.benchmarkSummaryGrid.innerHTML = '<div class="empty-state">Run the benchmark to see aggregate metrics.</div>';
    elements.benchmarkFieldMetrics.innerHTML = '<div class="empty-state">Field-level benchmark metrics will appear here after a run.</div>';
    elements.benchmarkCaseResults.innerHTML = '<div class="empty-state">Per-resume benchmark results will appear here after a run.</div>';
    return;
  }

  elements.benchmarkSummaryGrid.innerHTML = `
    <article class="detail-card">
      <div class="detail-card-title">Run summary</div>
      <div class="detail-line">${escapeHtml(String(report.processed_cases || 0))} processed · ${escapeHtml(String(report.success_cases || 0))} succeeded · ${escapeHtml(String(report.failed_cases || 0))} failed</div>
      <div class="detail-line">Overall score: ${escapeHtml(benchmarkPercent(report.overall_score))}</div>
      <div class="detail-line">Backend: ${escapeHtml(report.parser_backend || "auto")} · ${report.allow_remote_models ? "remote models allowed" : "local-safe mode"}</div>
    </article>
    <article class="detail-card">
      <div class="detail-card-title">Scope</div>
      <div class="detail-line">Dataset: ${escapeHtml(report.dataset_dir || "unknown")}</div>
      <div class="detail-line">Categories: ${escapeHtml((report.categories || []).join(", ") || "All")}</div>
      <div class="detail-line">Limit: ${escapeHtml(String(report.limit || "All"))}</div>
    </article>
    <article class="detail-card">
      <div class="detail-card-title">Timing</div>
      <div class="detail-line">Generated: ${escapeHtml(formatDate(report.generated_at))}</div>
      <div class="detail-line">Duration: ${escapeHtml(String(report.duration_seconds || 0))}s</div>
      <div class="detail-line">Saved report: ${escapeHtml(report.saved_report_path || "Not saved")}</div>
    </article>
  `;

  elements.benchmarkFieldMetrics.innerHTML = (report.field_metrics || []).length
    ? report.field_metrics.map((metric) => benchmarkFieldMetricCard(metric)).join("")
    : '<div class="empty-state">No field metrics were recorded.</div>';

  elements.benchmarkCaseResults.innerHTML = (report.cases || []).length
    ? report.cases.map((item) => `
        <details class="benchmark-case-card"${item.status === "error" ? "" : " open"}>
          <summary>
            <div class="meta-row">
              <strong>${escapeHtml(item.filename)}</strong>
              <span class="chip">${escapeHtml(item.category)}</span>
              <span class="chip ${benchmarkStatusChipClass(item.status === "error" ? "error" : (item.overall_score || 0) >= 0.95 ? "match" : (item.overall_score || 0) >= 0.75 ? "close" : "miss")}">${item.status === "error" ? "ERROR" : benchmarkPercent(item.overall_score)}</span>
            </div>
            <div class="meta-text">${escapeHtml(item.resume_id)} · ${escapeHtml(item.parser_backend || "auto")} · ${escapeHtml(item.extraction_mode || "unknown mode")}</div>
          </summary>
          <div class="benchmark-case-body">
            ${item.error ? `<div class="detail-line warning-line">${escapeHtml(item.error)}</div>` : ""}
            ${(item.warnings || []).length
              ? `<div class="stack-list compact-stack">${(item.warnings || []).map((warning) => `<div class="detail-line warning-line">${escapeHtml(warning)}</div>`).join("")}</div>`
              : ""}
            <div class="detail-grid">
              ${fieldPreviewCard("Extracted snapshot", [
                item.extracted_snapshot?.full_name ? `Name: ${item.extracted_snapshot.full_name}` : null,
                item.extracted_snapshot?.headline ? `Headline: ${item.extracted_snapshot.headline}` : null,
                item.extracted_snapshot?.location ? `Location: ${item.extracted_snapshot.location}` : null,
                `Skills: ${item.extracted_snapshot?.skills_count || 0}`,
                `Experience: ${item.extracted_snapshot?.experience_count || 0}`,
                `Projects: ${item.extracted_snapshot?.project_count || 0}`,
              ].filter(Boolean))}
              ${fieldPreviewCard("Diagnostics", [
                item.diagnostics?.document_role ? `Role: ${item.diagnostics.document_role}` : null,
                item.diagnostics?.profile_focus ? `Focus: ${item.diagnostics.profile_focus}` : null,
                item.diagnostics?.validation_status ? `Validation: ${item.diagnostics.validation_status} (${item.diagnostics.validation_score ?? "--"})` : null,
                item.diagnostics?.layout_parser ? `Layout parser: ${item.diagnostics.layout_parser}` : null,
                item.diagnostics?.page_count ? `Pages: ${item.diagnostics.page_count}` : null,
                item.diagnostics?.block_count ? `Blocks: ${item.diagnostics.block_count}` : null,
              ].filter(Boolean))}
            </div>
            <div class="benchmark-case-fields">
              ${(item.field_scores || []).map((fieldScore) => benchmarkFieldScoreCard(fieldScore)).join("")}
            </div>
          </div>
        </details>
      `).join("")
    : '<div class="empty-state">Per-resume benchmark results will appear here after a run.</div>';
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
  const overview = page === "profile" && state.profileOverview?.profile_mode !== "canonical" && state.profileStudioPreview
    ? state.profileStudioPreview
    : state.profileOverview;
  if (!overview) {
    return;
  }
  if (elements.profileMemoryMode) {
    const focusLabel = overview.profile_focus ? ` Focus: ${formatSectionLabel(overview.profile_focus)}.` : "";
    const viewLabel = overview.profile_view ? ` View: ${formatSectionLabel(overview.profile_view)}.` : "";
    elements.profileMemoryMode.textContent = overview.profile_mode === "canonical"
      ? `This is the saved canonical profile memory that future job outputs should use.${focusLabel}${viewLabel}`
      : overview.profile_mode === "review"
        ? `This is the live review preview. Accept, reject, or edit items on the left, then save when it looks right.${focusLabel}${viewLabel}`
        : `This is the latest extracted profile preview. Save the reviewed sections to lock in a canonical profile.${focusLabel}${viewLabel}`;
  }

  const identity = overview.identity || {};
  if (elements.profileIdentityCard) {
    elements.profileIdentityCard.innerHTML = `
      <div class="profile-block-title">${escapeHtml(identity.full_name || "No name detected yet")}</div>
      <div class="profile-block-subtitle">${escapeHtml(identity.headline || "Upload stronger profile evidence to capture a headline.")}</div>
      ${identity.current_position ? `<div class="profile-line subtle">Current position: ${escapeHtml(identity.current_position)}</div>` : ""}
      ${identity.target_headline ? `<div class="profile-line subtle">Target headline: ${escapeHtml(identity.target_headline)}</div>` : ""}
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

function availableProfileViews() {
  const values = unique([
    ...(state.profileOverview?.available_views || []),
    ...(state.profileStudioPreview?.available_views || []),
    ...(state.profileStudioReview?.canonical_profile?.available_views || []),
  ].filter(Boolean));
  return values.length ? values : ["master", "ai_ml", "web_dev", "full_stack", "ats_short"];
}

function renderProfileViewControl() {
  if (!elements.profileViewSelect) {
    return;
  }
  const views = availableProfileViews();
  const fallback = state.profileOverview?.profile_view || state.profileStudioPreview?.profile_view || state.profileOverview?.profile_focus || "master";
  const selected = views.includes(state.profileView) ? state.profileView : fallback;
  if (!state.profileView && selected) {
    rememberSelectedProfileView(selected);
  }
  elements.profileViewSelect.innerHTML = views
    .map((view) => `<option value="${escapeHtml(view)}" ${selected === view ? "selected" : ""}>${escapeHtml(formatSectionLabel(view))}</option>`)
    .join("");
}

function fusionGroupMarkup(group, anomalyLookup = new Map()) {
  const metadata = group.group_metadata || {};
  const anomaly = anomalyLookup.get(group.id);
  const candidateValues = metadata.candidate_values || [];
  const ignoredValues = metadata.ignored_values || [];
  const reasons = metadata.reasons || [];
  const groupLabel = formatFusionGroupLabel(group.group_type);
  return `
    <article class="fusion-entry">
      <div class="meta-row">
        <strong>${escapeHtml(groupLabel)}</strong>
        <span class="chip ${structuredClaimResolverClass(group.merge_action)}">${escapeHtml(String(group.merge_action || "merged").replaceAll("_", " ").toUpperCase())}</span>
        <span class="meta-text">${confidencePercent(group.confidence)}%</span>
      </div>
      <div class="fusion-entry-value">${escapeHtml(group.canonical_value || "No canonical value selected")}</div>
      <div class="detail-line">${escapeHtml(String(metadata.source_count || group.claim_ids?.length || 0))} sources${metadata.document_count ? ` · ${escapeHtml(String(metadata.document_count))} documents` : ""}</div>
      ${anomaly ? `<div class="detail-line warning-line">${escapeHtml(anomaly.message)}</div>` : ""}
      ${candidateValues.length ? `
        <div class="tag-row">
          ${candidateValues.slice(0, 4).map((item) => `<span class="tag">${escapeHtml(item.value || item.normalized || "")}</span>`).join("")}
        </div>
      ` : ""}
      ${ignoredValues.length ? `<div class="detail-line">Ignored: ${escapeHtml(ignoredValues.slice(0, 4).join(", "))}</div>` : ""}
      ${reasons.length ? `<div class="detail-line">${escapeHtml(reasons.join(" · "))}</div>` : ""}
    </article>
  `;
}

function renderProfileFusion() {
  if (!elements.profileFusionMerged || !elements.profileFusionCritical || !elements.profileFusionOptional || !elements.profileFusionIgnored) {
    return;
  }
  const fusion = state.profileFusion;
  if (!fusion) {
    if (elements.profileFusionMeta) {
      elements.profileFusionMeta.textContent = "Critical conflicts, optional cleanup, and ignored duplicates will appear here.";
    }
    elements.profileFusionMerged.innerHTML = '<div class="empty-state">Automatic merges will appear after review data loads.</div>';
    elements.profileFusionCritical.innerHTML = '<div class="empty-state">Trust-breaking conflicts will appear here.</div>';
    elements.profileFusionOptional.innerHTML = '<div class="empty-state">Optional cleanup items will appear here.</div>';
    elements.profileFusionIgnored.innerHTML = '<div class="empty-state">Duplicates and noisy fragments will appear here.</div>';
    return;
  }

  const anomalyLookup = new Map((fusion.anomalies || []).filter((item) => item.claim_group_id).map((item) => [item.claim_group_id, item]));
  if (elements.profileFusionMeta) {
    const summary = fusion.summary || {};
    elements.profileFusionMeta.textContent = `${summary.critical_review_total || 0} critical fixes before the profile is trustworthy · ${summary.optional_review_total || 0} optional cleanup items · ${summary.ignored_total || 0} ignored safely`;
  }

  elements.profileFusionMerged.innerHTML = (fusion.merged_groups || []).length
    ? fusion.merged_groups.map((group) => fusionGroupMarkup(group, anomalyLookup)).join("")
    : '<div class="empty-state">No automatic merges yet.</div>';
  elements.profileFusionCritical.innerHTML = (fusion.critical_review_groups || []).length
    ? fusion.critical_review_groups.map((group) => fusionGroupMarkup(group, anomalyLookup)).join("")
    : '<div class="empty-state">No critical conflicts right now.</div>';
  elements.profileFusionOptional.innerHTML = (fusion.optional_review_groups || []).length
    ? fusion.optional_review_groups.map((group) => fusionGroupMarkup(group, anomalyLookup)).join("")
    : '<div class="empty-state">No optional cleanup items right now.</div>';
  elements.profileFusionIgnored.innerHTML = (fusion.ignored_groups || []).length
    ? fusion.ignored_groups.map((group) => fusionGroupMarkup(group, anomalyLookup)).join("")
    : '<div class="empty-state">No duplicates or noisy fragments ignored yet.</div>';
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

function reviewSectionChoices() {
  return [
    { value: "identity", label: "Personal" },
    { value: "skills", label: "Skills" },
    { value: "work_experience", label: "Experience" },
    { value: "projects", label: "Projects" },
    { value: "education", label: "Education" },
    { value: "certifications", label: "Certifications" },
    { value: "public_profiles", label: "Links" },
  ];
}

function structuredClaimStatusClass(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "accepted") {
    return "success";
  }
  if (normalized === "edited" || normalized === "pending" || normalized === "duplicate") {
    return "warning";
  }
  return "danger";
}

function structuredClaimResolverClass(action) {
  const normalized = String(action || "").toLowerCase();
  if (normalized === "auto_correct" || normalized === "accepted_suggestion" || normalized === "admit") {
    return "success";
  }
  if (normalized === "needs_review" || normalized === "reject_noise") {
    return "danger";
  }
  if (normalized === "suggest" || normalized === "manual" || normalized === "duplicate" || normalized === "quarantine") {
    return "warning";
  }
  return "";
}

function structuredClaimValueText(section, fieldName, value) {
  const payload = value || {};
  if (section === "identity") {
    return payload.value || "";
  }
  if (section === "skills") {
    return payload.name || "";
  }
  if (section === "public_profiles") {
    return [payload.label, payload.url].filter(Boolean).join(" · ");
  }
  if (section === "work_experience") {
    return [payload.title, payload.organization, [payload.start_date, payload.end_date].filter(Boolean).join(" - ")].filter(Boolean).join(" · ");
  }
  if (section === "education") {
    return [payload.degree, payload.institution, payload.field_of_study].filter(Boolean).join(" · ");
  }
  if (section === "projects") {
    return [payload.name, payload.summary].filter(Boolean).join(" · ");
  }
  if (section === "certifications") {
    return [payload.name, payload.issuer, payload.credential_id].filter(Boolean).join(" · ");
  }
  return payload.value || payload.name || payload.title || payload.summary || "";
}

function structuredClaimFieldMarkup(claim) {
  const value = claim.value_json || {};
  if (claim.section === "identity") {
    return `
      <label class="field-label">Value</label>
      <input type="text" data-claim-input="value" value="${escapeHtml(value.value || "")}">
    `;
  }
  if (claim.section === "skills") {
    return `
      <label class="field-label">Skill</label>
      <input type="text" data-claim-input="name" value="${escapeHtml(value.name || "")}">
    `;
  }
  if (claim.section === "public_profiles") {
    return `
      <div class="two-col-grid compact-grid">
        <div>
          <label class="field-label">Label</label>
          <input type="text" data-claim-input="label" value="${escapeHtml(value.label || "")}">
        </div>
        <div>
          <label class="field-label">URL</label>
          <input type="text" data-claim-input="url" value="${escapeHtml(value.url || "")}">
        </div>
      </div>
    `;
  }
  if (claim.section === "work_experience") {
    return `
      <div class="two-col-grid compact-grid">
        <div>
          <label class="field-label">Role</label>
          <input type="text" data-claim-input="title" value="${escapeHtml(value.title || "")}">
        </div>
        <div>
          <label class="field-label">Company</label>
          <input type="text" data-claim-input="organization" value="${escapeHtml(value.organization || "")}">
        </div>
        <div>
          <label class="field-label">Start</label>
          <input type="text" data-claim-input="start_date" value="${escapeHtml(value.start_date || "")}">
        </div>
        <div>
          <label class="field-label">End</label>
          <input type="text" data-claim-input="end_date" value="${escapeHtml(value.end_date || "")}">
        </div>
      </div>
      <label class="field-label">Location</label>
      <input type="text" data-claim-input="location" value="${escapeHtml(value.location || "")}">
      <label class="field-label">Summary</label>
      <textarea rows="4" data-claim-input="summary">${escapeHtml(value.summary || "")}</textarea>
      <label class="field-label">Highlights</label>
      <textarea rows="4" data-claim-input="highlights">${escapeHtml((value.highlights || []).join("\n"))}</textarea>
    `;
  }
  if (claim.section === "projects") {
    return `
      <label class="field-label">Project</label>
      <input type="text" data-claim-input="name" value="${escapeHtml(value.name || "")}">
      <label class="field-label">Summary</label>
      <textarea rows="4" data-claim-input="summary">${escapeHtml(value.summary || "")}</textarea>
      <label class="field-label">Technologies</label>
      <textarea rows="3" data-claim-input="technologies">${escapeHtml((value.technologies || []).join(", "))}</textarea>
      <label class="field-label">Links</label>
      <textarea rows="3" data-claim-input="links">${escapeHtml((value.links || []).join("\n"))}</textarea>
    `;
  }
  if (claim.section === "education") {
    return `
      <div class="two-col-grid compact-grid">
        <div>
          <label class="field-label">Degree</label>
          <input type="text" data-claim-input="degree" value="${escapeHtml(value.degree || "")}">
        </div>
        <div>
          <label class="field-label">Institution</label>
          <input type="text" data-claim-input="institution" value="${escapeHtml(value.institution || "")}">
        </div>
        <div>
          <label class="field-label">Field</label>
          <input type="text" data-claim-input="field_of_study" value="${escapeHtml(value.field_of_study || "")}">
        </div>
        <div>
          <label class="field-label">Start</label>
          <input type="text" data-claim-input="start_date" value="${escapeHtml(value.start_date || "")}">
        </div>
        <div>
          <label class="field-label">End</label>
          <input type="text" data-claim-input="end_date" value="${escapeHtml(value.end_date || "")}">
        </div>
      </div>
      <label class="field-label">Summary</label>
      <textarea rows="4" data-claim-input="summary">${escapeHtml(value.summary || "")}</textarea>
    `;
  }
  if (claim.section === "certifications") {
    return `
      <div class="two-col-grid compact-grid">
        <div>
          <label class="field-label">Name</label>
          <input type="text" data-claim-input="name" value="${escapeHtml(value.name || "")}">
        </div>
        <div>
          <label class="field-label">Issuer</label>
          <input type="text" data-claim-input="issuer" value="${escapeHtml(value.issuer || "")}">
        </div>
        <div>
          <label class="field-label">Issued</label>
          <input type="text" data-claim-input="start_date" value="${escapeHtml(value.start_date || "")}">
        </div>
        <div>
          <label class="field-label">Credential ID</label>
          <input type="text" data-claim-input="credential_id" value="${escapeHtml(value.credential_id || "")}">
        </div>
      </div>
      <label class="field-label">Summary</label>
      <textarea rows="4" data-claim-input="summary">${escapeHtml(value.summary || "")}</textarea>
    `;
  }
  return `
    <label class="field-label">Value</label>
    <textarea rows="4" data-claim-input="raw_json">${escapeHtml(JSON.stringify(value, null, 2))}</textarea>
  `;
}

function profileStudioBucketChoices() {
  return [
    {
      value: "review",
      label: "Needs Review",
      description: "Focus here first. These are the only items that still need a decision or a quick adjustment.",
      emptyMessage: "Nothing needs review right now.",
    },
    {
      value: "ready",
      label: "Ready / Accepted",
      description: "These items already look solid enough to keep. Open this tab only when you want to spot-check them.",
      emptyMessage: "No stable items yet.",
    },
    {
      value: "rejected",
      label: "Rejected / Ignored",
      description: "These items stay out of the preview until you change them again.",
      emptyMessage: "No rejected or ignored items yet.",
    },
  ];
}

function profileStudioBucketForClaim(claim) {
  const status = String(claim.status || "").toLowerCase();
  const action = String(claim.resolver_action || "keep").toLowerCase();
  const admission = String(claim.admission_status || "").toLowerCase();
  if (admission === "reject_noise" || admission === "quarantine") {
    return "rejected";
  }
  if (status === "rejected" || status === "duplicate" || action === "duplicate") {
    return "rejected";
  }
  if (admission === "needs_review") {
    return "review";
  }
  if (admission === "admit") {
    return "ready";
  }
  if (status === "accepted" || status === "edited") {
    return "ready";
  }
  if (action === "needs_review" || action === "suggest") {
    return "review";
  }
  if (action === "manual" || action === "auto_correct" || action === "keep" || action === "accepted_suggestion") {
    return "ready";
  }
  return "review";
}

function buildProfileStudioBuckets(review) {
  return profileStudioBucketChoices().map((bucket) => {
    const sections = (review.sections || [])
      .map((section) => {
        const claims = (section.claims || []).filter((claim) => profileStudioBucketForClaim(claim) === bucket.value);
        if (!claims.length) {
          return null;
        }
        return {
          section: section.section,
          label: formatSectionLabel(section.section),
          claims,
        };
      })
      .filter(Boolean);

    return {
      ...bucket,
      total: sections.reduce((count, section) => count + section.claims.length, 0),
      sections,
    };
  });
}

function resolveActiveProfileStudioPane(buckets) {
  const nonEmptyBuckets = buckets.filter((bucket) => bucket.total > 0);
  const preferredBucket = buckets.find((bucket) => bucket.value === state.profileStudioBucket);
  const activeBucket = (
    (preferredBucket && (preferredBucket.total > 0 || !nonEmptyBuckets.length) ? preferredBucket : null)
    || buckets.find((bucket) => bucket.value === "review" && bucket.total > 0)
    || nonEmptyBuckets[0]
    || buckets[0]
  );
  state.profileStudioBucket = activeBucket.value;

  const preferredSection = state.profileStudioSectionByBucket[activeBucket.value];
  const activeSection = activeBucket.sections.find((section) => section.section === preferredSection) || activeBucket.sections[0] || null;
  if (activeSection) {
    state.profileStudioSectionByBucket[activeBucket.value] = activeSection.section;
  } else {
    delete state.profileStudioSectionByBucket[activeBucket.value];
  }
  return { activeBucket, activeSection };
}

function structuredClaimCardMarkup(claim) {
  const selectedSection = claim.suggested_section || claim.section;
  const rawPreview = structuredClaimValueText(claim.section, claim.field_name, claim.raw_value_json || {});
  const correctedPreview = structuredClaimValueText(selectedSection, claim.field_name, claim.value_json || {}) || claim.value_text || "Untitled item";
  const hasCorrectionPreview = rawPreview && correctedPreview && rawPreview !== correctedPreview;
  const sectionLabel = reviewSectionChoices().find((choice) => choice.value === selectedSection)?.label || formatSectionLabel(selectedSection);
  const cardClasses = ["studio-claim-card"];
  if (selectedSection === "skills") {
    cardClasses.push("studio-skill-card");
  }

  return `
    <article class="${cardClasses.join(" ")}" data-claim-id="${claim.id}" data-claim-section="${escapeHtml(claim.section)}">
      <div class="meta-row">
        <span class="chip ${structuredClaimStatusClass(claim.status)}">${escapeHtml(claim.status.replaceAll("_", " ").toUpperCase())}</span>
        <span class="chip ${structuredClaimResolverClass(claim.resolver_action)}">${escapeHtml(String(claim.resolver_action || "keep").replaceAll("_", " ").toUpperCase())}</span>
        <span class="chip ${structuredClaimResolverClass(claim.admission_status)}">${escapeHtml(String(claim.admission_status || "needs_review").replaceAll("_", " ").toUpperCase())}</span>
        <span class="meta-text">${confidencePercent(claim.confidence)}% parser</span>
        <span class="meta-text">${confidencePercent(claim.resolver_confidence || 0)}% resolver</span>
        <span class="meta-text">${confidencePercent(claim.admission_score || 0)}% admission</span>
        <span class="meta-text">${escapeHtml(claim.document_filename || "Source document")}</span>
      </div>
      <div class="studio-claim-preview">${escapeHtml(correctedPreview)}</div>
      ${hasCorrectionPreview ? `
        <div class="studio-claim-diff">
          <span>${escapeHtml(rawPreview)}</span>
          <span class="studio-claim-arrow">→</span>
          <strong>${escapeHtml(correctedPreview)}</strong>
        </div>
      ` : ""}
      ${claim.suggested_section && claim.suggested_section !== claim.section ? `<p class="subtle studio-claim-note">Suggested move: ${escapeHtml(sectionLabel)}</p>` : ""}
      ${claim.admission_reason ? `<p class="subtle studio-claim-note">Admission: ${escapeHtml(String(claim.admission_reason).replaceAll("_", " "))}</p>` : ""}
      ${claim.source_text ? `<p class="subtle">${escapeHtml(claim.source_text)}</p>` : ""}
      ${(claim.resolver_evidence || []).length ? `
        <div class="meta-row studio-claim-evidence">
          ${(claim.resolver_evidence || []).map((reason) => `<span class="chip">${escapeHtml(String(reason).replaceAll("_", " "))}</span>`).join("")}
        </div>
      ` : ""}
      <div class="two-col-grid compact-grid">
        <div>
          <label class="field-label">Section</label>
          <select data-claim-section-select>
            ${reviewSectionChoices().map((choice) => `
              <option value="${escapeHtml(choice.value)}" ${choice.value === selectedSection ? "selected" : ""}>
                ${escapeHtml(choice.label)}
              </option>
            `).join("")}
          </select>
        </div>
        <div>
          <label class="field-label">Parser</label>
          <input type="text" value="${escapeHtml(claim.parser_name)}" disabled>
        </div>
      </div>
      <div class="form-stack compact-form">
        ${structuredClaimFieldMarkup(claim)}
      </div>
      <div class="inline-row wrap">
        <button class="secondary-button" type="button" data-claim-action="accept">Accept</button>
        <button class="secondary-button" type="button" data-claim-action="save">Save edit</button>
        <button class="secondary-button danger-button" type="button" data-claim-action="reject">Reject</button>
      </div>
    </article>
  `;
}

function renderProfileStudioReview() {
  if (!elements.profileReviewSections) {
    return;
  }
  const review = state.profileStudioReview;
  if (!review) {
    elements.profileReviewSections.innerHTML = '<div class="empty-state">Review data will appear here after upload.</div>';
    if (elements.profileReviewMeta) {
      elements.profileReviewMeta.textContent = "Auto-corrected items and review suggestions will appear here after upload.";
    }
    return;
  }

  const buckets = buildProfileStudioBuckets(review);
  const { activeBucket, activeSection } = resolveActiveProfileStudioPane(buckets);
  const reviewCount = buckets.find((bucket) => bucket.value === "review")?.total || 0;
  const readyCount = buckets.find((bucket) => bucket.value === "ready")?.total || 0;
  const rejectedCount = buckets.find((bucket) => bucket.value === "rejected")?.total || 0;
  const fusionSummary = review.fusion?.summary || {};

  if (elements.profileReviewMeta) {
    elements.profileReviewMeta.textContent = `${review.claims_total} extracted items · ${fusionSummary.critical_review_total || 0} critical review items · ${fusionSummary.optional_review_total || reviewCount} optional cleanup items · ${readyCount} ready or accepted · ${rejectedCount} rejected or ignored`;
  }

  if (!buckets.some((bucket) => bucket.total > 0)) {
    elements.profileReviewSections.innerHTML = '<div class="empty-state">Upload evidence to generate reviewable profile items.</div>';
    return;
  }

  const sectionButtons = activeBucket.sections.length
    ? activeBucket.sections.map((section) => `
        <button
          class="studio-section-tab ${activeSection?.section === section.section ? "is-active" : ""}"
          type="button"
          data-studio-section="${escapeHtml(section.section)}"
        >
          <span>${escapeHtml(section.label)}</span>
          <span>${section.claims.length}</span>
        </button>
      `).join("")
    : "";

  const sectionBody = activeSection
    ? `
        <section class="studio-section-panel">
          <div class="studio-pane-header">
            <div>
              <span class="eyebrow">${escapeHtml(activeBucket.label)}</span>
              <h3>${escapeHtml(activeSection.label)}</h3>
              <p class="subtle">${activeBucket.description}</p>
            </div>
            <span class="chip">${activeSection.claims.length} item${activeSection.claims.length === 1 ? "" : "s"}</span>
          </div>
          <div class="studio-claim-list ${activeSection.section === "skills" ? "studio-skill-grid" : ""}">
            ${activeSection.claims.map((claim) => structuredClaimCardMarkup(claim)).join("")}
          </div>
        </section>
      `
    : `<div class="empty-state">${escapeHtml(activeBucket.emptyMessage)}</div>`;

  elements.profileReviewSections.innerHTML = `
    <div class="studio-review-shell">
      <div class="studio-bucket-tabs" role="tablist" aria-label="Profile review groups">
        ${buckets.map((bucket) => `
          <button
            class="studio-bucket-tab ${activeBucket.value === bucket.value ? "is-active" : ""}"
            type="button"
            role="tab"
            aria-selected="${activeBucket.value === bucket.value ? "true" : "false"}"
            data-studio-bucket="${escapeHtml(bucket.value)}"
            ${bucket.total ? "" : "disabled"}
          >
            <span class="studio-bucket-label">${escapeHtml(bucket.label)}</span>
            <span class="studio-bucket-copy">${bucket.total} item${bucket.total === 1 ? "" : "s"}</span>
          </button>
        `).join("")}
      </div>
      <div class="studio-review-workbench">
        <aside class="studio-section-nav">
          <div class="studio-section-nav-label">Sections</div>
          ${sectionButtons || `<div class="empty-inline">${escapeHtml(activeBucket.emptyMessage)}</div>`}
        </aside>
        <div class="studio-section-stage">
          ${sectionBody}
        </div>
      </div>
    </div>
  `;

  for (const button of elements.profileReviewSections.querySelectorAll("[data-studio-bucket]")) {
    button.addEventListener("click", () => {
      state.profileStudioBucket = button.dataset.studioBucket;
      renderProfileStudioReview();
    });
  }

  for (const button of elements.profileReviewSections.querySelectorAll("[data-studio-section]")) {
    button.addEventListener("click", () => {
      state.profileStudioSectionByBucket[state.profileStudioBucket] = button.dataset.studioSection;
      renderProfileStudioReview();
    });
  }

  for (const button of elements.profileReviewSections.querySelectorAll("[data-claim-action]")) {
    button.addEventListener("click", () => submitStructuredProfileClaim(button));
  }
}

function renderProfileStudioDiagnostics() {
  if (!elements.profileDiagnosticsSummary || !elements.profileDiagnosticsSources || !elements.profileDiagnosticsRecords) {
    return;
  }
  const diagnostics = state.profileStudioReview?.diagnostics;
  if (!diagnostics) {
    elements.profileDiagnosticsSummary.innerHTML = '<div class="empty-state">Correction diagnostics will appear after review data loads.</div>';
    elements.profileDiagnosticsSources.innerHTML = '<div class="empty-state">Parser diagnostics will appear after documents are processed.</div>';
    elements.profileDiagnosticsRecords.innerHTML = '<div class="empty-state">Experience, project, education, and summary frames will appear after review data loads.</div>';
    return;
  }

  const correction = diagnostics.correction || {};
  const actionCounts = correction.action_counts || {};
  const topReasons = correction.top_reason_codes || {};
  elements.profileDiagnosticsSummary.innerHTML = `
    <div class="meta-row">
      <span class="chip ${correction.embedding_retrieval_enabled ? "success" : "warning"}">${correction.embedding_retrieval_enabled ? "Embeddings On" : "Embeddings Off"}</span>
      <span class="chip ${correction.llm_arbiter_enabled ? "success" : "warning"}">${correction.llm_arbiter_enabled ? "Arbiter On" : "Arbiter Off"}</span>
      <span class="chip">${escapeHtml(correction.llm_arbiter_provider || "openai")}</span>
    </div>
    <div class="detail-grid">
      ${fieldPreviewCard("Runtime", [
        correction.correction_embedding_model ? `Embeddings: ${correction.correction_embedding_provider || "openai"} · ${correction.correction_embedding_model}` : "Embeddings: disabled",
        correction.llm_arbiter_model ? `Arbiter: ${correction.llm_arbiter_model}` : "Arbiter: disabled",
        `Cache entries: ${correction.correction_embedding_cache_entries || 0}`,
      ])}
      ${fieldPreviewCard("Signals", [
        `Semantic matches: ${correction.semantic_matches || 0}`,
        `Arbiter decisions: ${correction.llm_arbiter_decisions || 0}`,
        `Section suggestions: ${correction.section_suggestions || 0}`,
      ])}
      ${fieldPreviewCard("Cache", [
        `Hits: ${correction.correction_embedding_cache_hits || 0}`,
        `Misses: ${correction.correction_embedding_cache_misses || 0}`,
      ])}
      ${fieldPreviewCard("Resolver actions", Object.entries(actionCounts).map(([name, count]) => `${formatSectionLabel(name)}: ${count}`))}
    </div>
    <div class="stack-list compact-stack">
      ${Object.keys(topReasons).length
        ? Object.entries(topReasons).map(([reason, count]) => `<div class="detail-line">${escapeHtml(String(reason).replaceAll("_", " "))} · ${escapeHtml(String(count))}</div>`).join("")
        : '<div class="detail-line">No correction reasons recorded yet.</div>'}
    </div>
  `;

  const parserSources = diagnostics.parser_sources || [];
  elements.profileDiagnosticsSources.innerHTML = parserSources.length
    ? parserSources.map((source) => `
        <article class="detail-card">
          <div class="meta-row">
            <strong>${escapeHtml(source.filename)}</strong>
            ${source.validation_status ? `<span class="chip ${statusChipClass(source.validation_status)}">${escapeHtml(String(source.validation_status).replaceAll("_", " ").toUpperCase())}</span>` : ""}
            ${source.embedding_status ? `<span class="chip">${escapeHtml(source.embedding_status)}</span>` : ""}
          </div>
          <div class="detail-line">${escapeHtml(source.parser_backend || "parser")} · ${escapeHtml(source.extraction_mode || "mode")} · score ${escapeHtml(String(source.validation_score ?? "--"))}</div>
          <div class="detail-line">${escapeHtml(source.document_role || "general_resume")} · ${escapeHtml(source.profile_focus || "master")} · quality ${escapeHtml(String(source.source_quality ?? "--"))}</div>
          <div class="detail-line">${escapeHtml(String(source.page_count || 0))} pages · ${escapeHtml(String(source.block_count || 0))} blocks · ${escapeHtml(String(source.warning_count || 0))} warnings</div>
          <div class="tag-row">
            ${Object.entries(source.section_counts || {}).length
              ? Object.entries(source.section_counts || {}).map(([section, count]) => `<span class="tag">${escapeHtml(formatSectionLabel(section))} · ${escapeHtml(String(count))}</span>`).join("")
              : '<span class="empty-inline">No detected sections reported.</span>'}
          </div>
        </article>
      `).join("")
    : '<div class="empty-state">Parser diagnostics will appear after documents are processed.</div>';

  const recordFrames = diagnostics.record_frames || [];
  elements.profileDiagnosticsRecords.innerHTML = recordFrames.length
    ? recordFrames.map((documentFrames) => {
      const sections = [
        ["experience_frames", "Experience Frames"],
        ["project_frames", "Project Frames"],
        ["education_frames", "Education Frames"],
        ["summary_frames", "Summary Frames"],
        ["leadership_frames", "Leadership Frames"],
        ["freelance_frames", "Freelance Frames"],
      ];
      const sectionMarkup = sections
        .map(([key, label]) => {
          const frames = documentFrames[key] || [];
          if (!frames.length) {
            return "";
          }
          return `
            <div class="frame-group">
              <div class="detail-line frame-group-title">${escapeHtml(label)} · ${escapeHtml(String(frames.length))}</div>
              <div class="stack-list compact-stack">
                ${frames.map((frame) => {
                  const headline = frame.organization
                    ? `${frame.organization}${frame.title ? ` · ${frame.title}` : ""}`
                    : (frame.name || frame.text || frame.degree || "Frame");
                  const details = [
                    frame.start_date || frame.end_date ? `Dates: ${[frame.start_date, frame.end_date].filter(Boolean).join(" - ")}` : "",
                    frame.location ? `Location: ${frame.location}` : "",
                    frame.summary ? `Summary: ${frame.summary}` : "",
                    frame.text ? `Text: ${frame.text}` : "",
                    frame.degree || frame.institution ? `Education: ${[frame.degree, frame.institution].filter(Boolean).join(" · ")}` : "",
                    Array.isArray(frame.highlights) && frame.highlights.length ? `Bullets: ${frame.highlights.length}` : "",
                    Array.isArray(frame.technologies) && frame.technologies.length ? `Tech: ${frame.technologies.slice(0, 6).join(", ")}` : "",
                    Array.isArray(frame.source_block_ids) && frame.source_block_ids.length ? `Blocks: ${frame.source_block_ids.slice(0, 4).join(", ")}` : "",
                  ].filter(Boolean);
                  return `
                    <article class="detail-card frame-record">
                      <div class="meta-row">
                        <strong>${escapeHtml(headline)}</strong>
                        <span class="chip">${confidencePercent(frame.confidence || 0)}%</span>
                      </div>
                      ${details.map((detail) => `<div class="detail-line">${escapeHtml(detail)}</div>`).join("")}
                    </article>
                  `;
                }).join("")}
              </div>
            </div>
          `;
        })
        .filter(Boolean)
        .join("");

      return `
        <article class="detail-card">
          <div class="meta-row">
            <strong>${escapeHtml(documentFrames.filename || "Document")}</strong>
          </div>
          ${sectionMarkup || '<div class="empty-state">No assembled frames were generated for this document.</div>'}
        </article>
      `;
    }).join("")
    : '<div class="empty-state">Experience, project, education, and summary frames will appear after review data loads.</div>';
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

function readStructuredClaimValue(card, section) {
  const read = (name) => card.querySelector(`[data-claim-input="${name}"]`)?.value.trim() || "";
  if (section === "identity") {
    return { value: read("value") };
  }
  if (section === "skills") {
    return { name: read("name") };
  }
  if (section === "public_profiles") {
    return { label: read("label"), url: read("url") };
  }
  if (section === "work_experience") {
    return {
      title: read("title"),
      organization: read("organization"),
      location: read("location"),
      start_date: read("start_date"),
      end_date: read("end_date"),
      summary: read("summary"),
      highlights: read("highlights").split("\n").map((item) => item.trim()).filter(Boolean),
      technologies: [],
      links: [],
      source_document_ids: [],
    };
  }
  if (section === "projects") {
    return {
      name: read("name"),
      summary: read("summary"),
      technologies: read("technologies").split(",").map((item) => item.trim()).filter(Boolean),
      links: read("links").split("\n").map((item) => item.trim()).filter(Boolean),
      highlights: [],
      source_document_ids: [],
    };
  }
  if (section === "education") {
    return {
      degree: read("degree"),
      institution: read("institution"),
      field_of_study: read("field_of_study"),
      start_date: read("start_date"),
      end_date: read("end_date"),
      summary: read("summary"),
      technologies: [],
      highlights: [],
      links: [],
      source_document_ids: [],
    };
  }
  if (section === "certifications") {
    return {
      name: read("name"),
      issuer: read("issuer"),
      start_date: read("start_date"),
      credential_id: read("credential_id"),
      summary: read("summary"),
      technologies: [],
      highlights: [],
      links: [],
      source_document_ids: [],
    };
  }
  const rawJson = read("raw_json");
  try {
    return rawJson ? JSON.parse(rawJson) : {};
  } catch {
    return {};
  }
}

function convertStructuredClaimValue(value, fromSection, toSection) {
  if (fromSection === toSection) {
    return value;
  }
  const primaryText = value.value || value.name || value.title || value.degree || value.organization || value.institution || value.summary || "";
  if (toSection === "identity") {
    return { value: primaryText };
  }
  if (toSection === "skills") {
    return { name: primaryText };
  }
  if (toSection === "public_profiles") {
    return {
      label: value.label || "Link",
      url: value.url || (value.links || [])[0] || "",
    };
  }
  if (toSection === "projects") {
    return {
      name: value.name || value.title || primaryText,
      summary: value.summary || "",
      technologies: value.technologies || [],
      links: value.links || [],
      highlights: value.highlights || [],
      source_document_ids: value.source_document_ids || [],
    };
  }
  if (toSection === "work_experience") {
    return {
      title: value.title || value.name || primaryText,
      organization: value.organization || value.issuer || "",
      location: value.location || "",
      start_date: value.start_date || "",
      end_date: value.end_date || "",
      summary: value.summary || "",
      highlights: value.highlights || [],
      technologies: value.technologies || [],
      links: value.links || [],
      source_document_ids: value.source_document_ids || [],
    };
  }
  if (toSection === "education") {
    return {
      degree: value.degree || value.title || value.name || primaryText,
      institution: value.institution || value.organization || value.issuer || "",
      field_of_study: value.field_of_study || "",
      start_date: value.start_date || "",
      end_date: value.end_date || "",
      summary: value.summary || "",
      technologies: [],
      highlights: [],
      links: value.links || [],
      source_document_ids: value.source_document_ids || [],
    };
  }
  if (toSection === "certifications") {
    return {
      name: value.name || value.degree || primaryText,
      issuer: value.issuer || value.organization || value.institution || "",
      start_date: value.start_date || "",
      credential_id: value.credential_id || "",
      summary: value.summary || "",
      technologies: [],
      highlights: [],
      links: value.links || [],
      source_document_ids: value.source_document_ids || [],
    };
  }
  return value;
}

async function submitStructuredProfileClaim(button) {
  const card = button.closest("[data-claim-id]");
  if (!card) {
    return;
  }
  const claimId = card.dataset.claimId;
  const originalSection = card.dataset.claimSection;
  const nextSection = card.querySelector("[data-claim-section-select]")?.value || card.dataset.claimSection;
  const action = button.dataset.claimAction;
  const payload = { section: nextSection };
  if (action === "reject") {
    payload.status = "rejected";
  } else {
    const originalValue = readStructuredClaimValue(card, originalSection);
    payload.value_json = convertStructuredClaimValue(originalValue, originalSection, nextSection);
    payload.status = action === "accept" ? "accepted" : "edited";
  }

  try {
    setLoading(button, true, action === "accept" ? "Accepting..." : action === "reject" ? "Rejecting..." : "Saving...");
    await apiFetch(withProfileQuery(`/profile/studio/claims/${claimId}`), {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await Promise.all([loadProfileStudioReview(), loadProfileOverview(), loadSummary()]);
    showToast(action === "reject" ? "Rejected extracted item." : action === "accept" ? "Accepted extracted item." : "Saved review edit.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(button, false, button.dataset.originalLabel || button.textContent);
  }
}

async function acceptAllProfileStudioClaims() {
  try {
    setLoading(elements.acceptAllReviewButton, true, "Accepting...");
    await apiFetch(withProfileQuery("/profile/studio/claims/accept-all"), { method: "POST" });
    await Promise.all([loadProfileStudioReview(), loadProfileOverview(), loadSummary()]);
    showToast("Accepted all extracted profile items.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.acceptAllReviewButton, false, "Accept All");
  }
}

async function saveCanonicalProfile() {
  try {
    setLoading(elements.saveCanonicalButton, true, "Saving...");
    state.profileOverview = await apiFetch(withProfileQuery("/profile/studio/save", { view: state.profileView }), { method: "POST" });
    renderCurrentProfileMeta();
    renderProfileOverviewSnapshot();
    renderProfileViewControl();
    await Promise.all([loadProfileStudioReview(), loadSummary()]);
    showToast("Saved canonical profile memory.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.saveCanonicalButton, false, "Save Profile");
  }
}

async function resetCanonicalProfile() {
  const confirmed = window.confirm("Reset the saved canonical profile and go back to the latest extracted preview?");
  if (!confirmed) {
    return;
  }

  try {
    setLoading(elements.resetCanonicalButton, true, "Resetting...");
    state.profileOverview = await apiFetch(withProfileQuery("/profile/studio/canonical", { view: state.profileView }), { method: "DELETE" });
    renderCurrentProfileMeta();
    renderProfileOverviewSnapshot();
    renderProfileViewControl();
    await Promise.all([loadProfileStudioReview(), loadSummary()]);
    showToast("Returned to the extracted profile preview.");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.resetCanonicalButton, false, "Reset to Extracted");
  }
}

async function loadProfileOverview() {
  state.profileOverview = await apiFetch(withProfileQuery("/profile/overview", { view: state.profileView }));
  renderCurrentProfileMeta();
  renderProfileOverviewSnapshot();
  renderProfileViewControl();
  renderProfileEditor();
}

async function loadProfileStudioReview() {
  if (!elements.profileReviewSections) {
    return;
  }
  state.profileStudioReview = await apiFetch(withProfileQuery("/profile/studio/review", { view: state.profileView }));
  state.profileStudioPreview = state.profileStudioReview.review_preview_profile || null;
  state.profileFusion = state.profileStudioReview.fusion || null;
  renderProfileStudioReview();
  renderProfileFusion();
  renderProfileStudioDiagnostics();
  renderProfileOverviewSnapshot();
  renderProfileViewControl();
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
  if (!elements.parserBackendSelect && !elements.benchmarkBackendSelect && page !== "evidence" && page !== "benchmarks") {
    return;
  }
  state.parserBackends = await apiFetch("/resume-parsers");
  ensureSelectedParserBackend();
  renderParserBackendControls();
  renderBenchmarkBackendControls();
  renderSummary();
}

async function loadBenchmarkDataset() {
  if (!elements.benchmarkRunButton) {
    return;
  }
  state.benchmarkDataset = await apiFetch("/benchmark/dataset");
  if (elements.benchmarkLimitInput && !elements.benchmarkLimitInput.value) {
    elements.benchmarkLimitInput.value = String(Math.min(Math.max(state.benchmarkDataset?.total_cases || 1, 1), 12));
  }
  renderBenchmarkDataset();
}

async function loadLatestBenchmarkReport() {
  if (!elements.benchmarkRunButton) {
    return;
  }
  try {
    state.benchmarkReport = await apiFetch("/benchmark/latest");
  } catch (error) {
    if (error.status !== 404) {
      throw error;
    }
    state.benchmarkReport = null;
  }
  renderBenchmarkDataset();
  renderBenchmarkReport();
}

async function runBenchmarkReport() {
  if (!elements.benchmarkRunButton) {
    return;
  }

  try {
    setLoading(elements.benchmarkRunButton, true, "Running...");
    const selectedCategory = benchmarkCategoryValue();
    state.benchmarkReport = await apiFetch("/benchmark/run", {
      method: "POST",
      body: JSON.stringify({
        parser_backend: elements.benchmarkBackendSelect?.value || ensureSelectedParserBackend(),
        limit: benchmarkLimitValue(),
        categories: selectedCategory ? [selectedCategory] : [],
        allow_remote_models: Boolean(elements.benchmarkRemoteToggle?.checked),
      }),
    });
    renderBenchmarkDataset();
    renderBenchmarkReport();
    showToast(`Benchmark completed for ${state.benchmarkReport.processed_cases} resumes.`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setLoading(elements.benchmarkRunButton, false, "Run benchmark");
  }
}

async function loadSummary() {
  state.summary = await apiFetch(withProfileQuery("/dashboard/summary"));
  renderSummary();
}

async function loadRuntimeHealth() {
  try {
    state.health = await apiFetch("/health");
  } catch {
    state.health = null;
  }
  renderRuntimeHealth();
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
  await Promise.all([loadResumeParsers(), loadRuntimeHealth(), loadSummary(), loadDocuments(), loadProfileOverview()]);
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
  await loadSummary();
  await loadProfileOverview();
  await loadProfileStudioReview();
}

async function refreshBenchmarksPage() {
  await loadResumeParsers();
  await loadBenchmarkDataset();
  await loadLatestBenchmarkReport();
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
  const files = selectedUploadFiles();
  const profile = currentProfile();
  if (!files.length) {
    showToast("Pick at least one file before uploading.", "error");
    return;
  }
  if (!profile) {
    showToast("Choose a profile first.", "error");
    window.location.href = "/profiles/select";
    return;
  }

  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  formData.append("profile_id", profile.id);
  formData.append("parser_backend", ensureSelectedParserBackend());

  try {
    setLoading(elements.uploadButton, true, files.length > 1 ? "Uploading files..." : "Uploading...");
    const response = await apiFetch("/documents/upload-batch", {
      method: "POST",
      body: formData,
    });
    const uploads = Array.isArray(response.uploads) ? response.uploads : [];
    const failures = Array.isArray(response.failures) ? response.failures : [];
    for (const item of uploads) {
      if (item?.document?.id) {
        delete state.parserComparisons[item.document.id];
      }
    }
    if (uploads.length) {
      state.selectedDocumentId = uploads[uploads.length - 1].document.id;
    }
    if (elements.fileInput) {
      elements.fileInput.value = "";
    }
    refreshSelectedUploadLabel([]);
    await refreshEvidencePage();
    if (elements.uploadStatus) {
      const detected = response.auto_profile_sections?.length
        ? `Updated ${response.auto_profile_sections.map(formatSectionLabel).join(", ")}.`
        : uploads.length
          ? "Upload completed, but only light profile signals were found."
          : "No files were ingested.";
      const failureText = failures.length
        ? ` ${failures.length} file${failures.length === 1 ? "" : "s"} could not be processed.`
        : "";
      elements.uploadStatus.textContent = `${detected}${failureText} The current profile was refreshed automatically.`;
    }
    const warningCopy = response.warnings?.length ? ` ${response.warnings.join(" ")}` : "";
    if (!uploads.length && failures.length) {
      showToast(`None of the selected files could be uploaded. ${failures[0].filename}: ${failures[0].detail}`, "error");
      return;
    }
    const uploadedCount = uploads.length;
    const successCopy = uploadedCount === 1
      ? `Uploaded ${uploads[0].document.filename}.`
      : `Uploaded ${uploadedCount} files.`;
    if (failures.length) {
      const firstFailure = failures[0];
      showToast(`${successCopy} ${failures.length} failed, starting with ${firstFailure.filename}: ${firstFailure.detail}.${warningCopy}`, "error");
    } else {
      showToast(`${successCopy} The profile was updated automatically.${warningCopy}`);
    }
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
      refreshSelectedUploadLabel();
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
        refreshSelectedUploadLabel(Array.from(files));
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
  elements.acceptAllReviewButton?.addEventListener("click", acceptAllProfileStudioClaims);
  elements.saveCanonicalButton?.addEventListener("click", saveCanonicalProfile);
  elements.resetCanonicalButton?.addEventListener("click", resetCanonicalProfile);
  elements.profileViewSelect?.addEventListener("change", async () => {
    rememberSelectedProfileView(elements.profileViewSelect.value);
    await Promise.all([loadProfileStudioReview(), loadProfileOverview()]);
  });
}

function bindBenchmarksPage() {
  bindSharedWorkspaceActions();
  elements.benchmarkBackendSelect?.addEventListener("change", () => {
    rememberSelectedParserBackend(elements.benchmarkBackendSelect.value);
    renderBenchmarkBackendControls();
  });
  elements.benchmarkRunButton?.addEventListener("click", runBenchmarkReport);
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

async function initBenchmarksPage() {
  const authenticated = await ensureAuthenticated();
  if (!authenticated) {
    return;
  }
  bindBenchmarksPage();
  await refreshBenchmarksPage();
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
    if (page === "benchmarks") {
      await initBenchmarksPage();
      return;
    }
    await initEvidencePage();
  } catch (error) {
    showToast(error.message || "Something went wrong.", "error");
  }
}

init();
