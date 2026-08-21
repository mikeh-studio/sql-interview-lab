"use strict";

const state = {
  options: null,
  selectedCompany: null,
  dialect: "duckdb",
  difficulty: "medium",
  mode: "standard",
  roleTrack: "product_analytics",
  modelPolicy: "cli_default",
  historyId: null,
  questionSet: null,
  questions: [],
  activeQuestionIndex: 0,
  sessionId: null,
  exercise: null,
  starterSql: "",
  lastOutput: null,
  lastGrade: null,
  lastDoctor: null,
  generationId: null,
  generationPending: false,
  generationStartedAt: null,
};

const elements = {};
let toastTimer = null;
let loadingTimer = null;
let generationPollCancelled = false;

document.addEventListener("DOMContentLoaded", async () => {
  collectElements();
  bindEvents();
  try {
    state.options = await fetchJson("/api/options");
    renderCompanyCards();
    renderDialects();
    renderRoleTracks();
    renderModelConfiguration();
  } catch (error) {
    showToast(error.message, true);
  }
});

function collectElements() {
  const ids = [
    "setupView", "companyStep", "configStep", "companyGrid", "companyContinue",
    "historyButton", "labHistoryButton", "historyModal", "historyList", "historyStorage",
    "closeHistoryButton", "clearHistoryButton",
    "companyHelp", "customCompanyField", "customCompanyInput", "backToCompanies",
    "selectedCompanySummary", "dialectSelect", "dialectHelp", "additionalContextInput",
    "saveHistoryInput", "reuseDatasetPreference", "reuseDatasetInput",
    "providerSelect", "modeChoices", "modeHelp", "roleTrackField", "roleTrackChoices",
    "roleTrackHelp", "generationStatus", "generationStatusMessage",
    "modelConfiguration", "modelDefaultSummary", "modelDefaultHelp",
    "modelOverrideFields", "modelOverrideInput", "reasoningEffortInput",
    "resetModelConfiguration", "modelStatus",
    "dismissGenerationStatus",
    "difficultyChoices", "demoButton", "generateButton", "labView", "labCompany",
    "difficultyBadge", "questionNavigator", "engineStatus", "engineStatusLabel",
    "dialectBadge", "editorDialect",
    "companyBadge", "questionTypeBadge", "challengePosition", "challengeTitle", "businessContext",
    "requirementsToggleButton", "requirementsPanel", "requirementsList",
    "clarificationsSection", "clarificationsList",
    "hintArea", "hintButton", "solutionButton", "tablePreviews",
    "sqlEditor", "editorLines", "resetButton", "runButton", "submitButton",
    "outputResult", "testResult", "doctorPanel", "doctorResult", "doctorButton",
    "executionMeta", "testStatusDot", "doctorStatusDot",
    "newQuestionButton", "loadingOverlay", "loadingTitle", "loadingMessage",
    "loadingElapsed", "loadingProviderMeta", "loadingEvents",
    "generationProgress", "generationProgressTitle", "generationProgressMessage",
    "generationProgressMeta",
    "solutionModal", "solutionModalBody", "closeSolutionButton", "toast", "questionPanel",
    "schemaPanel",
  ];
  for (const id of ids) elements[id] = document.getElementById(id);
}

function bindEvents() {
  elements.companyContinue.addEventListener("click", showConfigStep);
  elements.historyButton.addEventListener("click", openHistory);
  elements.labHistoryButton.addEventListener("click", openHistory);
  elements.closeHistoryButton.addEventListener("click", closeHistory);
  elements.clearHistoryButton.addEventListener("click", clearHistory);
  elements.customCompanyInput.addEventListener("input", updateCustomCompany);
  elements.backToCompanies.addEventListener("click", showCompanyStep);
  elements.dialectSelect.addEventListener("change", handleDialect);
  elements.providerSelect.addEventListener("change", handleProvider);
  elements.difficultyChoices.addEventListener("click", handleDifficulty);
  elements.modeChoices.addEventListener("click", handleMode);
  elements.roleTrackChoices.addEventListener("change", handleRoleTrack);
  elements.modelConfiguration.addEventListener("change", handleModelPolicy);
  elements.resetModelConfiguration.addEventListener("click", resetModelConfiguration);
  elements.generateButton.addEventListener("click", () => generateExercise(false));
  elements.demoButton.addEventListener("click", () => generateExercise(true));
  elements.dismissGenerationStatus.addEventListener("click", clearGenerationStatus);
  elements.runButton.addEventListener("click", runQuery);
  elements.submitButton.addEventListener("click", submitQuery);
  elements.doctorButton.addEventListener("click", reviewQuery);
  elements.resetButton.addEventListener("click", resetEditor);
  elements.hintButton.addEventListener("click", revealHint);
  elements.requirementsToggleButton.addEventListener("click", toggleRequirements);
  elements.solutionButton.addEventListener("click", openSolutionModal);
  elements.closeSolutionButton.addEventListener("click", closeSolutionModal);
  elements.newQuestionButton.addEventListener("click", startNewQuestion);
  elements.sqlEditor.addEventListener("input", updateEditorLines);
  elements.sqlEditor.addEventListener("scroll", () => {
    elements.editorLines.scrollTop = elements.sqlEditor.scrollTop;
  });
  elements.sqlEditor.addEventListener("keydown", handleEditorKeys);

  document.querySelectorAll("[data-pane-tab]").forEach((button) => {
    button.addEventListener("click", () => activatePaneTab(button.dataset.paneTab));
  });
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    button.addEventListener("click", () => activateResultTab(button.dataset.resultTab));
  });
  elements.solutionModal.addEventListener("click", (event) => {
    if (event.target === elements.solutionModal) closeSolutionModal();
  });
  elements.historyModal.addEventListener("click", (event) => {
    if (event.target === elements.historyModal) closeHistory();
  });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail;
    if (Array.isArray(detail)) {
      throw new Error(detail.map((item) => item.msg).join("; "));
    }
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  return payload;
}

function renderCompanyCards() {
  elements.companyGrid.replaceChildren();
  for (const company of state.options.companies) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "company-card";
    card.dataset.companyId = company.id;
    card.dataset.accent = company.accent;
    card.setAttribute("aria-pressed", "false");

    const check = document.createElement("span");
    check.className = "company-card-check";
    check.textContent = "✓";
    const logo = createCompanyLogo(company);
    const title = document.createElement("h2");
    title.textContent = company.name;
    const description = document.createElement("p");
    description.textContent = company.description;
    card.append(check, logo, title, description);
    card.addEventListener("click", () => selectCompany(company, card));
    elements.companyGrid.append(card);
  }
}

function createCompanyLogo(company, fallbackText = company.monogram) {
  const logo = document.createElement("span");
  logo.className = "company-logo";
  if (company.logo_path) {
    const image = document.createElement("img");
    image.src = company.logo_path;
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    image.decoding = "async";
    logo.append(image);
  } else {
    logo.textContent = fallbackText;
  }
  return logo;
}

function selectCompany(company, selectedCard) {
  state.selectedCompany = company;
  elements.companyGrid.querySelectorAll(".company-card").forEach((card) => {
    const selected = card === selectedCard;
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-pressed", String(selected));
  });
  elements.customCompanyField.hidden = !company.custom;
  if (company.custom) {
    updateCustomCompany();
    elements.customCompanyInput.focus();
  } else {
    elements.companyContinue.disabled = false;
    elements.companyHelp.textContent = `${company.name} selected. Continue when you are ready.`;
  }
}

function updateCustomCompany() {
  if (!state.selectedCompany?.custom) return;
  const companyName = elements.customCompanyInput.value.trim();
  elements.companyContinue.disabled = !companyName;
  elements.companyHelp.textContent = companyName
    ? `${companyName} selected. Continue when you are ready.`
    : "Enter a company or organization name to continue.";
}

function resolvedCompanyName() {
  if (!state.selectedCompany) return "";
  return state.selectedCompany.custom
    ? elements.customCompanyInput.value.trim()
    : state.selectedCompany.name;
}

function renderDialects() {
  elements.dialectSelect.replaceChildren();
  for (const dialect of state.options.dialects) {
    const option = document.createElement("option");
    option.value = dialect.id;
    option.textContent = `${dialect.name} · ${dialect.execution_label}`;
    elements.dialectSelect.append(option);
  }
  elements.dialectSelect.value = state.dialect;
  handleDialect();
}

function renderRoleTracks() {
  elements.roleTrackChoices.replaceChildren();
  const roles = [...state.options.roles].sort((left, right) =>
    left.name.localeCompare(right.name),
  );
  for (const role of roles) {
    const option = document.createElement("label");
    option.className = "focus-area-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.name = "focus-area";
    input.value = role.id;
    input.checked = role.id === state.roleTrack;
    const name = document.createElement("span");
    name.textContent = role.name;
    option.append(input, name);
    elements.roleTrackChoices.append(option);
  }
  updateRoleTrackHelp();
}

function formatConfigurationValue(value, fallback) {
  return value ? value : fallback;
}

function formatReasoningEffort(value) {
  if (!value) return "CLI default reasoning";
  return `${value.charAt(0).toUpperCase()}${value.slice(1)} reasoning`;
}

function renderModelConfiguration() {
  const configuration = state.options.codex_configuration || {};
  const model = formatConfigurationValue(configuration.model, "Codex chooses at run time");
  elements.modelDefaultSummary.textContent =
    `${model} · ${formatReasoningEffort(configuration.reasoning_effort)}`;
  if (configuration.source === "cli_runtime") {
    elements.modelDefaultHelp.textContent =
      "The configured command ignores base user config; Codex resolves settings when generation starts.";
  } else if (
    configuration.model_is_authoritative ||
    configuration.reasoning_effort_is_authoritative
  ) {
    elements.modelDefaultHelp.textContent =
      "Includes explicit configured-command values; Codex resolves any remaining settings at run time.";
  } else if (configuration.source === "profile") {
    elements.modelDefaultHelp.textContent =
      "Detected from the active Codex profile; project or managed settings may override it.";
  } else {
    elements.modelDefaultHelp.textContent =
      "Detected from Codex user settings; project or managed settings may override it.";
  }
  if (!elements.modelOverrideInput.value && configuration.model) {
    elements.modelOverrideInput.value = configuration.model;
  }
  handleProvider();
  syncModelPolicy();
}

function handleProvider() {
  const isCodex = elements.providerSelect.value === "codex";
  elements.modelConfiguration.hidden = !isCodex;
}

function handleModelPolicy(event) {
  const input = event.target.closest('input[name="model-policy"]');
  if (!input) return;
  state.modelPolicy = input.value;
  syncModelPolicy();
}

function syncModelPolicy() {
  elements.modelConfiguration.querySelectorAll('input[name="model-policy"]').forEach((input) => {
    input.checked = input.value === state.modelPolicy;
  });
  elements.modelOverrideFields.hidden = state.modelPolicy !== "override";
}

function resetModelConfiguration() {
  state.modelPolicy = "cli_default";
  elements.modelOverrideInput.value = state.options.codex_configuration?.model || "";
  elements.reasoningEffortInput.value = "";
  syncModelPolicy();
}

function handleRoleTrack(event) {
  const input = event.target.closest('input[type="checkbox"]');
  if (!input) return;
  if (!input.checked) {
    input.checked = true;
    return;
  }
  state.roleTrack = input.value;
  elements.roleTrackChoices.querySelectorAll('input[type="checkbox"]').forEach((choice) => {
    choice.checked = choice === input;
  });
  updateRoleTrackHelp();
}

function updateRoleTrackHelp() {
  const role = state.options.roles.find((item) => item.id === state.roleTrack);
  if (role) elements.roleTrackHelp.textContent = role.description;
}

function syncRoleTrackChoices() {
  elements.roleTrackChoices.querySelectorAll('input[type="checkbox"]').forEach((choice) => {
    choice.checked = choice.value === state.roleTrack;
  });
  updateRoleTrackHelp();
}

function selectedDialect() {
  return state.options.dialects.find((dialect) => dialect.id === state.dialect);
}

function handleDialect() {
  state.dialect = elements.dialectSelect.value || "duckdb";
  const dialect = selectedDialect();
  if (dialect) elements.dialectHelp.textContent = dialect.execution_label;
  updateDemoAvailability();
}

function updateDemoAvailability() {
  elements.demoButton.hidden = !(
    state.selectedCompany?.demo_available && state.dialect === "duckdb" &&
    state.mode === "standard"
  );
}

function showConfigStep() {
  const companyName = resolvedCompanyName();
  if (!companyName) return;
  elements.companyStep.hidden = true;
  elements.configStep.hidden = false;
  elements.selectedCompanySummary.replaceChildren();
  elements.selectedCompanySummary.dataset.accent = state.selectedCompany.accent;
  const logo = createCompanyLogo(state.selectedCompany, companyName.charAt(0).toUpperCase());
  const copy = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = companyName;
  const caption = document.createElement("small");
  caption.textContent = "Selected company style";
  copy.append(name, caption);
  elements.selectedCompanySummary.append(logo, copy);
  updateDemoAvailability();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showCompanyStep() {
  elements.configStep.hidden = true;
  elements.companyStep.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function handleDifficulty(event) {
  const button = event.target.closest("[data-difficulty]");
  if (!button) return;
  state.difficulty = button.dataset.difficulty;
  elements.difficultyChoices.querySelectorAll("button").forEach((choice) => {
    choice.classList.toggle("selected", choice === button);
  });
}

function handleMode(event) {
  const button = event.target.closest("[data-mode]");
  if (!button) return;
  state.mode = button.dataset.mode;
  elements.modeChoices.querySelectorAll("button").forEach((choice) => {
    choice.classList.toggle("selected", choice === button);
  });
  const advanced = state.mode === "advanced";
  elements.roleTrackField.hidden = !advanced;
  elements.reuseDatasetPreference.hidden = !advanced;
  elements.modeHelp.textContent = advanced
    ? "A SQL build, SQL debugging task, and analytical case with staged interviewer details and a self-review rubric."
    : "Three deterministic SQL questions with exact requirements available inline.";
  updateDemoAvailability();
}

async function generateExercise(demo) {
  const companyName = resolvedCompanyName();
  if (!companyName) {
    showCompanyStep();
    return;
  }
  const useModelOverride = !demo && elements.providerSelect.value === "codex" &&
    state.modelPolicy === "override";
  const modelOverride = useModelOverride
    ? elements.modelOverrideInput.value.trim()
    : "";
  const reasoningEffortOverride = useModelOverride
    ? elements.reasoningEffortInput.value.trim()
    : "";
  if (useModelOverride && !modelOverride && !reasoningEffortOverride) {
    showToast("Enter a model ID or reasoning effort, or follow the Codex CLI settings.", true);
    elements.modelOverrideInput.focus();
    return;
  }
  const payload = {
    company: companyName,
    dialect: state.dialect,
    difficulty: state.difficulty,
    additional_context: elements.additionalContextInput.value.trim(),
    provider: elements.providerSelect.value,
    demo,
    save_history: elements.saveHistoryInput.checked,
    mode: state.mode,
    role_track: state.mode === "advanced" ? state.roleTrack : null,
    reuse_cached_dataset: elements.reuseDatasetInput.checked,
    model_override: modelOverride || null,
    reasoning_effort_override: reasoningEffortOverride || null,
  };
  clearGenerationStatus();
  showLoading(demo);
  try {
    if (!demo && state.mode === "advanced") {
      const started = await fetchJson("/api/generations", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.generationId = started.generation_id;
      state.generationPending = true;
      state.generationStartedAt = Date.now();
      generationPollCancelled = false;
      await pollGeneration(started.generation_id);
      return;
    }
    const response = await fetchJson("/api/exercises", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    enterLab(response);
  } catch (error) {
    state.generationPending = false;
    if (state.questionSet?.generation_status === "running") {
      elements.generationProgress.hidden = false;
      elements.generationProgress.classList.add("failed");
      elements.generationProgressTitle.textContent = "Generation status was interrupted";
      elements.generationProgressMessage.textContent = error.message;
      updateGenerationControls();
    }
    showGenerationFailure(error.message);
    showToast(error.message, true, 12000);
  } finally {
    if (!state.generationPending) hideLoading();
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollGeneration(generationId) {
  let openedFirstQuestion = false;
  let consecutivePollFailures = 0;
  while (!generationPollCancelled) {
    let progress;
    try {
      progress = await fetchJson(`/api/generations/${generationId}`);
      consecutivePollFailures = 0;
    } catch (error) {
      consecutivePollFailures += 1;
      if (consecutivePollFailures >= 4) throw error;
      elements.loadingMessage.textContent = "Reconnecting to the local generation log…";
      await wait(1200);
      continue;
    }
    renderGenerationLog(progress);
    if (progress.partial_result && !openedFirstQuestion) {
      enterLab(progress.partial_result);
      openedFirstQuestion = true;
      hideLoading();
      renderInLabGenerationProgress(progress);
      showToast("Question 1 is ready. Questions 2 and 3 are continuing in the background.");
    } else if (openedFirstQuestion && progress.status === "running") {
      renderInLabGenerationProgress(progress);
    }
    if (progress.status === "complete") {
      state.generationPending = false;
      if (openedFirstQuestion) mergeProgressiveResult(progress.result);
      else enterLab(progress.result);
      elements.generationProgress.hidden = true;
      hideLoading();
      const tokenText = progress.telemetry.total_tokens == null
        ? "Token usage was not reported by the CLI."
        : `${progress.telemetry.total_tokens.toLocaleString()} tokens reported.`;
      showToast(`All 3 questions are ready. ${tokenText}`);
      return;
    }
    if (progress.status === "failed") {
      state.generationPending = false;
      hideLoading();
      if (openedFirstQuestion) {
        elements.generationProgressTitle.textContent = "Questions 2 and 3 could not finish";
        elements.generationProgressMessage.textContent = progress.error;
        elements.generationProgress.classList.add("failed");
        updateGenerationControls();
      } else {
        showGenerationFailure(progress.error || "Generation failed.");
      }
      throw new Error(progress.error || "Generation failed.");
    }
    await wait(900);
  }
}

function mergeProgressiveResult(result) {
  const current = state.questions[0];
  current.sql = elements.sqlEditor.value;
  state.questionSet = result;
  state.historyId = result.history_id;
  state.questions = result.questions.map((question, index) => index === 0
    ? { ...question, ...current, session_id: question.session_id }
    : {
        ...question,
        sql: question.latest_sql || "",
        passed: question.passed ?? null,
        detailsExpanded: false,
        clarifications: question.clarifications || [],
      });
  renderModelStatus(result.generation_telemetry);
  elements.challengePosition.textContent = `QUESTION 1 OF ${state.questions.length}`;
  renderQuestionNavigator();
  updateGenerationControls();
}

function renderGenerationLog(progress) {
  const latest = progress.events.at(-1);
  elements.loadingElapsed.textContent = `${Math.floor(progress.elapsed_seconds)}s elapsed`;
  if (latest) elements.loadingMessage.textContent = latest.message;
  elements.loadingEvents.replaceChildren();
  progress.events.slice(-5).forEach((event) => {
    const item = document.createElement("li");
    const elapsed = document.createElement("span");
    elapsed.textContent = `${Math.floor(event.elapsed_seconds)}s`;
    const message = document.createElement("span");
    message.textContent = event.message;
    item.append(elapsed, message);
    elements.loadingEvents.append(item);
  });
  elements.loadingProviderMeta.textContent = generationTelemetryText(progress.telemetry);
}

function generationTelemetryText(telemetry = {}) {
  const effort = telemetry.resolved_reasoning_effort || telemetry.reasoning_effort;
  const identity = [telemetry.provider, telemetry.resolved_model || telemetry.model, effort]
    .filter(Boolean)
    .join(" · ");
  const tokens = telemetry.total_tokens == null
    ? "tokens pending"
    : `${telemetry.total_tokens.toLocaleString()} tokens`;
  return `${identity || "CLI details pending"} · ${tokens}`;
}

function renderInLabGenerationProgress(progress) {
  elements.generationProgress.hidden = false;
  elements.generationProgress.classList.remove("failed");
  elements.generationProgressTitle.textContent = "Question 1 ready · building Questions 2 and 3";
  elements.generationProgressMessage.textContent = progress.events.at(-1)?.message || "Generation continues.";
  elements.generationProgressMeta.textContent = `${Math.floor(progress.elapsed_seconds)}s · ${generationTelemetryText(progress.telemetry)}`;
}

function showGenerationFailure(message) {
  elements.generationStatusMessage.textContent = message;
  elements.generationStatus.hidden = false;
}

function clearGenerationStatus() {
  elements.generationStatus.hidden = true;
  elements.generationStatusMessage.textContent = "";
}

function showLoading(demo) {
  elements.loadingOverlay.hidden = false;
  state.generationStartedAt = Date.now();
  elements.loadingEvents.replaceChildren();
  elements.loadingElapsed.textContent = "0s elapsed";
  elements.loadingProviderMeta.textContent = "Waiting for provider details";
  const messages = demo
    ? ["Loading the validated sample exercise…", "Seeding the visible DuckDB tables…"]
    : state.mode === "advanced"
    ? [
        "Calibrating questions to the selected role track.",
        "Building SQL construction, debugging, and analytical case tasks.",
        "Writing staged interviewer clarifications and deterministic requirements.",
        "Creating a self-review case rubric without automated case scoring.",
        `Validating all SQL deliverables with ${selectedDialect()?.execution_label || "DuckDB"}.`,
      ]
    : [
        "Creating one company-style schema and shared dataset.",
        "Generating visible data and hidden edge cases.",
        "Writing three distinct SQL interview questions.",
        "Checking the full set against the exercise schema.",
        `Validating all reference queries with ${selectedDialect()?.execution_label || "DuckDB"}.`,
      ];
  let index = 0;
  elements.loadingTitle.textContent = demo
    ? "Opening the instant practice lab…"
    : state.mode === "advanced"
    ? "Generating an advanced interview set…"
    : "Generating three realistic questions…";
  elements.loadingMessage.textContent = messages[0];
  loadingTimer = window.setInterval(() => {
    const elapsed = state.generationStartedAt
      ? Math.floor((Date.now() - state.generationStartedAt) / 1000)
      : 0;
    elements.loadingElapsed.textContent = `${elapsed}s elapsed`;
    if (state.mode !== "advanced") {
      index = (index + 1) % messages.length;
      elements.loadingMessage.textContent = messages[index];
    }
  }, 1000);
}

function hideLoading() {
  elements.loadingOverlay.hidden = true;
  window.clearInterval(loadingTimer);
}

function enterLab(response) {
  state.mode = response.mode || "standard";
  if (response.role_track) state.roleTrack = response.role_track;
  elements.modeChoices.querySelectorAll("button").forEach((choice) => {
    choice.classList.toggle("selected", choice.dataset.mode === state.mode);
  });
  elements.roleTrackField.hidden = state.mode !== "advanced";
  syncRoleTrackChoices();
  state.questionSet = response;
  state.historyId = response.history_id;
  state.questions = response.questions.map((question) => ({
    ...question,
    sql: question.latest_sql || "",
    passed: question.passed ?? null,
    detailsExpanded: false,
    clarifications: question.clarifications || [],
  }));
  state.activeQuestionIndex = 0;
  elements.setupView.hidden = true;
  elements.labView.hidden = false;
  elements.labCompany.textContent = response.company;
  renderModelStatus(response.generation_telemetry);
  elements.engineStatus.classList.toggle("emulated", response.execution_mode === "emulated");
  elements.engineStatusLabel.textContent = response.execution_label;
  elements.dialectBadge.textContent = response.dialect_name;
  elements.dialectBadge.classList.toggle("native", response.execution_mode === "native");
  elements.dialectBadge.classList.toggle("emulated", response.execution_mode === "emulated");
  elements.editorDialect.textContent = response.dialect_name;
  elements.businessContext.textContent = response.business_context;
  elements.businessContext.title = response.business_context;
  renderTablePreviews(response.tables);
  activateQuestion(0);
}

function renderModelStatus(telemetry = null) {
  if (!telemetry?.model && !telemetry?.resolved_model) {
    elements.modelStatus.hidden = true;
    elements.modelStatus.textContent = "";
    return;
  }
  const model = telemetry.resolved_model || telemetry.model;
  const effort = telemetry.resolved_reasoning_effort || telemetry.reasoning_effort;
  const sources = {
    interview_override: "interview override",
    cli_reported: "reported by Codex CLI",
    command_override: "configured command",
  };
  const source = sources[telemetry.configuration_source] || "CLI settings";
  elements.modelStatus.textContent = [model, effort, source].filter(Boolean).join(" · ");
  elements.modelStatus.title = elements.modelStatus.textContent;
  elements.modelStatus.hidden = false;
}

function activateQuestion(index) {
  closeSolutionModal();
  if (state.exercise && state.questions[state.activeQuestionIndex]) {
    state.questions[state.activeQuestionIndex].sql = elements.sqlEditor.value;
  }
  state.activeQuestionIndex = index;
  const question = state.questions[index];
  state.sessionId = question.session_id;
  state.exercise = {
    ...question,
    company: state.questionSet.company,
    business_context: state.questionSet.business_context,
    tables: state.questionSet.tables,
  };
  const exercise = state.exercise;
  elements.difficultyBadge.textContent = exercise.difficulty;
  elements.companyBadge.textContent = exercise.company;
  elements.challengePosition.textContent = `QUESTION ${index + 1} OF ${state.questions.length}`;
  elements.challengeTitle.textContent = exercise.task_summary;
  const advanced = state.questionSet.mode === "advanced";
  elements.questionTypeBadge.hidden = !advanced;
  elements.questionTypeBadge.textContent = formatQuestionType(exercise.question_type);
  renderRequirements(
    exercise.requirements,
    question.detailsExpanded,
    question.clarifications || [],
  );
  elements.requirementsToggleButton.textContent = advanced && !question.details_revealed
    ? "Ask interviewer"
    : question.detailsExpanded ? "Show Less" : "See More";
  elements.hintArea.replaceChildren();
  const remainingHints = Math.max(0, exercise.hint_count - (exercise.hints_revealed || 0));
  elements.hintButton.disabled = remainingHints === 0;
  elements.hintButton.textContent = remainingHints
    ? `Reveal a hint (${remainingHints})`
    : "No hints available";
  elements.solutionButton.textContent = exercise.solution_revealed
    ? "View solution again"
    : "View solution";
  updateGenerationControls();

  const firstTable = state.questionSet.tables[0]?.name || "table_name";
  state.starterSql = exercise.starter_sql ||
    `-- Write your ${state.questionSet.dialect_name} query here\nSELECT\n  *\nFROM ${firstTable}\nLIMIT 10;`;
  elements.sqlEditor.value = question.sql || state.starterSql;
  updateEditorLines();
  resetResults();
  renderQuestionNavigator();
  activatePaneTab("question");
  elements.sqlEditor.focus();
}

function updateGenerationControls() {
  const incomplete = state.questionSet?.generation_status === "running";
  elements.submitButton.disabled = incomplete;
  elements.doctorButton.disabled = incomplete;
  elements.solutionButton.disabled = incomplete;
  const remainingHints = Math.max(
    0,
    (state.exercise?.hint_count || 0) - (state.exercise?.hints_revealed || 0),
  );
  elements.hintButton.disabled = incomplete || remainingHints === 0;
  const reason = incomplete
    ? "Available after all three questions finish and the saved session is attached."
    : "";
  for (const button of [
    elements.submitButton,
    elements.doctorButton,
    elements.solutionButton,
    elements.hintButton,
  ]) {
    button.title = reason;
  }
}

async function toggleRequirements() {
  const question = state.questions[state.activeQuestionIndex];
  if (state.questionSet.mode === "advanced" && !question.details_revealed) {
    try {
      const details = await fetchJson(
        `/api/sessions/${question.session_id}/interviewer-details`,
        { method: "POST" },
      );
      question.requirements = details.requirements;
      question.clarifications = details.clarifications;
      question.details_revealed = true;
      question.detailsExpanded = true;
      renderRequirements(question.requirements, true, question.clarifications);
    } catch (error) {
      showToast(error.message, true);
    }
    return;
  }
  question.detailsExpanded = !question.detailsExpanded;
  updateRequirementsDisclosure(question.detailsExpanded);
}

function renderRequirements(requirements, expanded, clarifications = []) {
  elements.requirementsList.replaceChildren();
  requirements.forEach((requirement) => {
    const item = document.createElement("li");
    item.textContent = requirement;
    elements.requirementsList.append(item);
  });
  elements.clarificationsList.replaceChildren();
  elements.clarificationsSection.hidden = clarifications.length === 0;
  clarifications.forEach((clarification) => {
    const item = document.createElement("div");
    item.className = "clarification-item";
    const question = document.createElement("strong");
    question.textContent = clarification.candidate_question;
    const answer = document.createElement("p");
    answer.textContent = clarification.interviewer_answer;
    item.append(question, answer);
    elements.clarificationsList.append(item);
  });
  updateRequirementsDisclosure(expanded);
}

function updateRequirementsDisclosure(expanded) {
  elements.requirementsPanel.hidden = !expanded;
  elements.requirementsToggleButton.textContent = expanded ? "Show Less" : "See More";
  elements.requirementsToggleButton.setAttribute("aria-expanded", String(expanded));
}

function formatQuestionType(value) {
  return {
    sql_build: "SQL build",
    sql_debug: "SQL debugging",
    analytical_case: "Analytical case",
  }[value] || value;
}

function renderQuestionNavigator() {
  elements.questionNavigator.replaceChildren();
  state.questions.forEach((question, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "question-nav-button";
    button.classList.toggle("active", index === state.activeQuestionIndex);
    if (question.passed === true) button.classList.add("passed");
    if (question.passed === false) button.classList.add("failed");
    button.textContent = `Question ${index + 1}`;
    button.setAttribute("aria-pressed", String(index === state.activeQuestionIndex));
    button.addEventListener("click", () => activateQuestion(index));
    elements.questionNavigator.append(button);
  });
}

function renderTablePreviews(tables) {
  elements.tablePreviews.replaceChildren();
  for (const table of tables) {
    const card = document.createElement("article");
    card.className = "preview-card";

    const header = document.createElement("div");
    header.className = "preview-header";
    const copy = document.createElement("div");
    const name = document.createElement("h3");
    name.textContent = table.name;
    const description = document.createElement("p");
    description.textContent = table.description;
    copy.append(name, description);
    header.append(copy);

    const details = document.createElement("details");
    details.className = "ddl-details";
    const summary = document.createElement("summary");
    summary.textContent = "View DDL";
    const ddl = document.createElement("pre");
    ddl.textContent = table.ddl;
    details.append(summary, ddl);

    const label = document.createElement("div");
    label.className = "preview-label";
    label.textContent = `Example rows · first ${table.preview.rows.length}`;
    const tableWrap = buildDataTable(table.preview.columns, table.preview.rows);
    card.append(header, details, label, tableWrap);
    elements.tablePreviews.append(card);
  }
}

function buildDataTable(columns, rows) {
  const wrap = document.createElement("div");
  wrap.className = "data-table-wrap";
  const table = document.createElement("table");
  table.className = "data-table";
  const thead = document.createElement("thead");
  const headingRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headingRow.append(th);
  });
  thead.append(headingRow);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((value) => {
      const td = document.createElement("td");
      if (value === null) {
        td.textContent = "NULL";
        td.className = "null-value";
      } else {
        td.textContent = String(value);
        td.title = String(value);
      }
      tr.append(td);
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(table);
  return wrap;
}

function activatePaneTab(name) {
  document.querySelectorAll("[data-pane-tab]").forEach((button) => {
    const active = button.dataset.paneTab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.questionPanel.hidden = name !== "question";
  elements.schemaPanel.hidden = name !== "schema";
}

function activateResultTab(name) {
  document.querySelectorAll("[data-result-tab]").forEach((button) => {
    const active = button.dataset.resultTab === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  elements.outputResult.hidden = name !== "output";
  elements.testResult.hidden = name !== "tests";
  elements.doctorPanel.hidden = name !== "doctor";
}

function updateEditorLines() {
  const lineCount = Math.max(1, elements.sqlEditor.value.split("\n").length);
  elements.editorLines.textContent = Array.from({ length: lineCount }, (_, index) => index + 1).join("\n");
}

function handleEditorKeys(event) {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    if (event.shiftKey) submitQuery();
    else runQuery();
    return;
  }
  if (event.key === "Tab") {
    event.preventDefault();
    const start = elements.sqlEditor.selectionStart;
    const end = elements.sqlEditor.selectionEnd;
    elements.sqlEditor.value =
      elements.sqlEditor.value.slice(0, start) + "  " + elements.sqlEditor.value.slice(end);
    elements.sqlEditor.selectionStart = elements.sqlEditor.selectionEnd = start + 2;
    updateEditorLines();
  }
}

async function runQuery() {
  const sql = elements.sqlEditor.value.trim();
  if (!sql) return showToast("Write a SQL query first.", true);
  setButtonBusy(elements.runButton, true, "Running…");
  activateResultTab("output");
  try {
    const result = await fetchJson(`/api/sessions/${state.sessionId}/run`, {
      method: "POST",
      body: JSON.stringify({ sql }),
    });
    state.lastOutput = result;
    renderQueryResult(result);
  } catch (error) {
    renderError(elements.outputResult, error.message);
  } finally {
    setButtonBusy(elements.runButton, false, "Run query", "▶");
  }
}

function renderQueryResult(result) {
  elements.outputResult.replaceChildren();
  if (!result.ok) {
    renderError(elements.outputResult, result.error);
    elements.executionMeta.textContent = "Query failed";
    return;
  }
  if (!result.columns.length) {
    const message = document.createElement("div");
    message.className = "result-summary pass";
    message.textContent = "Statement completed successfully.";
    elements.outputResult.append(message);
  } else {
    elements.outputResult.append(buildDataTable(result.columns, result.rows));
  }
  elements.executionMeta.textContent = `${result.row_count} rows · ${result.duration_ms} ms`;
}

async function submitQuery() {
  const sql = elements.sqlEditor.value.trim();
  if (!sql) return showToast("Write a SQL query first.", true);
  setButtonBusy(elements.submitButton, true, "Grading…");
  activateResultTab("tests");
  try {
    const grade = await fetchJson(`/api/sessions/${state.sessionId}/submit`, {
      method: "POST",
      body: JSON.stringify({ sql }),
    });
    state.lastGrade = grade;
    renderGrade(grade);
  } catch (error) {
    renderError(elements.testResult, error.message);
  } finally {
    setButtonBusy(elements.submitButton, false, "Submit answer");
  }
}

function renderGrade(grade) {
  state.questions[state.activeQuestionIndex].passed = grade.passed;
  state.questions[state.activeQuestionIndex].sql = elements.sqlEditor.value;
  renderQuestionNavigator();
  elements.testResult.replaceChildren();
  elements.testStatusDot.className = grade.passed ? "pass" : "fail";
  const summary = document.createElement("div");
  summary.className = `result-summary ${grade.passed ? "pass" : "fail"}`;
  const icon = document.createElement("span");
  icon.className = "result-summary-icon";
  icon.textContent = grade.passed ? "✓" : "!";
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = grade.passed ? "All tests passed" : "Your result does not match yet";
  const description = document.createElement("p");
  description.textContent = grade.passed
    ? `Matched ${grade.datasets.length} deterministic grading datasets.`
    : "Review the failing dataset details below and try again.";
  copy.append(title, description);
  summary.append(icon, copy);

  const list = document.createElement("div");
  list.className = "test-list";
  grade.datasets.forEach((dataset) => {
    const card = document.createElement("div");
    card.className = "test-card";
    const header = document.createElement("div");
    header.className = "test-card-header";
    const label = document.createElement("span");
    label.textContent = dataset.label;
    const status = document.createElement("span");
    status.className = dataset.passed ? "pass" : "fail";
    status.textContent = dataset.passed ? "PASSED" : "FAILED";
    header.append(label, status);
    card.append(header);

    if (!dataset.passed) {
      const detail = document.createElement("div");
      detail.className = "test-detail";
      if (dataset.error) {
        detail.textContent = dataset.error;
      } else if (dataset.comparison) {
        const comparison = dataset.comparison;
        const lines = [];
        if (!comparison.columns_match) {
          lines.push(`Expected columns: ${comparison.expected_columns.join(", ")}`);
          lines.push(`Actual columns: ${comparison.actual_columns.join(", ")}`);
        }
        if (comparison.expected_row_count !== comparison.actual_row_count) {
          lines.push(`Expected ${comparison.expected_row_count} rows; received ${comparison.actual_row_count}.`);
        }
        if (comparison.differing_rows) lines.push(`${comparison.differing_rows} row(s) differ.`);
        const example = comparison.examples[0];
        if (example) {
          lines.push(`Expected example: ${formatRow(example.expected)}`);
          lines.push(`Actual example: ${formatRow(example.actual)}`);
        }
        detail.textContent = lines.join("\n");
      }
      card.append(detail);
    }
    list.append(card);
  });
  elements.testResult.append(summary, list);
}

async function reviewQuery() {
  const sql = elements.sqlEditor.value.trim();
  if (!sql) return showToast("Write a SQL query first.", true);
  setButtonBusy(elements.doctorButton, true, "Reviewing…");
  activateResultTab("doctor");
  elements.doctorResult.innerHTML = `
    <div class="empty-result doctor-loading">
      <span class="empty-result-icon">⌁</span>
      <strong>Running deterministic checks…</strong>
      <p>The CLI provider will review the evidence after execution and grading finish.</p>
    </div>`;
  try {
    const diagnosis = await fetchJson(`/api/sessions/${state.sessionId}/doctor`, {
      method: "POST",
      body: JSON.stringify({ sql }),
    });
    state.lastDoctor = diagnosis;
    renderDoctor(diagnosis);
  } catch (error) {
    renderError(elements.doctorResult, error.message);
    elements.doctorStatusDot.className = "fail";
  } finally {
    setButtonBusy(elements.doctorButton, false, "Review current query");
  }
}

function renderDoctor(diagnosis) {
  elements.doctorResult.replaceChildren();
  const passed = diagnosis.grade.passed;
  elements.doctorStatusDot.className = passed ? "pass" : "fail";

  const summary = document.createElement("div");
  summary.className = `result-summary ${passed ? "pass" : "fail"}`;
  const icon = document.createElement("span");
  icon.className = "result-summary-icon";
  icon.textContent = passed ? "✓" : "!";
  const copy = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = passed
    ? "Deterministic check passed"
    : diagnosis.execution.ok
      ? "Deterministic check found mismatches"
      : "The query could not execute";
  const detail = document.createElement("p");
  detail.textContent = diagnosis.execution.ok
    ? `${diagnosis.execution.row_count} visible row(s) · reviewed with ${providerLabel(diagnosis.provider)} CLI`
    : diagnosis.execution.error;
  copy.append(title, detail);
  summary.append(icon, copy);
  elements.doctorResult.append(summary);

  const feedback = diagnosis.feedback;
  const overview = document.createElement("div");
  overview.className = "doctor-overview";
  const overviewTitle = document.createElement("strong");
  overviewTitle.textContent = "Diagnosis";
  const overviewText = document.createElement("p");
  overviewText.textContent = feedback.summary;
  overview.append(overviewTitle, overviewText);
  if (feedback.categories.length) {
    const categories = document.createElement("div");
    categories.className = "doctor-categories";
    feedback.categories.forEach((category) => {
      const chip = document.createElement("span");
      chip.textContent = category;
      categories.append(chip);
    });
    overview.append(categories);
  }
  elements.doctorResult.append(overview);

  const sections = [
    ["What works", feedback.strengths],
    ["Issues to inspect", feedback.issues],
    ["Next steps", feedback.next_steps],
  ];
  const sectionGrid = document.createElement("div");
  sectionGrid.className = "doctor-sections";
  sections.forEach(([heading, items]) => {
    if (!items.length) return;
    const section = document.createElement("section");
    const sectionTitle = document.createElement("h3");
    sectionTitle.textContent = heading;
    const list = document.createElement("ul");
    items.forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item;
      list.append(row);
    });
    section.append(sectionTitle, list);
    sectionGrid.append(section);
  });
  elements.doctorResult.append(sectionGrid);
}

function providerLabel(provider) {
  if (provider === "codex") return "Codex";
  if (provider === "claude") return "Claude";
  return provider;
}

function formatRow(row) {
  return row === null ? "<missing row>" : JSON.stringify(row);
}

function renderError(container, message) {
  container.replaceChildren();
  const error = document.createElement("div");
  error.className = "error-block";
  error.textContent = message;
  container.append(error);
}

async function revealHint() {
  try {
    const response = await fetchJson(`/api/sessions/${state.sessionId}/hint`, { method: "POST" });
    const callout = document.createElement("div");
    callout.className = "hint-callout";
    const label = document.createElement("strong");
    label.textContent = `Hint ${elements.hintArea.children.length + 1}: `;
    callout.append(label, document.createTextNode(response.hint));
    elements.hintArea.append(callout);
    state.questions[state.activeQuestionIndex].hints_revealed += 1;
    elements.hintButton.textContent = response.remaining
      ? `Reveal another hint (${response.remaining})`
      : "No more hints";
    elements.hintButton.disabled = response.remaining === 0;
  } catch (error) {
    showToast(error.message, true);
    elements.hintButton.disabled = true;
  }
}

function openSolutionModal() {
  const question = state.questions[state.activeQuestionIndex];
  elements.solutionModal.hidden = false;
  if (question.solution) {
    renderSolution(question.solution);
    elements.closeSolutionButton.focus();
    return;
  }
  if (question.solution_revealed) {
    renderSolutionLoading();
    void revealSolution();
    return;
  }
  renderSolutionConfirmation();
}

function closeSolutionModal() {
  elements.solutionModal.hidden = true;
}

function renderSolutionConfirmation() {
  elements.solutionModalBody.replaceChildren();
  const icon = document.createElement("div");
  icon.className = "modal-icon";
  icon.textContent = "⌁";
  const title = document.createElement("h2");
  title.id = "solutionHeading";
  title.textContent = "Reveal the reference solution?";
  const description = document.createElement("p");
  description.textContent =
    "This will show the validated reference SQL. Try submitting your own answer first if you want the full interview experience.";
  const actions = document.createElement("div");
  actions.className = "modal-actions";
  const cancelButton = document.createElement("button");
  cancelButton.className = "button secondary";
  cancelButton.type = "button";
  cancelButton.textContent = "Keep working";
  cancelButton.addEventListener("click", closeSolutionModal);
  const confirmButton = document.createElement("button");
  confirmButton.className = "button danger-fill";
  confirmButton.type = "button";
  confirmButton.textContent = "Reveal solution";
  confirmButton.addEventListener("click", () => revealSolution(confirmButton));
  actions.append(cancelButton, confirmButton);
  elements.solutionModalBody.append(icon, title, description, actions);
  confirmButton.focus();
}

function renderSolutionLoading() {
  elements.solutionModalBody.replaceChildren();
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "REFERENCE SOLUTION";
  const title = document.createElement("h2");
  title.id = "solutionHeading";
  title.textContent = "Loading validated approach…";
  elements.solutionModalBody.append(eyebrow, title);
}

function renderSolution(solution) {
  elements.solutionModalBody.replaceChildren();
  const eyebrow = document.createElement("div");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = "REFERENCE SOLUTION";
  const title = document.createElement("h2");
  title.id = "solutionHeading";
  title.textContent = "One validated approach";
  const codeWrap = document.createElement("div");
  codeWrap.className = "solution-code-wrap";
  const code = document.createElement("pre");
  code.className = "solution-code";
  code.textContent = solution.reference_sql;
  codeWrap.append(code);
  const explanation = document.createElement("p");
  explanation.textContent = solution.explanation;
  elements.solutionModalBody.append(eyebrow, title, codeWrap, explanation);
  if (solution.case_rubric?.length) {
    const rubricTitle = document.createElement("h3");
    rubricTitle.textContent = "Self-review rubric";
    const rubricNote = document.createElement("p");
    rubricNote.textContent =
      "Use this to review your reasoning. It does not change the deterministic SQL result.";
    const rubricList = document.createElement("div");
    rubricList.className = "case-rubric";
    solution.case_rubric.forEach((criterion) => {
      const item = document.createElement("article");
      const heading = document.createElement("strong");
      heading.textContent = criterion.criterion;
      const signal = document.createElement("p");
      signal.textContent = `Strong signal: ${criterion.strong_signal}`;
      const miss = document.createElement("p");
      miss.textContent = `Common miss: ${criterion.common_miss}`;
      item.append(heading, signal, miss);
      rubricList.append(item);
    });
    elements.solutionModalBody.append(rubricTitle, rubricNote, rubricList);
  }
  if (solution.reference_discussion?.length) {
    const discussionTitle = document.createElement("h3");
    discussionTitle.textContent = "Strong discussion points";
    const discussion = document.createElement("ul");
    solution.reference_discussion.forEach((point) => {
      const item = document.createElement("li");
      item.textContent = point;
      discussion.append(item);
    });
    elements.solutionModalBody.append(discussionTitle, discussion);
  }
}

async function revealSolution(confirmButton = null) {
  const questionIndex = state.activeQuestionIndex;
  const question = state.questions[questionIndex];
  if (confirmButton) setButtonBusy(confirmButton, true, "Loading…");
  try {
    const solution = await fetchJson(`/api/sessions/${question.session_id}/solution`, {
      method: "POST",
    });
    question.solution_revealed = true;
    question.solution = solution;
    if (state.activeQuestionIndex === questionIndex) {
      elements.solutionButton.textContent = "View solution again";
      renderSolution(solution);
    }
  } catch (error) {
    showToast(error.message, true);
    if (state.activeQuestionIndex === questionIndex) renderSolutionConfirmation();
  } finally {
    if (confirmButton?.isConnected) {
      setButtonBusy(confirmButton, false, "Reveal solution");
    }
  }
}

async function resetEditor() {
  elements.sqlEditor.value = state.starterSql;
  updateEditorLines();
  try {
    await fetchJson(`/api/sessions/${state.sessionId}/reset`, { method: "POST" });
    showToast("Editor and visible database reset.");
  } catch (error) {
    showToast(error.message, true);
  }
}

function resetResults() {
  state.lastOutput = null;
  state.lastGrade = null;
  state.lastDoctor = null;
  elements.executionMeta.textContent = "";
  elements.testStatusDot.className = "";
  elements.doctorStatusDot.className = "";
  elements.outputResult.innerHTML = `
    <div class="empty-result">
      <span class="empty-result-icon">▦</span>
      <strong>Run your query to see results</strong>
      <p>${state.questionSet?.execution_label || "DuckDB native execution"}.</p>
    </div>`;
  elements.testResult.innerHTML = `
    <div class="empty-result">
      <span class="empty-result-icon">✓</span>
      <strong>Submit when you are ready</strong>
      <p>Your answer will be checked against visible and hidden datasets.</p>
    </div>`;
  elements.doctorResult.innerHTML = `
    <div class="empty-result">
      <span class="empty-result-icon">⌁</span>
      <strong>Get a second set of eyes</strong>
      <p>Your SQL will be executed and graded before the CLI review begins.</p>
    </div>`;
  activateResultTab("output");
}

function startNewQuestion() {
  if (elements.sqlEditor.value !== state.starterSql && !window.confirm("Leave this attempt and start a new question?")) {
    return;
  }
  state.sessionId = null;
  state.exercise = null;
  state.questionSet = null;
  state.questions = [];
  state.activeQuestionIndex = 0;
  state.historyId = null;
  state.generationPending = false;
  state.generationId = null;
  generationPollCancelled = true;
  elements.generationProgress.hidden = true;
  elements.labView.hidden = true;
  elements.setupView.hidden = false;
  elements.configStep.hidden = true;
  elements.companyStep.hidden = false;
  window.scrollTo({ top: 0 });
}

async function openHistory() {
  elements.historyModal.hidden = false;
  elements.historyList.innerHTML = '<div class="history-empty">Loading saved sessions…</div>';
  try {
    const history = await fetchJson("/api/history");
    renderHistory(history);
  } catch (error) {
    renderError(elements.historyList, error.message);
  }
}

function closeHistory() {
  elements.historyModal.hidden = true;
}

function renderHistory(history) {
  elements.historyList.replaceChildren();
  elements.historyStorage.textContent = `${history.sessions.length} saved session${history.sessions.length === 1 ? "" : "s"} · ${formatBytes(history.storage_bytes)} on disk`;
  elements.clearHistoryButton.disabled = history.sessions.length === 0 ||
    Boolean(state.historyId) || state.generationPending;
  elements.clearHistoryButton.title = state.generationPending
    ? "Wait for question generation to finish."
    : state.historyId
      ? "Start a new session before clearing all history."
      : "Delete every saved session, generation log, and cached dataset.";

  if (!history.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    const title = document.createElement("strong");
    title.textContent = "No previous sessions yet";
    const detail = document.createElement("span");
    detail.textContent = "Your next generated question set will be saved locally.";
    empty.append(title, detail);
    elements.historyList.append(empty);
    return;
  }

  history.sessions.forEach((session) => {
    const card = document.createElement("article");
    card.className = "history-card";
    const isActive = session.id === state.historyId;
    card.classList.toggle("active", isActive);

    const main = document.createElement("div");
    main.className = "history-card-main";
    const titleRow = document.createElement("div");
    titleRow.className = "history-card-title";
    const title = document.createElement("strong");
    title.textContent = session.company;
    const time = document.createElement("time");
    time.dateTime = session.last_activity_at;
    time.textContent = formatHistoryDate(session.last_activity_at);
    titleRow.append(title, time);

    const meta = document.createElement("div");
    meta.className = "history-card-meta";
    const dialect = document.createElement("span");
    dialect.textContent = session.dialect_name;
    const difficulty = document.createElement("span");
    difficulty.textContent = `${capitalize(session.difficulty)} difficulty`;
    const attempts = document.createElement("span");
    attempts.textContent = `${session.submission_count} submission${session.submission_count === 1 ? "" : "s"}`;
    const progress = document.createElement("span");
    progress.className = `history-progress${session.completed_at ? "" : " in-progress"}`;
    progress.textContent = session.completed_at
      ? `✓ ${session.question_count} of ${session.question_count} passed`
      : `${session.questions_passed} of ${session.question_count} passed`;
    meta.append(dialect, difficulty, attempts, progress);
    main.append(titleRow, meta);

    const actions = document.createElement("div");
    actions.className = "history-card-actions";
    const resume = document.createElement("button");
    resume.type = "button";
    resume.className = "button secondary small";
    resume.textContent = isActive ? "Current" : "Resume";
    resume.disabled = isActive;
    resume.addEventListener("click", () => resumeHistory(session.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "history-delete";
    remove.textContent = "×";
    remove.title = isActive ? "The active session cannot be deleted." : "Delete session";
    remove.disabled = isActive;
    remove.addEventListener("click", () => deleteHistory(session));
    actions.append(resume, remove);
    card.append(main, actions);
    elements.historyList.append(card);
  });
}

async function resumeHistory(historyId) {
  try {
    const response = await fetchJson(`/api/history/${historyId}/resume`, { method: "POST" });
    closeHistory();
    enterLab(response);
    showToast("Previous session resumed.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function deleteHistory(session) {
  if (!window.confirm(`Delete the saved ${session.company} session? This cannot be undone.`)) return;
  try {
    await fetchJson(`/api/history/${session.id}`, { method: "DELETE" });
    await openHistory();
    showToast("Saved session deleted.");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function clearHistory() {
  if (state.historyId) return;
  if (!window.confirm("Delete all saved SQL Lab sessions? This cannot be undone.")) return;
  try {
    const result = await fetchJson("/api/history", { method: "DELETE" });
    await openHistory();
    showToast(`${result.deleted_count} saved session${result.deleted_count === 1 ? "" : "s"} deleted.`);
  } catch (error) {
    showToast(error.message, true);
  }
}

function formatHistoryDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function capitalize(value) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : "";
}

function setButtonBusy(button, busy, label, prefix = "") {
  if (!button) return;
  button.disabled = busy;
  button.textContent = prefix ? `${prefix} ${label}` : label;
}

function showToast(message, error = false, duration = 4200) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(
    () => elements.toast.classList.remove("visible"),
    duration,
  );
}
