"use strict";

const API_ROOT = "/knowledge/documents";

const state = {
  documents: [],
  total: 0,
  limit: 50,
  offset: 0,
  selected: new Set(),
  loading: false,
  sortKey: null,
  sortDirection: "ascending",
};

const elements = {
  body: document.querySelector("#documents-body"),
  empty: document.querySelector("#empty-state"),
  loading: document.querySelector("#loading-state"),
  notice: document.querySelector("#notice"),
  query: document.querySelector("#filter-query"),
  type: document.querySelector("#filter-type"),
  status: document.querySelector("#filter-status"),
  project: document.querySelector("#filter-project"),
  projectOptions: document.querySelector("#project-options"),
  source: document.querySelector("#filter-source"),
  toolbar: document.querySelector("#bulk-toolbar"),
  selectedCount: document.querySelector("#selected-count"),
  selectPage: document.querySelector("#select-page"),
  range: document.querySelector("#range-label"),
  page: document.querySelector("#page-label"),
  pageSize: document.querySelector("#page-size"),
  previous: document.querySelector("#previous-page"),
  next: document.querySelector("#next-page"),
};

function statusLabel(status) {
  const labels = {
    indexed: "Indexed",
    not_indexed: "Not indexed",
    failed: "Failed",
    indexing: "Indexing",
  };
  return labels[status] || String(status || "Unknown").replaceAll("_", " ");
}

function typeLabel(sourceType) {
  const labels = {
    document: "Document",
    transcription: "Audio",
    audio: "Audio",
    image: "Image",
    ocr: "OCR",
    web: "Web",
    email: "Email",
    git: "Git",
  };
  const value = String(sourceType || "Unknown");
  return labels[value.toLowerCase()]
    || value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formattedDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const today = new Date();
  const isToday = date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
  const day = isToday ? "Today" : new Intl.DateTimeFormat("en-GB", {
    month: "short",
    day: "numeric",
  }).format(date);
  const time = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  return `${day}\n${time}`;
}

function showNotice(message, error = false) {
  elements.notice.textContent = message;
  elements.notice.classList.toggle("error", error);
  elements.notice.hidden = !message;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string" ? detail : `Request failed (HTTP ${response.status})`
    );
  }
  return payload;
}

function queryParameters() {
  const params = new URLSearchParams({
    limit: String(state.limit),
    offset: String(state.offset),
  });
  const query = elements.query.value.trim();
  const type = elements.type.value.trim();
  const project = elements.project.value.trim();
  if (query) params.set("query", query);
  if (elements.status.value !== "all") {
    params.set("status", elements.status.value);
  }
  if (type) params.set("source_type", type);
  if (project) params.set("project", project);
  if (elements.source.value) {
    params.set("source_available", elements.source.value);
  }
  return params;
}

async function loadStatistics() {
  const statuses = ["indexed", "not_indexed", "failed"];
  const totals = await Promise.all(statuses.map(async (status) => {
    const params = new URLSearchParams({status, limit: "1", offset: "0"});
    const result = await apiRequest(`${API_ROOT}?${params}`);
    return [status, result.total];
  }));
  for (const [status, total] of totals) {
    const id = status === "not_indexed" ? "stat-not-indexed" : `stat-${status}`;
    document.querySelector(`#${id}`).textContent = total.toLocaleString();
  }
}

async function loadDocuments({refreshStats = false} = {}) {
  if (state.loading) return;
  state.loading = true;
  elements.loading.hidden = false;
  elements.empty.hidden = true;
  elements.body.replaceChildren();
  showNotice("");
  try {
    const result = await apiRequest(`${API_ROOT}?${queryParameters()}`);
    state.documents = result.documents || [];
    state.total = Number(result.total || 0);
    reconcileSelection();
    renderDocuments();
    renderPagination();
    updateProjectOptions();
    if (refreshStats) await loadStatistics();
  } catch (error) {
    state.documents = [];
    state.total = 0;
    renderDocuments();
    renderPagination();
    showNotice(error.message, true);
  } finally {
    state.loading = false;
    elements.loading.hidden = true;
  }
}

function reconcileSelection() {
  const visible = new Set(state.documents.map((document) => document.document_id));
  for (const id of [...state.selected]) {
    if (!visible.has(id)) state.selected.delete(id);
  }
  renderSelection();
}

function renderSelection() {
  elements.selectedCount.textContent = state.selected.size;
  elements.toolbar.hidden = state.selected.size === 0;
  const pageIds = state.documents.map((document) => document.document_id);
  const selectedOnPage = pageIds.filter((id) => state.selected.has(id)).length;
  elements.selectPage.checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
  elements.selectPage.indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
  updateBulkEligibility();
}

function updateBulkEligibility() {
  const selected = state.documents.filter((documentRecord) =>
    state.selected.has(documentRecord.document_id)
  );
  document.querySelectorAll("[data-bulk-action]").forEach((button) => {
    const enabled = selected.some((record) =>
      isEligibleForBulk(record, button.dataset.bulkAction)
    );
    button.disabled = !enabled;
    button.title = enabled ? "" : "No selected documents are eligible";
  });
}

function isEligibleForBulk(record, operation) {
  const available = record.source_available === true;
  const eligibility = {
    index: record.index_status === "not_indexed" && available,
    reindex: record.index_status === "indexed" && available,
    retry: record.index_status === "failed" && available,
    "delete-index": record.index_status === "indexed",
    delete: true,
  };
  return Boolean(eligibility[operation]);
}

function cell(text, className = "") {
  const element = document.createElement("td");
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function statusCell(documentRecord) {
  const td = document.createElement("td");
  const status = document.createElement("span");
  const normalized = documentRecord.index_status || "other";
  status.className = `status status-${normalized.replaceAll("_", "-")}`;
  status.textContent = statusLabel(normalized);
  td.append(status);
  return td;
}

function filenameCell(documentRecord) {
  const td = document.createElement("td");
  td.className = "filename";
  const title = document.createElement("span");
  title.className = "filename-title";
  title.textContent = documentRecord.source_filename || "Untitled";
  td.append(title);
  if (documentRecord.error) {
    const error = document.createElement("span");
    error.className = "row-error";
    error.textContent = documentRecord.error;
    error.title = documentRecord.error;
    td.append(error);
  }
  return td;
}

function sourceCell(documentRecord) {
  const available = documentRecord.source_available === true;
  const td = cell(available ? "✔ Available" : "Not local", "source");
  td.classList.add(available ? "source-available" : "source-not-local");
  return td;
}

function allowedActions(documentRecord) {
  const available = documentRecord.source_available === true;
  switch (documentRecord.index_status) {
    case "indexed":
      return [
        ...(available ? [{operation: "reindex", label: "Reindex"}] : []),
        {operation: "delete-index", label: "Delete Index"},
        {operation: "delete", label: "Delete Knowledge", danger: true},
      ];
    case "not_indexed":
      return [
        ...(available ? [{operation: "index", label: "Index"}] : []),
        {operation: "delete", label: "Delete Knowledge", danger: true},
      ];
    case "failed":
      return [
        ...(available ? [{operation: "retry", label: "Retry"}] : []),
        {operation: "delete", label: "Delete Knowledge", danger: true},
      ];
    default:
      return [];
  }
}

function actionsCell(documentRecord) {
  const td = document.createElement("td");
  td.className = "actions-column";
  const actions = allowedActions(documentRecord);
  if (!actions.length) {
    td.textContent = "—";
    return td;
  }
  const menu = document.createElement("details");
  menu.className = "action-menu";
  const trigger = document.createElement("summary");
  trigger.textContent = "⋮";
  trigger.setAttribute("aria-label", `Actions for ${documentRecord.source_filename || "document"}`);
  const items = document.createElement("div");
  items.className = "action-menu-items";
  for (const action of actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = action.label;
    button.disabled = Boolean(action.disabled);
    if (action.disabled) button.title = "Local source artifact is missing";
    if (action.danger) button.classList.add("danger-text");
    button.addEventListener("click", () => {
      menu.open = false;
      runBulkAction(action.operation, [documentRecord.document_id]);
    });
    items.append(button);
  }
  menu.append(trigger, items);
  td.append(menu);
  return td;
}

function sortedDocuments() {
  if (!state.sortKey) return state.documents;
  const direction = state.sortDirection === "ascending" ? 1 : -1;
  const values = {
    filename: (record) => String(record.source_filename || "").toLocaleLowerCase(),
    status: (record) => String(record.index_status || ""),
    chunks: (record) => Number(record.chunk_count || 0),
    updated: (record) => Date.parse(record.updated_at || "") || 0,
  };
  const value = values[state.sortKey];
  return [...state.documents].sort((left, right) => {
    const leftValue = value(left);
    const rightValue = value(right);
    if (typeof leftValue === "string") {
      return leftValue.localeCompare(rightValue) * direction;
    }
    return (leftValue - rightValue) * direction;
  });
}

function renderDocuments() {
  const fragment = document.createDocumentFragment();
  for (const documentRecord of sortedDocuments()) {
    const row = document.createElement("tr");
    const select = document.createElement("td");
    select.className = "select-column";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(documentRecord.document_id);
    checkbox.setAttribute(
      "aria-label",
      `Select ${documentRecord.source_filename || documentRecord.document_id}`
    );
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(documentRecord.document_id);
      else state.selected.delete(documentRecord.document_id);
      renderSelection();
    });
    select.append(checkbox);
    row.append(
      select,
      filenameCell(documentRecord),
      cell(typeLabel(documentRecord.source_type)),
      cell(documentRecord.project || "—"),
      statusCell(documentRecord),
      cell(String(documentRecord.chunk_count ?? 0), "numeric"),
      sourceCell(documentRecord),
      cell(formattedDate(documentRecord.updated_at), "updated"),
      actionsCell(documentRecord),
    );
    fragment.append(row);
  }
  elements.body.replaceChildren(fragment);
  elements.empty.hidden = state.documents.length !== 0 || state.loading;
  renderSelection();
}

function renderPagination() {
  const start = state.total === 0 ? 0 : state.offset + 1;
  const end = Math.min(state.offset + state.documents.length, state.total);
  const page = Math.floor(state.offset / state.limit) + 1;
  const pageCount = Math.max(1, Math.ceil(state.total / state.limit));
  elements.range.textContent = `${start.toLocaleString()}–${end.toLocaleString()} of ${state.total.toLocaleString()}`;
  elements.page.textContent = `Page ${page.toLocaleString()} of ${pageCount.toLocaleString()}`;
  elements.previous.disabled = state.offset === 0;
  elements.next.disabled = state.offset + state.limit >= state.total;
}

function updateProjectOptions() {
  const projects = [...new Set(
    state.documents.map((document) => document.project).filter(Boolean)
  )].sort();
  elements.projectOptions.replaceChildren(...projects.map((project) => {
    const option = document.createElement("option");
    option.value = project;
    return option;
  }));
}

async function runBulkAction(operation, documentIds) {
  if (!documentIds.length) return;
  const destructive = ["delete", "delete-index"].includes(operation);
  if (destructive) {
    const label = operation === "delete"
      ? "delete the selected documents from Knowledge"
      : "delete the selected indexes";
    if (!window.confirm(`Confirm: ${label}?`)) return;
  }
  showNotice(`Running ${operation} for ${documentIds.length} document(s)…`);
  try {
    const result = await apiRequest(`${API_ROOT}/bulk/${operation}`, {
      method: "POST",
      body: JSON.stringify({document_ids: documentIds}),
    });
    const message = result.failed
      ? `${result.succeeded} succeeded; ${result.failed} failed.`
      : `${result.succeeded} document(s) completed successfully.`;
    state.selected.clear();
    await loadDocuments({refreshStats: true});
    showNotice(message, result.failed > 0);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function scheduleFilterReload() {
  window.clearTimeout(scheduleFilterReload.timer);
  scheduleFilterReload.timer = window.setTimeout(() => {
    state.offset = 0;
    state.selected.clear();
    loadDocuments();
  }, 300);
}

elements.query.addEventListener("input", scheduleFilterReload);
elements.type.addEventListener("input", scheduleFilterReload);
elements.project.addEventListener("input", scheduleFilterReload);
elements.status.addEventListener("change", () => {
  state.offset = 0;
  state.selected.clear();
  loadDocuments();
});
elements.source.addEventListener("change", () => {
  state.offset = 0;
  state.selected.clear();
  loadDocuments();
});
elements.selectPage.addEventListener("change", () => {
  for (const documentRecord of state.documents) {
    if (elements.selectPage.checked) state.selected.add(documentRecord.document_id);
    else state.selected.delete(documentRecord.document_id);
  }
  renderDocuments();
});
elements.previous.addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  state.selected.clear();
  loadDocuments();
});
elements.next.addEventListener("click", () => {
  state.offset += state.limit;
  state.selected.clear();
  loadDocuments();
});
elements.pageSize.addEventListener("change", () => {
  state.limit = Number(elements.pageSize.value);
  state.offset = 0;
  state.selected.clear();
  loadDocuments();
});
document.querySelectorAll("[data-bulk-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const documentIds = state.documents
      .filter((record) => state.selected.has(record.document_id))
      .filter((record) => isEligibleForBulk(record, button.dataset.bulkAction))
      .map((record) => record.document_id);
    runBulkAction(button.dataset.bulkAction, documentIds);
  });
});
document.querySelectorAll("[data-status-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.status.value = button.dataset.statusFilter;
    state.offset = 0;
    state.selected.clear();
    loadDocuments();
  });
});
document.querySelectorAll("[data-sort-key]").forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    if (state.sortKey === key) {
      state.sortDirection = state.sortDirection === "ascending"
        ? "descending"
        : "ascending";
    } else {
      state.sortKey = key;
      state.sortDirection = "ascending";
    }
    document.querySelectorAll("[data-sort-key]").forEach((sortButton) => {
      const active = sortButton.dataset.sortKey === state.sortKey;
      const header = sortButton.closest("th");
      header.setAttribute(
        "aria-sort",
        active ? state.sortDirection : "none",
      );
      sortButton.querySelector(".sort-indicator").textContent = active
        ? state.sortDirection === "ascending" ? "▲" : "▼"
        : "";
    });
    renderDocuments();
  });
});
document.addEventListener("click", (event) => {
  document.querySelectorAll(".action-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});

loadDocuments({refreshStats: true}).catch((error) => {
  showNotice(error.message, true);
});
