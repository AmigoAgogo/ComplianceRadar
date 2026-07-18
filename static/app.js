const state = {
  dashboard: null,
  busy: false,
  progressTimer: null,
  eventFilterFrom: "",
  eventFilterTo: "",
  apiBase: "",
  pendingSyncPeriod: "7d",
  lastAiOpinionId: "",
};

const categoryLabels = {
  "业务合规": "Business Compliance",
  "信息披露": "Information Disclosure",
  "监管处罚": "Regulatory Penalty",
  "监管动态": "Regulatory Update",
  "公司治理": "Corporate Governance",
  "关联交易": "Related-Party Governance",
  "风险管理": "Risk Management",
  "信用风险": "Credit Risk",
};

function localizeCategory(label) {
  return categoryLabels[label] || label;
}

function setStatusBanner(message = "", tone = "info") {
  const banner = document.getElementById("app-status-banner");
  if (!banner) {
    return;
  }
  banner.textContent = message;
  banner.className = message ? `status-banner ${tone}` : "status-banner hidden";
}

async function probeApiOrigin(origin) {
  const response = await fetch(`${origin}/api/health`, { method: "GET", mode: "cors" });
  if (!response.ok) {
    throw new Error(`Health probe failed: ${response.status}`);
  }
  const payload = await response.json();
  if (payload.status !== "ok") {
    throw new Error("Health probe returned unexpected payload.");
  }
  return origin;
}

async function detectApiBase() {
  if (state.apiBase) {
    return state.apiBase;
  }

  const host = window.location.hostname || "127.0.0.1";
  const candidateOrigins = [];
  if (window.location.origin) {
    candidateOrigins.push(window.location.origin);
  }
  for (let port = 8765; port <= 8785; port += 1) {
    const candidate = `http://${host}:${port}`;
    if (!candidateOrigins.includes(candidate)) {
      candidateOrigins.push(candidate);
    }
  }
  if (host !== "127.0.0.1") {
    for (let port = 8765; port <= 8785; port += 1) {
      const candidate = `http://127.0.0.1:${port}`;
      if (!candidateOrigins.includes(candidate)) {
        candidateOrigins.push(candidate);
      }
    }
  }

  for (const origin of candidateOrigins) {
    try {
      state.apiBase = await probeApiOrigin(origin);
      if (origin !== window.location.origin) {
        setStatusBanner(`Connected to local API at ${origin}.`, "success");
      }
      return state.apiBase;
    } catch {
      // Keep scanning candidate ports until a healthy local API responds.
    }
  }

  throw new Error("Unable to reach the local ComplianceRadar API.");
}

function setProgressState(value, label, visible = true) {
  const shell = document.getElementById("event-sync-progress");
  const bar = document.getElementById("event-sync-progress-bar");
  const text = document.getElementById("event-sync-progress-label");
  const number = document.getElementById("event-sync-progress-value");
  shell.classList.toggle("hidden", !visible);
  bar.style.width = `${value}%`;
  text.textContent = label;
  number.textContent = `${value}%`;
}

function clearProgressSimulation() {
  if (state.progressTimer) {
    clearInterval(state.progressTimer);
    state.progressTimer = null;
  }
}

function startProgressSimulation(scopeLabel) {
  clearProgressSimulation();
  const stages = [
    { value: 10, label: `${scopeLabel}: preparing sources...` },
    { value: 35, label: `${scopeLabel}: fetching regulator pages...` },
    { value: 70, label: `${scopeLabel}: parsing and reconciling records...` },
  ];
  let index = 0;
  setProgressState(stages[0].value, stages[0].label, true);
  state.progressTimer = setInterval(() => {
    index += 1;
    if (index >= stages.length) {
      clearProgressSimulation();
      return;
    }
    setProgressState(stages[index].value, stages[index].label, true);
  }, 900);
}

function setBusyState(isBusy, triggerLabel = "Working...") {
  state.busy = isBusy;
  document.querySelectorAll("button").forEach((button) => {
    if (!button.dataset.originalLabel) {
      button.dataset.originalLabel = button.textContent;
    }
    if (button.dataset.busyAction === "sync" || button.dataset.busyAction === "update") {
      button.disabled = isBusy;
      button.classList.toggle("is-busy", isBusy);
      button.textContent = isBusy ? triggerLabel : button.dataset.originalLabel;
    }
  });
}

function describeSyncResult(payload, scopeLabel) {
  const errorCount = payload.errors.length;
  const sourceResults = payload.source_results || [];
  const okSources = sourceResults.filter((item) => item.status === "ok");
  const sourceSummary = sourceResults.length
    ? ` Checked ${sourceResults.length} source(s): ${okSources.length} succeeded, ${errorCount} failed.`
    : "";
  const suffix = errorCount
    ? ` Failed sources: ${payload.errors.map((item) => `${item.source_id}`).join(", ")}. First issue: ${payload.errors[0].source_id} - ${payload.errors[0].error}.`
    : "";
  const llmPart = payload.llm_enriched_count
    ? ` LLM enriched ${payload.llm_enriched_count} event(s) with ${payload.llm_model}.`
    : " No LLM enrichment ran in this update.";
  return `${scopeLabel} updated ${payload.processed_sources.length} source(s), added ${payload.synced_count} live article event(s), errors ${errorCount}.${sourceSummary}${suffix}${llmPart}`;
}

function logActivity(message) {
  const stamp = new Date().toLocaleTimeString();
  const consoleNode = document.getElementById("activity-log");
  consoleNode.textContent = `[${stamp}] ${message}\n${consoleNode.textContent}`;
}

async function fetchJson(url, options = {}) {
  const base = await detectApiBase();
  const targetUrl = url.startsWith("http") ? url : `${base}${url}`;
  const response = await fetch(targetUrl, {
    headers: { "Content-Type": "application/json" },
    mode: "cors",
    ...options,
  });
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload.error) {
        detail = payload.error;
      }
    } catch {
      // Ignore body parse failures and keep the status message.
    }
    throw new Error(detail);
  }
  return response.json();
}

function setActiveView(view) {
  document.querySelectorAll(".nav-link").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `view-${view}`);
  });
}

function renderCards(summary) {
  const cards = [
    ["Total Events", summary.total_events],
    ["Major Events", summary.major_events],
    ["Pending Items", summary.pending_reviews],
    ["Active Sources", summary.active_sources],
    ["Primary Theme", summary.top_category],
  ];

  document.getElementById("summary-cards").innerHTML = cards
    .map(
      ([label, value]) => `
      <div class="card">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </div>
    `
    )
    .join("");
}

function renderBars(containerId, rows) {
  if (!rows.length) {
    document.getElementById(containerId).innerHTML = `<div class="meta">No chart data available yet.</div>`;
    return;
  }
  const maxValue = Math.max(...rows.map((row) => row.value), 1);
  document.getElementById(containerId).innerHTML = rows
    .map(
      (row) => `
        <div class="bar-row">
          <div class="bar-label"><span>${row.label}</span><span>${row.value}</span></div>
          <div class="bar" style="width: ${(row.value / maxValue) * 100}%"></div>
        </div>
      `
    )
    .join("");
}

function renderManagementDashboard(payload) {
  const intelligence = payload.penalty_intelligence || [];
  const earlyWarning = payload.early_warning || {};
  const reasons = payload.top_penalty_reasons || [];
  document.getElementById("dashboard-trend-window").textContent =
    payload.trend_window_label || "Trend window unavailable.";

  document.getElementById("management-headline").textContent =
    payload.headline || "Management view is loading.";

  document.getElementById("penalty-intelligence").innerHTML = intelligence
    .map(
      (item) => `
        <div class="review-item">
          <div><strong>${item.label}</strong></div>
          <p>${item.value}</p>
        </div>
      `
    )
    .join("");

  renderBars(
    "reason-chart",
    reasons.map((item) => ({
      label: `${item.reason} (${item.share}%)`,
      value: item.count,
    }))
  );

  document.getElementById("early-warning-panel").innerHTML = `
    <div class="review-item">
      <div><strong>${earlyWarning.headline || "No early warning yet."}</strong></div>
      <p>${earlyWarning.summary || "No management warning available yet."}</p>
    </div>
    <div class="review-item">
      <div><strong>Control Domains</strong></div>
      ${(earlyWarning.control_domains || [])
        .map((item) => `<p><span class="badge approved">Domain</span>${item}</p>`)
        .join("") || `<p>No control domains mapped yet.</p>`}
    </div>
    ${(earlyWarning.supporting_events || [])
      .map(
        (item) => `
          <div class="review-item">
            <div><span class="badge major">Analyzed Signal</span><strong>${item.title}</strong></div>
            <div class="meta">${item.reason} | ${item.published_at ? item.published_at.slice(0, 10) : "No date"}</div>
            <p>${item.analysis_summary}</p>
            ${item.source_url ? `<a class="model-button" href="${item.source_url}" target="_blank" rel="noreferrer">Open Source</a>` : ""}
          </div>
        `
      )
      .join("")}
    <div class="review-item">
      <div><strong>Management Actions</strong></div>
      ${((earlyWarning.management_actions || earlyWarning.actions || []))
        .map(
          (item) => `
            <p>${item}</p>
          `
        )
        .join("") || "<p>No management actions available yet.</p>"}
    </div>
    ${(earlyWarning.actions || [])
      .map(
        (item) => `
          <div class="review-item">
            <div><span class="badge pending">Action</span></div>
            <p>${item}</p>
          </div>
        `
      )
      .join("")}
  `;
}

function renderPriorityFeed(events) {
  const priority = events.filter((event) => event.severity === "major").slice(0, 5);
  return priority
    .map(
      (event) => `
        <div class="feed-item">
          <div><span class="badge major">Major</span>${event.title}</div>
          <div class="meta">${event.regulator} | ${event.region} | ${event.published_at.slice(0, 10)}</div>
          <p>${event.risk_hint}</p>
        </div>
      `
    )
    .join("");
}

function applyEventFilters(events) {
  return events.filter((event) => {
    const published = event.published_at.slice(0, 10);
    if (state.eventFilterFrom && published < state.eventFilterFrom) {
      return false;
    }
    if (state.eventFilterTo && published > state.eventFilterTo) {
      return false;
    }
    return true;
  });
}

function isPlaceholderInstitutionName(name) {
  const normalized = (name || "").trim();
  if (!normalized) {
    return true;
  }
  const badMarkers = ["某", "示例", "样本", "测试", "待识别", "Not disclosed"];
  return badMarkers.some((marker) => normalized.includes(marker));
}

function isVerifiedSourceUrl(url) {
  const normalized = (url || "").trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  if (!normalized.startsWith("http")) {
    return false;
  }
  const blocked = ["example.com", "/index.html", "/index/index.html", "javascript:", "{{", "}}"];
  return !blocked.some((marker) => normalized.includes(marker));
}

function isDisplayableEvent(event) {
  const institutionName = event.institution_name_original || event.institution_name || "";
  const primarySource = (event.sources || []).find((item) => isVerifiedSourceUrl(item.url)) || null;
  return (
    Boolean(event.source_link_verified) &&
    Boolean(event.article_opened) &&
    Boolean(event.original_subject_extracted) &&
    !isPlaceholderInstitutionName(institutionName) &&
    Boolean(primarySource)
  );
}

function renderEventsTable(events) {
  const filtered = applyEventFilters(events).filter((event) => isDisplayableEvent(event));
  const summary = document.getElementById("event-filter-summary");
  const fromText = state.eventFilterFrom || "start";
  const toText = state.eventFilterTo || "latest";
  summary.textContent =
    state.eventFilterFrom || state.eventFilterTo
      ? `Showing ${filtered.length} announcements between ${fromText} and ${toText}.`
      : `Showing all ${filtered.length} available announcements.`;

  document.getElementById("events-table-shell").innerHTML = `
    <table class="events-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Regulator</th>
          <th>Institution</th>
          <th>Category</th>
          <th>Severity</th>
          <th>Confidence</th>
          <th>Original Subject</th>
          <th>Source Link</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        ${filtered
          .map(
            (event) => {
              const primarySource = (event.sources || []).find((item) => isVerifiedSourceUrl(item.url)) || null;
              const sourceLabel = "Open Source Article";
              const eventId = String(event.event_id || "").replace(/'/g, "\\'");
              return `
              <tr>
                <td>${event.published_at.slice(0, 10)}</td>
                <td>${event.regulator}</td>
                <td>${event.institution_name || event.institution_name_original}</td>
                <td>${localizeCategory(event.category)}</td>
                <td><span class="badge ${event.severity === "major" ? "major" : "approved"}">${event.severity}</span></td>
                <td><span class="badge confidence-${event.extraction_confidence || "low"}">${event.extraction_confidence || "low"}</span></td>
                <td>${event.institution_name_original || event.institution_name}</td>
                <td>${
                  primarySource
                    ? `<a class="model-button" href="${primarySource.url}" target="_blank" rel="noreferrer">` +
                      `${sourceLabel}</a>`
                    : `<span class="meta">No source URL</span>`
                }</td>
                <td>
                  <button class="model-button" onclick="editEventReview('${eventId}')">Edit Review</button>
                  <button class="danger-button" onclick="deleteEvent('${eventId}')">Delete</button>
                </td>
              </tr>
            `;
            }
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderRiskOutlook(riskOutlook) {
  document.getElementById("review-kpi-major").textContent = `${riskOutlook.major_signal_count || 0}`;
  document.getElementById("review-kpi-theme").textContent = riskOutlook.top_theme || "No signal yet";
  document.getElementById("review-kpi-window").textContent = riskOutlook.latest_window || "No window";
  document.getElementById("review-outlook").innerHTML = `
    <div class="review-item">
      <div><strong>Why This Matters</strong></div>
      <p>${riskOutlook.trend_summary}</p>
    </div>
    <div class="review-item">
      <div><strong>What Management Should Watch</strong></div>
      <p>${riskOutlook.management_message || "No management message available."}</p>
    </div>
    ${riskOutlook.priority_risks
      .map(
        (risk) => `
          <div class="review-item">
            <div><span class="badge pending">Watchpoint</span><strong>${risk.title}</strong></div>
            <div class="meta">${risk.category} | ${risk.institution} | ${risk.published_at.slice(0, 10)}</div>
            <p>${risk.risk_hint}</p>
          </div>
        `
      )
      .join("")}
    <div class="review-item">
      <div><strong>Recommended Actions</strong></div>
      ${riskOutlook.management_actions.map((item) => `<p>${item}</p>`).join("")}
    </div>
  `;
}

function renderSources(sources) {
  document.getElementById("source-list").innerHTML = sources
    .map(
      (source) => `
        <div class="source-row">
          <div class="source-main">
            <div><strong>${source.name}</strong></div>
            <div class="meta">${source.url || "No URL stored yet"}</div>
            <div class="meta">Type: ${source.kind} | Status: ${source.status || "active"} | Last sync: ${source.last_sync_result || "not run"}</div>
            <div class="meta">Health Status: ${source.health_status || "unknown"} | Parser: ${source.parser || "n/a"}</div>
          </div>
          <div class="source-actions">
            <button class="model-button" data-busy-action="update" onclick="inspectLatestSource('${source.source_id}')">Check Latest</button>
            <button class="danger-button" onclick="deleteSource('${source.source_id}', '${source.name.replace(/'/g, "\\'")}')">Delete</button>
          </div>
        </div>
      `
    )
    .join("");
}

function renderReports(links = {}) {
  const kinds = ["csv", "html", "pdf"];
  document.getElementById("report-links").innerHTML = kinds
    .map((kind) => {
      const path = links[kind];
      return `
        <div class="model-item">
          <div><strong>${kind.toUpperCase()}</strong></div>
          <div class="meta">${path || "Not exported yet"}</div>
          <a href="${state.apiBase}/api/reports/download/${kind}" target="_blank">Download ${kind.toUpperCase()}</a>
        </div>
      `;
    })
    .join("");
}

function parseStructuredResponse(answer) {
  const sections = {
    summary: "No summary extracted.",
    china: "No China management brief extracted.",
    global: "No global compliance brief extracted.",
    signals: "No signals extracted.",
    risk: "No risk implication extracted.",
    actions: "No recommended actions extracted.",
  };
  const lines = answer.split(/\r?\n/);
  let active = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    if (line.startsWith("Executive Summary:")) {
      active = "summary";
      sections.summary = line.replace("Executive Summary:", "").trim();
      continue;
    }
    if (line.startsWith("Key Signals:")) {
      active = "signals";
      sections.signals = line.replace("Key Signals:", "").trim();
      continue;
    }
    if (line.startsWith("China Management Brief:")) {
      active = "china";
      sections.china = line.replace("China Management Brief:", "").trim();
      continue;
    }
    if (line.startsWith("Global Compliance Brief:")) {
      active = "global";
      sections.global = line.replace("Global Compliance Brief:", "").trim();
      continue;
    }
    if (line.startsWith("Risk to Siemens Financial Leasing:")) {
      active = "risk";
      sections.risk = line.replace("Risk to Siemens Financial Leasing:", "").trim();
      continue;
    }
    if (line.startsWith("Recommended Actions:")) {
      active = "actions";
      sections.actions = line.replace("Recommended Actions:", "").trim();
      continue;
    }
    if (active) {
      sections[active] = `${sections[active]} ${line}`.trim();
    }
  }

  return sections;
}

function renderAiBriefCards(answer) {
  const sections = parseStructuredResponse(answer);
  document.getElementById("ai-brief-summary").textContent = sections.summary;
  document.getElementById("ai-brief-china").textContent = sections.china;
  document.getElementById("ai-brief-global").textContent = sections.global;
  document.getElementById("ai-brief-signals").textContent = sections.signals;
  document.getElementById("ai-brief-risk").textContent = sections.risk;
  document.getElementById("ai-brief-actions").textContent = sections.actions;
}

function renderAiResponse(payload) {
  state.lastAiOpinionId = payload.opinion_id || state.lastAiOpinionId || "";
  document.getElementById("ai-response").textContent = payload.answer;
  document.getElementById("ai-context-lens").textContent = payload.business_lens || "No business lens loaded.";
  document.getElementById("ai-context-agent-folder").textContent = payload.agent_folder || "No agent config folder detected yet.";
  document.getElementById("ai-response-meta").textContent =
    `Generated at ${new Date(payload.generated_at).toLocaleString()} with ${payload.model}.`;
  document.getElementById("ai-run-meta").textContent =
    `Using ${payload.context_event_count || 0} radar events and the Siemens Financial Leasing lens.`;
  setStatusBanner("AI response generated successfully.", "success");
  renderAiBriefCards(payload.answer);
}

async function setModel(name) {
  await fetchJson(`/api/models/current/${name}`, { method: "POST" });
  logActivity(`Model switched to ${name}`);
  await loadDashboard();
}

async function testModel(name) {
  const payload = await fetchJson(`/api/models/${name}/test`, { method: "POST" });
  document.getElementById("model-test-result").textContent = JSON.stringify(payload, null, 2);
  logActivity(`Model tested: ${name}`);
}

async function editModel(name) {
  const payload = {
    base_url: document.getElementById("model-base-url").value,
    api_key: document.getElementById("model-api-key").value,
    model_id: document.getElementById("model-model-id").value,
  };
  await fetchJson(`/api/models/${name}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  logActivity(`Model updated: ${name}`);
  await loadDashboard();
}

function renderModels(models) {
  document.getElementById("current-model-pill").textContent = `Model: ${models.current_model}`;
  const copilotModel = document.getElementById("copilot-current-model");
  if (copilotModel) {
    copilotModel.textContent = models.current_model;
  }
  document.getElementById("model-list").innerHTML = models.profiles
    .map(
      (profile) => `
        <div class="model-item">
          <div><strong>${profile.name}</strong> (${profile.provider})</div>
          <div class="meta">${profile.base_url}</div>
          <div class="meta">Model ID: ${profile.model_id}</div>
          <div class="toolbar">
            <button class="model-button" onclick="setModel('${profile.name}')">Use This Model</button>
            <button class="model-button" onclick="testModel('${profile.name}')">Test</button>
            <button class="model-button" onclick="editModel('${profile.name}')">Update Settings</button>
          </div>
        </div>
      `
    )
    .join("");
  const current = models.profiles.find((profile) => profile.name === models.current_model) || models.profiles[0];
  if (current) {
    document.getElementById("model-provider").value = current.provider || "openai-compatible";
    document.getElementById("model-base-url").value = current.base_url || "";
    document.getElementById("model-api-key").value = current.api_key || "";
    const modelSelect = document.getElementById("model-model-id");
    if (current.model_id) {
      modelSelect.innerHTML = `<option value="${current.model_id}">${current.model_id}</option>`;
      modelSelect.value = current.model_id;
    }
  }
}

async function loadDashboard() {
  state.dashboard = await fetchJson("/api/dashboard");
  setStatusBanner("Local ComplianceRadar API connected.", "success");
  renderCards(state.dashboard.summary);
  renderManagementDashboard(state.dashboard.management_dashboard || {});
  renderEventsTable(state.dashboard.events);
  renderRiskOutlook(state.dashboard.risk_outlook);
  renderSources(state.dashboard.sources);
  renderModels(state.dashboard.models);
  if (state.dashboard.agent_context) {
    document.getElementById("loaded-agent-name").textContent =
      `Agent: ${state.dashboard.agent_context.agent_name || "No agent loaded"}`;
    document.getElementById("ai-context-agent-folder").textContent =
      state.dashboard.agent_context.folder || "No agent config folder detected yet.";
  }
}

async function sendAiPrompt() {
  const prompt = document.getElementById("ai-prompt").value;
  const button = document.getElementById("send-ai");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Thinking...";
  document.getElementById("ai-run-meta").textContent = "Building Siemens Financial Leasing view from current radar...";
  document.getElementById("ai-response-meta").textContent = "Running analysis...";
  setStatusBanner("Submitting AI analysis request...", "info");
  try {
    const payload = await fetchJson("/api/ai/chat", {
      method: "POST",
      body: JSON.stringify({ prompt, context: "gui-console" }),
    });
    renderAiResponse(payload);
    logActivity(`AI response generated with ${payload.model} using ${payload.context_event_count} radar events.`);
  } catch (error) {
    document.getElementById("ai-response").textContent = `AI request failed: ${error.message}`;
    document.getElementById("ai-response-meta").textContent = "Generation failed.";
    document.getElementById("ai-run-meta").textContent = `AI request failed: ${error.message}`;
    setStatusBanner(`AI request failed: ${error.message}`, "error");
    logActivity(`AI response failed: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function copyAiBrief() {
  const text = document.getElementById("ai-response").textContent;
  if (!text) {
    return;
  }
  await navigator.clipboard.writeText(text);
  document.getElementById("ai-run-meta").textContent = "Full AI brief copied to clipboard.";
  setStatusBanner("AI brief copied to clipboard.", "success");
  logActivity("AI brief copied to clipboard.");
}

async function editAiOpinion() {
  const current = document.getElementById("ai-response").textContent;
  if (!current || !state.lastAiOpinionId) {
    setStatusBanner("No editable AI opinion is loaded yet.", "error");
    return;
  }
  const updated = window.prompt("Edit AI opinion", current);
  if (!updated || updated === current) {
    return;
  }
  const payload = await fetchJson(`/api/ai/opinions/${state.lastAiOpinionId}`, {
    method: "PUT",
    body: JSON.stringify({ answer: updated, edited_by: "local-user" }),
  });
  document.getElementById("ai-response").textContent = payload.answer;
  document.getElementById("ai-response-meta").textContent = `Edited at ${new Date(payload.edited_at).toLocaleString()}.`;
  renderAiBriefCards(payload.answer);
  setStatusBanner("AI opinion edited and saved to the runtime ledger.", "success");
  logActivity(`AI opinion edited: ${state.lastAiOpinionId}`);
}

function downloadAiBrief() {
  const content = document.getElementById("ai-response").textContent;
  if (!content) {
    return;
  }
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "regulatory-output.txt";
  link.click();
  URL.revokeObjectURL(url);
  document.getElementById("ai-run-meta").textContent = "AI brief exported as text.";
  setStatusBanner("AI brief exported as text.", "success");
  logActivity("AI brief exported.");
}

async function syncSources(period = state.pendingSyncPeriod) {
  setBusyState(true, "Updating...");
  startProgressSimulation("All sources");
  const periodLabel = period === "today" ? "today" : period === "30d" ? "the last 30 days" : "the last 7 days";
  document.getElementById("event-status-line").textContent = `Updating all configured sources for ${periodLabel}...`;
  setStatusBanner(`Updating all configured sources for ${periodLabel}...`, "info");
  try {
    const payload = await fetchJson("/api/sources/sync", {
      method: "POST",
      body: JSON.stringify({ period }),
    });
    clearProgressSimulation();
    setProgressState(100, "All sources update completed.", true);
    document.getElementById("event-status-line").textContent = describeSyncResult(payload, "All sources");
    setStatusBanner(describeSyncResult(payload, "All sources"), "success");
    logActivity(`Source sync completed: ${payload.synced_count} new events, ${payload.errors.length} errors.`);
    await loadDashboard();
  } catch (error) {
    clearProgressSimulation();
    setProgressState(100, `Update failed: ${error.message}`, true);
    document.getElementById("event-status-line").textContent = `Update failed: ${error.message}`;
    setStatusBanner(`Update failed: ${error.message}`, "error");
    logActivity(`Source sync failed: ${error.message}`);
  } finally {
    setBusyState(false);
  }
}

function showSyncPeriodModal() {
  const modal = document.getElementById("sync-period-modal");
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
}

function hideSyncPeriodModal() {
  const modal = document.getElementById("sync-period-modal");
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

async function syncSingleSource(sourceId) {
  if (!sourceId) {
    return;
  }
  setBusyState(true, "Updating...");
  startProgressSimulation(sourceId);
  document.getElementById("event-status-line").textContent = `Updating ${sourceId}...`;
  setStatusBanner(`Updating ${sourceId}...`, "info");
  try {
    const payload = await fetchJson("/api/sources/sync", {
      method: "POST",
      body: JSON.stringify({ source_ids: [sourceId] }),
    });
    clearProgressSimulation();
    setProgressState(100, `${sourceId} update completed.`, true);
    document.getElementById("event-status-line").textContent = describeSyncResult(payload, sourceId);
    setStatusBanner(describeSyncResult(payload, sourceId), "success");
    logActivity(`Single-source update for ${sourceId}: ${payload.synced_count} new events, ${payload.errors.length} errors.`);
    await loadDashboard();
  } catch (error) {
    clearProgressSimulation();
    setProgressState(100, `Update failed for ${sourceId}: ${error.message}`, true);
    document.getElementById("event-status-line").textContent = `Update failed for ${sourceId}: ${error.message}`;
    setStatusBanner(`Update failed for ${sourceId}: ${error.message}`, "error");
    logActivity(`Single-source update failed for ${sourceId}: ${error.message}`);
  } finally {
    setBusyState(false);
  }
}

async function saveMinimaxModel() {
  const payload = {
    base_url: document.getElementById("model-base-url").value,
    api_key: document.getElementById("model-api-key").value,
    model_id: document.getElementById("model-model-id").value,
    provider: document.getElementById("model-provider").value,
  };
  await fetchJson("/api/models/Minimax China", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  logActivity("Minimax settings updated.");
  setStatusBanner("Minimax settings updated.", "success");
  await loadDashboard();
}

async function loadModelCatalog() {
  const baseUrl = document.getElementById("model-base-url").value;
  const apiKey = document.getElementById("model-api-key").value;
  const status = document.getElementById("model-catalog-status");
  if (!baseUrl || !apiKey) {
    status.textContent = "Enter Base URL and API Key first.";
    return;
  }

  try {
    const payload = await fetchJson("/api/models/catalog", {
      method: "POST",
      body: JSON.stringify({
        provider: document.getElementById("model-provider").value,
        base_url: baseUrl,
        api_key: apiKey,
      }),
    });
    const select = document.getElementById("model-model-id");
    select.innerHTML = payload.models
      .map((name) => `<option value="${name}">${name}</option>`)
      .join("");
    status.textContent = `Loaded ${payload.models.length} model(s).`;
    setStatusBanner(`Loaded ${payload.models.length} model(s) from the remote catalog.`, "success");
    logActivity(`Loaded ${payload.models.length} models from remote catalog.`);
  } catch (error) {
    status.textContent = `Catalog error: ${error.message}`;
    setStatusBanner(`Catalog error: ${error.message}`, "error");
    logActivity(`Model catalog load failed: ${error.message}`);
  }
}

async function deleteSource(sourceId, sourceName) {
  const shouldDelete = window.confirm(`Delete source "${sourceName}"?`);
  if (!shouldDelete) {
    return;
  }
  await fetchJson(`/api/sources/${sourceId}`, { method: "DELETE" });
  document.getElementById("source-discovery-result").textContent = `Deleted source: ${sourceName}`;
  setStatusBanner(`Deleted source: ${sourceName}`, "success");
  logActivity(`Source deleted: ${sourceName}`);
  await loadDashboard();
}

async function deleteEvent(eventId) {
  const shouldDelete = window.confirm("Delete this announcement from the Event Library?");
  if (!shouldDelete) {
    return;
  }
  await fetchJson(`/api/events/${eventId}`, {
    method: "DELETE",
    body: JSON.stringify({ deleted_by: "local-user" }),
  });
  setStatusBanner("Announcement deleted from Event Library.", "success");
  logActivity(`Announcement deleted: ${eventId}`);
  await loadDashboard();
}

async function editEventReview(eventId) {
  const reviewer = window.prompt("Reviewer", "local-user");
  if (!reviewer) {
    return;
  }
  const status = window.prompt("Review status", "reviewed");
  if (!status) {
    return;
  }
  const note = window.prompt("Review note", "");
  if (note === null) {
    return;
  }
  await fetchJson(`/api/events/${eventId}/review`, {
    method: "POST",
    body: JSON.stringify({ reviewer, status, note }),
  });
  setStatusBanner("Review opinion edited and saved.", "success");
  logActivity(`Review opinion edited: ${eventId}`);
  await loadDashboard();
}

async function addSource(payload) {
  await fetchJson("/api/sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  logActivity(`Source added: ${payload.source_id}`);
  setStatusBanner(`Source added: ${payload.name || payload.source_id}`, "success");
  await loadDashboard();
}

async function discoverSource() {
  const query = document.getElementById("source-discovery-input").value.trim();
  if (!query) {
    return;
  }
  try {
    const payload = await fetchJson("/api/sources/discover", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
    document.getElementById("source-discovery-result").textContent =
      `Validated source candidate: ${payload.source.name}`;
    await addSource(payload.source);
    document.getElementById("source-discovery-result").textContent =
      `Added verified source: ${payload.source.name}`;
    document.getElementById("source-discovery-input").value = "";
  } catch (error) {
    document.getElementById("source-discovery-result").textContent =
      `Source validation failed: ${error.message}`;
    setStatusBanner(`Source validation failed: ${error.message}`, "error");
  }
}

function currentModuleForExport() {
  const active = document.querySelector(".nav-link.active");
  return active ? active.dataset.view : "dashboard";
}

async function exportReports() {
  const module = currentModuleForExport();
  const payload = await fetchJson("/api/reports/export", {
    method: "POST",
    body: JSON.stringify({ module }),
  });
  renderReports(payload);
  logActivity(`Reports exported for module: ${module}.`);
  setStatusBanner(`Reports exported for ${module}.`, "success");
  const links = Object.entries(payload)
    .filter(([kind]) => ["csv", "html", "pdf"].includes(kind))
    .map(([kind, path]) => `${kind.toUpperCase()}: ${path}`)
    .join(" | ");
  document.getElementById("event-status-line").textContent = `Reports exported for ${module}. ${links}`;
}

async function inspectLatestSource(sourceId) {
  try {
    const payload = await fetchJson(`/api/sources/${sourceId}/latest`);
    const event = payload.event;
    document.getElementById("source-discovery-result").textContent =
      `Latest live signal from ${payload.source_name}: ${event.title}`;
    setStatusBanner(`Latest live signal fetched from ${payload.source_name}.`, "success");
    logActivity(`Latest signal checked for ${payload.source_name}: ${event.title}`);
  } catch (error) {
    document.getElementById("source-discovery-result").textContent =
      `Latest signal check failed: ${error.message}`;
    setStatusBanner(`Latest signal check failed: ${error.message}`, "error");
    logActivity(`Latest signal check failed for ${sourceId}: ${error.message}`);
  }
}

function bindEvents() {
  document.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.view));
  });
  document.getElementById("send-ai").addEventListener("click", sendAiPrompt);
  document.getElementById("ai-copy-full").addEventListener("click", copyAiBrief);
  document.getElementById("ai-export-brief").addEventListener("click", downloadAiBrief);
  document.getElementById("ai-edit-opinion").addEventListener("click", editAiOpinion);
  document.getElementById("reset-demo").addEventListener("click", async () => {
    await fetchJson("/api/demo/reset", { method: "POST" });
    logActivity("Demo data reset while preserving configured models.");
    setStatusBanner("Demo data reset while preserving configured models.", "success");
    await loadDashboard();
  });
  document.getElementById("refresh-events").addEventListener("click", async () => {
    await loadDashboard();
    document.getElementById("event-status-line").textContent = "Local data refreshed.";
  });
  document.getElementById("apply-event-filters").addEventListener("click", () => {
    state.eventFilterFrom = document.getElementById("event-period-from").value;
    state.eventFilterTo = document.getElementById("event-period-to").value;
    renderEventsTable(state.dashboard.events);
    document.getElementById("event-status-line").textContent = "Event period filter applied.";
    setStatusBanner("Event period filter applied.", "success");
  });
  document.getElementById("clear-event-filters").addEventListener("click", () => {
    state.eventFilterFrom = "";
    state.eventFilterTo = "";
    document.getElementById("event-period-from").value = "";
    document.getElementById("event-period-to").value = "";
    renderEventsTable(state.dashboard.events);
    document.getElementById("event-status-line").textContent = "Event period filter cleared.";
    setStatusBanner("Event period filter cleared.", "success");
  });
  document.getElementById("update-all-events").addEventListener("click", () => {
    showSyncPeriodModal();
    document.getElementById("event-status-line").textContent =
      "Choose Today, Last 7 Days, or Last 30 Days before running source update.";
  });
  document.querySelectorAll(".sync-period-option").forEach((button) => {
    button.addEventListener("click", async () => {
      state.pendingSyncPeriod = button.dataset.period;
      hideSyncPeriodModal();
      await syncSources(state.pendingSyncPeriod);
    });
  });
  document.getElementById("sync-period-modal").addEventListener("click", (event) => {
    if (event.target.id === "sync-period-modal") {
      hideSyncPeriodModal();
    }
  });
  document.getElementById("export-reports").addEventListener("click", exportReports);
  document.getElementById("load-model-catalog").addEventListener("click", loadModelCatalog);
  document.getElementById("model-base-url").addEventListener("change", loadModelCatalog);
  document.getElementById("model-api-key").addEventListener("change", loadModelCatalog);
  document.getElementById("model-provider").addEventListener("change", loadModelCatalog);
  document.getElementById("save-minimax-model").addEventListener("click", saveMinimaxModel);
  document.getElementById("discover-source").addEventListener("click", discoverSource);
}

async function bootstrapApp() {
  bindEvents();
  renderReports();
  try {
    await detectApiBase();
    await loadDashboard();
  } catch (error) {
    setStatusBanner(`Unable to connect to the local ComplianceRadar API. ${error.message}`, "error");
    document.getElementById("event-status-line").textContent = `Unable to connect to the local ComplianceRadar API. ${error.message}`;
    logActivity(`App bootstrap failed: ${error.message}`);
  }
}

bootstrapApp();
