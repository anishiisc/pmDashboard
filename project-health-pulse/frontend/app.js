/* ── State ─────────────────────────────────────────────────────────── */
const state = {
  files: [],          // File objects selected by the user
  runId: null,
  pollTimer: null,
  pillarsConfig: null,
};

/* ── Helpers ────────────────────────────────────────────────────────── */
function ratingClass(rating) {
  if (!rating) return "unknown";
  return rating.toLowerCase().replace(/ /g, "_");
}

function chip(rating) {
  const cls = ratingClass(rating);
  return `<span class="chip chip-${cls}">${rating || "—"}</span>`;
}

function scoreBadge(score, threshold) {
  const needsReview = score < threshold;
  return `<span class="score-badge${needsReview ? " review-needed" : ""}" title="${needsReview ? "Review recommended" : ""}">${score}/10</span>`;
}

function urgencyBadge(urgency) {
  return `<span class="urgency-badge urgency-${urgency}">${urgency.replace(/_/g, " ")}</span>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ── On load ─────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  await loadPillarsConfig();
  renderEmptyPillars();
  await loadPreviousRuns();
  bindEvents();
});

/* ── API calls ────────────────────────────────────────────────────────── */
async function loadPillarsConfig() {
  try {
    const r = await fetch("/api/config/pillars");
    state.pillarsConfig = await r.json();
  } catch (e) {
    console.error("Could not load pillars config", e);
  }
}

async function loadPreviousRuns() {
  try {
    const r = await fetch("/api/runs");
    const runs = await r.json();
    const sel = document.getElementById("prev-run-select");
    runs.forEach(run => {
      const opt = document.createElement("option");
      opt.value = run.run_id;
      const date = run.created_at ? run.created_at.substring(0, 16).replace("T", " ") : "";
      opt.textContent = `${date} — ${run.overall_rating || "?"} (${run.file_count} files)`;
      sel.appendChild(opt);
    });
  } catch (e) { /* no runs yet */ }
}

/* ── Events ──────────────────────────────────────────────────────────── */
function bindEvents() {
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const browseLink = document.getElementById("browse-link");
  const submitBtn = document.getElementById("submit-btn");
  const resetBtn = document.getElementById("reset-btn");
  const prevRunSel = document.getElementById("prev-run-select");

  browseLink.addEventListener("click", e => { e.preventDefault(); fileInput.click(); });
  dropZone.addEventListener("click", e => { if (e.target !== browseLink) fileInput.click(); });

  dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    addFiles([...e.dataTransfer.files]);
  });

  fileInput.addEventListener("change", () => { addFiles([...fileInput.files]); fileInput.value = ""; });

  submitBtn.addEventListener("click", submitRun);
  resetBtn.addEventListener("click", confirmReset);

  prevRunSel.addEventListener("change", async () => {
    const runId = prevRunSel.value;
    if (!runId) return;
    try {
      const r = await fetch(`/api/runs/${runId}/final`);
      const data = await r.json();
      renderResults(data);
    } catch (e) {
      alert("Could not load run: " + e.message);
    }
  });
}

/* ── File management ─────────────────────────────────────────────────── */
const MAX_FILES = 10;
const MAX_FILE_KB = 200;

function addFiles(newFiles) {
  newFiles.forEach(f => {
    if (!f.name.endsWith(".txt")) { alert(`Only .txt files accepted: ${f.name}`); return; }
    if (f.size / 1024 > MAX_FILE_KB) { alert(`${f.name} exceeds ${MAX_FILE_KB} KB`); return; }
    // Replace duplicates
    state.files = state.files.filter(existing => existing.name !== f.name);
    state.files.push(f);
  });
  if (state.files.length > MAX_FILES) { state.files = state.files.slice(0, MAX_FILES); alert(`Max ${MAX_FILES} files.`); }
  renderFileList();
  updateSubmitBtn();
}

function renderFileList() {
  const list = document.getElementById("file-list");
  list.innerHTML = "";
  state.files.forEach((f, i) => {
    const div = document.createElement("div");
    div.className = "file-chip";
    div.innerHTML = `<span>${escHtml(f.name)}</span><button class="remove-btn" data-idx="${i}" title="Remove">✕</button>`;
    list.appendChild(div);
  });
  list.querySelectorAll(".remove-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.files.splice(Number(btn.dataset.idx), 1);
      renderFileList();
      updateSubmitBtn();
    });
  });
}

function updateSubmitBtn() {
  document.getElementById("submit-btn").disabled = state.files.length === 0;
}

/* ── Submit ──────────────────────────────────────────────────────────── */
async function submitRun() {
  if (state.files.length === 0) return;

  const form = new FormData();
  state.files.forEach(f => form.append("files", f));

  // Lock UI
  document.getElementById("submit-btn").disabled = true;
  document.getElementById("file-input").disabled = true;
  document.getElementById("progress-card").style.display = "";
  resetProgress();

  try {
    const r = await fetch("/api/runs", { method: "POST", body: form });
    if (!r.ok) {
      const err = await r.json();
      throw new Error(err.detail || r.statusText);
    }
    const data = await r.json();
    state.runId = data.run_id;
    startPolling();
  } catch (e) {
    showError("Submission failed: " + e.message);
    unlockUI();
  }
}

/* ── Polling ─────────────────────────────────────────────────────────── */
function startPolling() {
  state.pollTimer = setInterval(pollStatus, 1500);
}

function stopPolling() {
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

async function pollStatus() {
  try {
    const r = await fetch(`/api/runs/${state.runId}/status`);
    const s = await r.json();
    updateProgress(s);

    if (s.state === "complete") {
      stopPolling();
      const fr = await fetch(`/api/runs/${state.runId}/final`);
      const data = await fr.json();
      renderResults(data);
      unlockUI();
      await loadPreviousRuns();  // refresh dropdown
    } else if (s.state === "failed") {
      stopPolling();
      showError(`Pipeline failed at stage ${s.stage || "?"}: ${s.message}`);
      unlockUI();
    }
  } catch (e) {
    console.error("Poll error", e);
  }
}

/* ── Progress ─────────────────────────────────────────────────────────── */
const STAGE_ORDER = ["S0_ingest", "S1_extract", "S2_grounding", "S3_debate", "S4_rollup", "S5_recommend", "S6_assemble"];

function resetProgress() {
  document.querySelectorAll("#progress-list li").forEach(li => {
    li.className = "";
    li.querySelector(".step-icon").textContent = "○";
  });
}

function updateProgress(status) {
  const currentStage = status.stage;
  const isDone = status.state === "complete";
  const isFailed = status.state === "failed";

  const currentIdx = STAGE_ORDER.indexOf(currentStage);

  document.querySelectorAll("#progress-list li").forEach((li, i) => {
    const stageId = STAGE_ORDER[i];
    const icon = li.querySelector(".step-icon");
    li.className = "";
    if (isDone || i < currentIdx) {
      li.classList.add("done"); icon.textContent = "✓";
    } else if (stageId === currentStage) {
      if (isFailed) { li.classList.add("failed"); icon.textContent = "✗"; }
      else { li.classList.add("active"); icon.innerHTML = '<span class="spinner"></span>'; }
    } else {
      icon.textContent = "○";
    }
  });
}

/* ── Reset ────────────────────────────────────────────────────────────── */
async function confirmReset() {
  if (!confirm("Clear all selected files and results? Previous runs are preserved.")) return;
  stopPolling();
  state.files = [];
  state.runId = null;
  renderFileList();
  updateSubmitBtn();
  document.getElementById("progress-card").style.display = "none";
  resetProgress();
  document.getElementById("results-area").innerHTML = "";
  renderEmptyPillars();
  try { await fetch("/api/reset", { method: "POST" }); } catch (e) { /* ignore */ }
}

function unlockUI() {
  document.getElementById("submit-btn").disabled = state.files.length === 0;
  document.getElementById("file-input").disabled = false;
}

/* ── Empty pillar cards ──────────────────────────────────────────────── */
function renderEmptyPillars() {
  if (!state.pillarsConfig) return;
  const area = document.getElementById("results-area");
  let html = "";
  state.pillarsConfig.pillars.forEach(pillar => {
    html += `
    <div class="pillar-card" style="margin-bottom:16px;">
      <div class="pillar-header">
        <span class="pillar-id">${escHtml(pillar.id)}</span>
        <span class="pillar-name">${escHtml(pillar.name)}</span>
        ${chip(null)}
      </div>
      <div class="pillar-body">
        ${pillar.items.map(item => `
          <div class="item-row">
            <div class="item-header">
              <span class="item-id">${escHtml(item.id)}</span>
              <span class="item-name">${escHtml(item.name)}</span>
              ${chip(null)}
            </div>
          </div>
        `).join("")}
        <div class="empty-state">Upload transcripts and click Submit to analyse</div>
      </div>
    </div>`;
  });
  area.innerHTML = html;
}

/* ── Error display ───────────────────────────────────────────────────── */
function showError(msg) {
  const area = document.getElementById("results-area");
  area.innerHTML = `<div class="card" style="border-color:#c00;color:#a00;padding:16px;">${escHtml(msg)}</div>`;
}

/* ── Render results ──────────────────────────────────────────────────── */
const REVIEW_THRESHOLD = 6; // matches default; ideally fetch from config

function renderResults(data) {
  const area = document.getElementById("results-area");
  let html = "";

  // Summary banner
  const summary = data.summary || {};
  html += `
  <div class="summary-banner" style="margin-bottom:16px;">
    <div class="summary-row">
      <span class="summary-label">Overall</span>
      ${chip(summary.overall_rating)}
      <span class="summary-meta">Review needed: ${(summary.items_flagged_for_review || []).length}</span>
      <span class="summary-meta">Revised by debate: ${(summary.ratings_changed_by_debate || []).length}</span>
    </div>
    ${(data.integrity_flags || []).length > 0 ? `
    <div class="integrity-banner">
      ⚠ ${data.integrity_flags.length} integrity flag(s): ${data.integrity_flags.map(f =>
        `${escHtml(f.ref)} — ${escHtml(f.description)}`).join("; ")}
    </div>` : ""}
  </div>`;

  // Pillar cards
  (data.pillars || []).forEach(pillar => {
    const nameMap = getPillarName(pillar.pillar_id);
    html += renderPillarCard(pillar, nameMap);
  });

  area.innerHTML = html;
  bindCollapsibles(area);
  bindCommentaryActions(area);
}

function getPillarName(pillarId) {
  if (!state.pillarsConfig) return pillarId;
  const p = state.pillarsConfig.pillars.find(x => x.id === pillarId);
  return p ? p.name : pillarId;
}

function getItemName(itemId) {
  if (!state.pillarsConfig) return itemId;
  for (const p of state.pillarsConfig.pillars) {
    const item = p.items.find(x => x.id === itemId);
    if (item) return item.name;
  }
  return itemId;
}

function renderPillarCard(pillar, name) {
  const pid = pillar.pillar_id;
  const reviewFlag = pillar.manager_review_required ? ` <span class="flag-icon" title="Manager review recommended">⚑</span>` : "";
  const coverageFlag = pillar.coverage_gap ? ` <span class="coverage-flag" title="Some items not evidenced">◌ coverage gap</span>` : "";
  const confidenceText = `${pillar.confidence_mean || "—"}`;

  let html = `
  <div class="pillar-card" style="margin-bottom:16px;">
    <div class="pillar-header" data-pillar="${pid}">
      <span class="pillar-id">${escHtml(pid)}</span>
      <span class="pillar-name">${escHtml(name || pid)}</span>
      ${chip(pillar.rating)}${reviewFlag}${coverageFlag}
      <span class="pillar-meta">conf ${confidenceText}</span>
      <span class="pillar-toggle" id="toggle-${pid}">▼</span>
    </div>
    <div class="pillar-body" id="body-${pid}">`;

  // Items
  (pillar.items || []).forEach(item => {
    html += renderItemRow(item);
  });

  // Recommendations
  if (pillar.recommendations && pillar.recommendations.length) {
    html += `<div class="rec-section"><div class="commentary-label">Recommendations</div>`;
    pillar.recommendations.forEach(rec => {
      html += `<div class="rec-item">${urgencyBadge(rec.urgency)} <span>${escHtml(rec.action)}</span> <em style="color:#aaa;font-size:11px;">(${escHtml(rec.owner_role)})</em></div>`;
    });
    html += `</div>`;
  }

  // Commentary
  if (pillar.suggested_commentary) {
    html += `
    <div class="commentary-section">
      <div class="commentary-label">Pillar commentary <span class="commentary-draft-note">draft — please review</span></div>
      <textarea class="commentary-box" id="commentary-${pid}" rows="4">${escHtml(pillar.suggested_commentary)}</textarea>
      <div class="commentary-actions">
        <button class="btn-sm accept-btn" data-pillar="${pid}">Accept draft</button>
        <button class="btn-sm copy-btn" data-pillar="${pid}">Copy text</button>
      </div>
    </div>`;
  }

  // Manager prompts
  if (pillar.manager_prompts && pillar.manager_prompts.length) {
    html += `<div class="prompts-section"><div class="prompt-label">Questions for you</div>`;
    pillar.manager_prompts.forEach(q => {
      html += `<div class="prompt-item">${escHtml(q)}</div>`;
    });
    html += `</div>`;
  }

  html += `</div></div>`;
  return html;
}

function renderItemRow(item) {
  const changed = item.draft_rating !== item.final_rating
    ? `<span class="item-changed">draft: ${escHtml(item.draft_rating)} → ${escHtml(item.final_rating)}</span>` : "";
  const threshold = REVIEW_THRESHOLD;
  const badge = item.verification_score != null ? scoreBadge(item.verification_score, threshold) : "";
  const reviewIcon = item.manager_review_required ? `<span class="flag-icon" title="Review recommended">⚑</span>` : "";

  const hasEvidence = item.evidence && item.evidence.length > 0;
  const hasDebate = item.debate != null;

  let html = `
  <div class="item-row">
    <div class="item-header">
      <span class="item-id">${escHtml(item.item_id)}</span>
      <span class="item-name">${escHtml(getItemName(item.item_id))}</span>
      <div class="item-badge-row">
        ${chip(item.final_rating)} ${badge} ${reviewIcon} ${changed}
      </div>
    </div>`;

  if (hasEvidence) {
    const uid = `ev-${item.item_id.replace(".", "_")}`;
    html += `<button class="collapsible-toggle" data-target="${uid}">Evidence (${item.evidence.length})</button>
    <div class="collapsible-body" id="${uid}" style="display:none;">`;
    item.evidence.forEach(q => {
      html += `<div class="evidence-item">
        <span class="evidence-ref" title="${escHtml(lookupDocInfo(q.ref))}">${escHtml(q.ref)}</span>
        "${escHtml(q.text)}"
      </div>`;
    });
    html += `</div>`;
  }

  if (hasDebate) {
    const uid2 = `db-${item.item_id.replace(".", "_")}`;
    const debate = item.debate;
    html += `<button class="collapsible-toggle" data-target="${uid2}">Debate</button>
    <div class="collapsible-body" id="${uid2}" style="display:none;">`;
    if (debate.challenge) {
      html += `<div class="debate-section">
        <div class="debate-label">Challenger (${debate.challenge.stance}${debate.challenge.proposed_rating ? " → " + debate.challenge.proposed_rating : ""})</div>
        <div class="debate-text">${escHtml(debate.challenge.argument || "No argument.")}</div>
      </div>`;
    }
    if (debate.rebuttal) {
      html += `<div class="debate-section">
        <div class="debate-label">Defender (${debate.rebuttal.response})</div>
        <div class="debate-text">${escHtml(debate.rebuttal.argument || "")}</div>
      </div>`;
    }
    if (item.reasoning) {
      html += `<div class="debate-section">
        <div class="debate-label">Judge reasoning</div>
        <div class="debate-text">${escHtml(item.reasoning)}</div>
      </div>`;
    }
    html += `</div>`;
  }

  html += `</div>`;
  return html;
}

// Placeholder — in a richer version, we'd have the source_documents in state
function lookupDocInfo(ref) {
  return ref;  // e.g. "D3:L014"
}

/* ── Collapsible toggle ─────────────────────────────────────────────── */
function bindCollapsibles(root) {
  root.querySelectorAll(".collapsible-toggle").forEach(btn => {
    btn.addEventListener("click", () => {
      const target = document.getElementById(btn.dataset.target);
      if (!target) return;
      const isOpen = target.style.display !== "none";
      target.style.display = isOpen ? "none" : "";
      btn.textContent = btn.textContent.replace(/^(Hide|Show|Evidence|Debate)/, m => {
        if (m === "Evidence" || m === "Debate") return m;
        return isOpen ? m.replace("Hide", "Show") : m.replace("Show", "Hide");
      });
    });
  });

  // Pillar header toggle
  root.querySelectorAll(".pillar-header[data-pillar]").forEach(header => {
    header.addEventListener("click", () => {
      const pid = header.dataset.pillar;
      const body = document.getElementById(`body-${pid}`);
      const toggle = document.getElementById(`toggle-${pid}`);
      if (!body) return;
      const isOpen = body.style.display !== "none";
      body.style.display = isOpen ? "none" : "";
      if (toggle) toggle.classList.toggle("open", !isOpen);
    });
  });
}

/* ── Commentary actions ─────────────────────────────────────────────── */
function bindCommentaryActions(root) {
  root.querySelectorAll(".accept-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const pid = btn.dataset.pillar;
      const ta = document.getElementById(`commentary-${pid}`);
      if (!ta) return;
      ta.classList.add("accepted");
      ta.readOnly = true;
      btn.textContent = "Accepted";
      btn.classList.add("accepted");
    });
  });

  root.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pid = btn.dataset.pillar;
      const ta = document.getElementById(`commentary-${pid}`);
      if (!ta) return;
      try {
        await navigator.clipboard.writeText(ta.value);
        const orig = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = orig; }, 1500);
      } catch (e) {
        alert("Copy failed: " + e.message);
      }
    });
  });
}
