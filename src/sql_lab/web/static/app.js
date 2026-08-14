"use strict";

const state = {
  options: null,
  selectedCompany: null,
  dialect: "duckdb",
  difficulty: "medium",
  historyId: null,
  questionSet: null,
  questions: [],
  activeQuestionIndex: 0,
  sessionId: null,
  exercise: null,
  starterSql: "",
  lastOutput: null,
  lastGrade: null,
};

const elements = {};
let toastTimer = null;
let loadingTimer = null;

document.addEventListener("DOMContentLoaded", async () => {
  collectElements();
  bindEvents();
  try {
    state.options = await fetchJson("/api/options");
    renderCompanyCards();
    renderDialects();
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
    "saveHistoryInput",
    "providerSelect",
    "difficultyChoices", "demoButton", "generateButton", "labView", "labCompany",
    "difficultyBadge", "questionNavigator", "engineStatus", "engineStatusLabel",
    "dialectBadge", "editorDialect",
    "companyBadge", "challengeTitle", "businessContext", "questionText",
    "hintArea", "hintButton", "solutionButton", "tablePreviews",
    "sqlEditor", "editorLines", "resetButton", "runButton", "submitButton",
    "outputResult", "testResult", "executionMeta", "testStatusDot",
    "newQuestionButton", "loadingOverlay", "loadingTitle", "loadingMessage",
    "solutionModal", "solutionModalBody", "closeSolutionButton", "cancelSolutionButton",
    "confirmSolutionButton", "toast", "questionPanel", "schemaPanel",
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
  elements.difficultyChoices.addEventListener("click", handleDifficulty);
  elements.generateButton.addEventListener("click", () => generateExercise(false));
  elements.demoButton.addEventListener("click", () => generateExercise(true));
  elements.runButton.addEventListener("click", runQuery);
  elements.submitButton.addEventListener("click", submitQuery);
  elements.resetButton.addEventListener("click", resetEditor);
  elements.hintButton.addEventListener("click", revealHint);
  elements.solutionButton.addEventListener("click", openSolutionModal);
  elements.closeSolutionButton.addEventListener("click", closeSolutionModal);
  elements.cancelSolutionButton.addEventListener("click", closeSolutionModal);
  elements.confirmSolutionButton.addEventListener("click", revealSolution);
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
    const logo = document.createElement("span");
    logo.className = "company-logo";
    logo.textContent = company.monogram;
    const title = document.createElement("h2");
    title.textContent = company.name;
    const description = document.createElement("p");
    description.textContent = company.description;
    card.append(check, logo, title, description);
    card.addEventListener("click", () => selectCompany(company, card));
    elements.companyGrid.append(card);
  }
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
    state.selectedCompany?.demo_available && state.dialect === "duckdb"
  );
}

function showConfigStep() {
  const companyName = resolvedCompanyName();
  if (!companyName) return;
  elements.companyStep.hidden = true;
  elements.configStep.hidden = false;
  elements.selectedCompanySummary.replaceChildren();
  elements.selectedCompanySummary.dataset.accent = state.selectedCompany.accent;
  const logo = document.createElement("span");
  logo.className = "company-logo";
  logo.textContent = state.selectedCompany.custom
    ? companyName.charAt(0).toUpperCase()
    : state.selectedCompany.monogram;
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

async function generateExercise(demo) {
  const companyName = resolvedCompanyName();
  if (!companyName) {
    showCompanyStep();
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
  };
  showLoading(demo);
  try {
    const response = await fetchJson("/api/exercises", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    enterLab(response);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    hideLoading();
  }
}

function showLoading(demo) {
  elements.loadingOverlay.hidden = false;
  const messages = demo
    ? ["Loading the validated sample exercise…", "Seeding the visible DuckDB tables…"]
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
    : "Generating three realistic questions…";
  elements.loadingMessage.textContent = messages[0];
  loadingTimer = window.setInterval(() => {
    index = (index + 1) % messages.length;
    elements.loadingMessage.textContent = messages[index];
  }, 4200);
}

function hideLoading() {
  elements.loadingOverlay.hidden = true;
  window.clearInterval(loadingTimer);
}

function enterLab(response) {
  state.questionSet = response;
  state.historyId = response.history_id;
  state.questions = response.questions.map((question) => ({
    ...question,
    sql: question.latest_sql || "",
    passed: question.passed ?? null,
  }));
  state.activeQuestionIndex = 0;
  elements.setupView.hidden = true;
  elements.labView.hidden = false;
  elements.labCompany.textContent = response.company;
  elements.engineStatus.classList.toggle("emulated", response.execution_mode === "emulated");
  elements.engineStatusLabel.textContent = response.execution_label;
  elements.dialectBadge.textContent = response.dialect_name;
  elements.dialectBadge.classList.toggle("native", response.execution_mode === "native");
  elements.dialectBadge.classList.toggle("emulated", response.execution_mode === "emulated");
  elements.editorDialect.textContent = response.dialect_name;
  elements.businessContext.textContent = response.business_context;
  renderTablePreviews(response.tables);
  activateQuestion(0);
}

function activateQuestion(index) {
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
  elements.challengeTitle.textContent = `Question ${index + 1} of ${state.questions.length}`;
  elements.questionText.textContent = exercise.question;
  elements.hintArea.replaceChildren();
  const remainingHints = Math.max(0, exercise.hint_count - (exercise.hints_revealed || 0));
  elements.hintButton.disabled = remainingHints === 0;
  elements.hintButton.textContent = remainingHints
    ? `Reveal a hint (${remainingHints})`
    : "No hints available";
  elements.solutionButton.textContent = exercise.solution_revealed
    ? "View solution again"
    : "View solution";

  const firstTable = state.questionSet.tables[0]?.name || "table_name";
  state.starterSql = `-- Write your ${state.questionSet.dialect_name} query here\nSELECT\n  *\nFROM ${firstTable}\nLIMIT 10;`;
  elements.sqlEditor.value = question.sql || state.starterSql;
  updateEditorLines();
  resetResults();
  renderQuestionNavigator();
  activatePaneTab("question");
  elements.sqlEditor.focus();
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
    button.classList.toggle("active", button.dataset.resultTab === name);
  });
  elements.outputResult.hidden = name !== "output";
  elements.testResult.hidden = name !== "tests";
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
  elements.solutionModal.hidden = false;
  elements.confirmSolutionButton?.focus();
}

function closeSolutionModal() {
  elements.solutionModal.hidden = true;
}

async function revealSolution() {
  setButtonBusy(elements.confirmSolutionButton, true, "Loading…");
  try {
    const solution = await fetchJson(`/api/sessions/${state.sessionId}/solution`, { method: "POST" });
    state.questions[state.activeQuestionIndex].solution_revealed = true;
    elements.solutionButton.textContent = "View solution again";
    elements.solutionModalBody.replaceChildren();
    const eyebrow = document.createElement("div");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "REFERENCE SOLUTION";
    const title = document.createElement("h2");
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
  } catch (error) {
    showToast(error.message, true);
  } finally {
    setButtonBusy(elements.confirmSolutionButton, false, "Reveal solution");
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
  elements.executionMeta.textContent = "";
  elements.testStatusDot.className = "";
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
  elements.clearHistoryButton.disabled = history.sessions.length === 0 || Boolean(state.historyId);
  elements.clearHistoryButton.title = state.historyId
    ? "Start a new session before clearing all history."
    : "Delete every saved session.";

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

function showToast(message, error = false) {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("error", error);
  elements.toast.classList.add("visible");
  toastTimer = window.setTimeout(() => elements.toast.classList.remove("visible"), 4200);
}
