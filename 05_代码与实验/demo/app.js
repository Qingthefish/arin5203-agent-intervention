const state = {
  payload: null,
  family: "held-t8",
  condition: "full_evidence",
  method: "typed_card_retention",
  mode: "story",
};

const statusLabels = {
  authority_status: "Authority",
  clearance_status: "Clearance",
  hold_status: "Active hold",
  delegation_status: "Delegation",
  recovery_status: "Recovery",
};

const decisionLabels = {
  AUTO_EXECUTE: "Execute",
  REQUEST_CONFIRMATION: "Confirm",
  HANDOFF: "Handoff",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function activeRun() {
  return state.payload.runs.find(item =>
    item.family_id === state.family
    && item.condition === state.condition
    && item.method === state.method
  );
}

function activeFamily() {
  return state.payload.families.find(item => item.family_id === state.family);
}

function routeClass(decision) {
  if (decision === "REQUEST_CONFIRMATION") return "confirm";
  if (decision === "HANDOFF") return "handoff";
  return "execute";
}

function statusClass(value) {
  if (["MISSING", "BLOCKED"].includes(value)) return value.toLowerCase();
  if (value === "REPAIRABLE_GAP") return "gap";
  return "";
}

function formatValue(value) {
  if (typeof value === "number") return value.toLocaleString("en-HK");
  return String(value);
}

function pct(value) {
  if (value === null || value === undefined) return "n/a";
  return `${Math.round(value * 100)}%`;
}

function renderControls() {
  document.querySelector("#family-tabs").innerHTML = state.payload.families.map(item => `
    <button class="${item.family_id === state.family ? "active" : ""}" data-family="${esc(item.family_id)}">
      ${esc(item.label)}
    </button>`).join("");

  document.querySelector("#method-picker").innerHTML = `
    <span>Memory strategy</span>
    <select aria-label="Memory strategy">
      ${state.payload.methods.map(item => `<option value="${esc(item.id)}" ${item.id === state.method ? "selected" : ""}>${esc(item.label)}</option>`).join("")}
    </select>`;

  document.querySelector("#condition-strip").innerHTML = state.payload.conditions.map(item => `
    <button class="${item.id === state.condition ? "active" : ""}" data-condition="${esc(item.id)}">
      <strong>${esc(item.label)}</strong><span>${esc(item.short)}</span>
    </button>`).join("");

  document.querySelectorAll("[data-family]").forEach(button => button.addEventListener("click", () => {
    state.family = button.dataset.family;
    render();
  }));
  document.querySelectorAll("[data-condition]").forEach(button => button.addEventListener("click", () => {
    state.condition = button.dataset.condition;
    render();
  }));
  document.querySelector("#method-picker select").addEventListener("change", event => {
    state.method = event.target.value;
    render();
  });
}

function cardRows(run, compact = false) {
  const decisive = new Set(run.result.decisive_card_ids);
  const ignored = new Set(run.result.ignored_card_ids);
  if (run.cards.length === 0) {
    return compact
      ? `<div class="empty-proof">No proof card survived this memory strategy.</div>`
      : `<tr><td colspan="6" class="empty-proof">No proof card survived this memory strategy.</td></tr>`;
  }
  if (compact) {
    return run.cards.map(card => `
      <div class="mini-card ${decisive.has(card.card_id) ? "decisive" : ""} ${ignored.has(card.card_id) ? "ignored" : ""}">
        <span>${esc(card.kind)}</span><span>${esc(card.card_id)}</span>
      </div>`).join("");
  }
  return run.cards.map(card => `
    <tr class="${ignored.has(card.card_id) ? "ignored" : ""}">
      <td><code>${esc(card.card_id)}</code><br><small>${esc(card.source_event_ids.join(", "))}</small></td>
      <td><span class="pill">${esc(card.kind)}</span></td>
      <td>${esc(card.issuer_id)}</td>
      <td>${esc(card.subject_id)}</td>
      <td>${esc(card.scope.map(pair => pair.join("=")).join(" · "))}</td>
      <td>${decisive.has(card.card_id) ? "Used" : ignored.has(card.card_id) ? "Ignored" : "Supporting"}</td>
    </tr>`).join("");
}

function stateRows(run) {
  if (run.state.state_diff.length === 0) {
    return `<div class="no-change">No external mutation applied.</div>`;
  }
  return run.state.state_diff.map(item => `
    <div class="diff-row">
      <code>${esc(item.field)}</code>
      <span class="before">${esc(formatValue(item.before))}</span>
      <span class="diff-arrow">→</span>
      <span class="after">${esc(formatValue(item.after))}</span>
    </div>`).join("");
}

function renderStory(run, family) {
  const directDecision = run.direct.decision;
  const changedByAudit = directDecision !== run.decision;
  const verdictClass = run.route_correct ? "pass" : "fail";
  const verdictText = run.route_correct ? "Matches frozen oracle" : "Known failure boundary";
  document.querySelector("#story-view").innerHTML = `
    <div class="story-top">
      <article class="request-panel">
        <span class="panel-label">${esc(family.eyebrow)} · held-out request</span>
        <p class="request-text">“${esc(family.request)}”</p>
        <p class="risk-note">${esc(family.risk)}</p>
      </article>
      <article class="decision-panel">
        <span class="panel-label">Direct route → evidence audit</span>
        <div class="pipeline">
          <div class="route-chip ${routeClass(directDecision)}">
            <small>Direct</small><strong>${esc(decisionLabels[directDecision])}</strong>
          </div>
          <span class="pipeline-arrow">${changedByAudit ? "→ corrected →" : "→ verified →"}</span>
          <div class="route-chip ${routeClass(run.decision)}">
            <small>Final</small><strong>${esc(run.decision_label)}</strong>
          </div>
        </div>
        <p>${esc(run.decision_summary)}</p>
        <div class="verdict ${verdictClass}">${esc(verdictText)} · expected ${esc(decisionLabels[run.expected_decision])}</div>
      </article>
    </div>
    <div class="journey">
      <article class="stage">
        <span class="panel-label">01 · active memory</span>
        <h3>${esc(run.condition_label)}</h3>
        <p>${esc(run.condition_summary)}.</p>
        <div class="metric-grid">
          <div><strong>${esc(run.exact_raw_tokens)}</strong><span>raw tokens</span></div>
          <div><strong>${esc(run.removed_event_ids.length)}</strong><span>events removed</span></div>
          <div><strong>${esc(run.critical_kind)}</strong><span>critical type</span></div>
        </div>
      </article>
      <div class="arrow">→</div>
      <article class="stage">
        <span class="panel-label">02 · retained proof</span>
        <h3>${esc(run.method_label)}</h3>
        <div class="memory-stack">${cardRows(run, true)}</div>
        <p>${esc(run.retained_card_ids.length)} / ${esc(run.visible_card_ids.length)} visible cards rehydrated · citation precision ${esc(pct(run.direct.proof_citation_precision))}</p>
      </article>
      <div class="arrow">→</div>
      <article class="stage ${run.state.harmful_mutation ? "danger-stage" : ""}">
        <span class="panel-label">03 · deterministic state replay</span>
        <h3>${run.state.harmful_mutation ? "Harmful mutation" : run.state.mutation_applied ? "Mutation applied" : "Mutation paused"}</h3>
        <div class="state-diff">${stateRows(run)}</div>
        <p>${run.state.harmful_mutation ? "The missing hold was never visible to the compactor." : run.state.mutation_applied ? "The verified route reached the tool." : "Confirm or Handoff stopped the tool call."}</p>
      </article>
    </div>`;
}

function renderDebug(run) {
  const obligations = Object.entries(statusLabels).map(([key, label]) => {
    const value = run.result[key];
    return `<div class="obligation"><span>${esc(label)}</span><span class="status ${statusClass(value)}">${esc(value)}</span></div>`;
  }).join("");
  document.querySelector("#debug-view").innerHTML = `
    <div class="debug-head">
      <span class="panel-label">Frozen runtime inspection</span>
      <h2>${esc(run.action.operation)} → ${esc(run.action.target_id)}</h2>
      <p>${esc(run.case_id)} · ${esc(run.method_label)} · ${esc(run.exact_raw_tokens)} raw tokens</p>
    </div>
    <div class="debug-grid">
      <aside class="obligations">
        <span class="panel-label">Proof obligations</span>
        ${obligations}
        <div class="obligation"><span>Final route</span><span class="status ${routeClass(run.decision)}">${esc(run.decision_label.toUpperCase())}</span></div>
        <div class="obligation"><span>Route correct</span><span class="status ${run.route_correct ? "" : "blocked"}">${run.route_correct ? "YES" : "NO"}</span></div>
        <div class="obligation"><span>Citation precision</span><span class="status">${esc(pct(run.direct.proof_citation_precision))}</span></div>
      </aside>
      <div class="card-table">
        <table>
          <thead><tr><th>Card / source</th><th>Type</th><th>Issuer</th><th>Subject</th><th>Scope</th><th>Verdict</th></tr></thead>
          <tbody>${cardRows(run)}</tbody>
        </table>
      </div>
    </div>
    <div class="memory-inspector">
      <span class="panel-label">Exact compacted memory seen by the router</span>
      <pre>${esc(run.active_memory)}</pre>
    </div>`;
}

function render() {
  renderControls();
  const run = activeRun();
  const family = activeFamily();
  renderStory(run, family);
  renderDebug(run);
  document.querySelector("#story-view").classList.toggle("hidden", state.mode !== "story");
  document.querySelector("#debug-view").classList.toggle("hidden", state.mode !== "debug");
  document.querySelectorAll("[data-mode]").forEach(button => button.classList.toggle("active", button.dataset.mode === state.mode));
}

async function boot() {
  const response = await fetch("/api/traces", { cache: "no-store" });
  if (!response.ok) throw new Error(`Trace API returned ${response.status}`);
  state.payload = await response.json();
  const trace = state.payload.trace;
  document.querySelector("#trace-stamp").innerHTML = `
    TRACE&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.status)}<br>
    MODEL&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.model)} · local<br>
    CALLS&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.measured_generation_calls)} measured<br>
    TOKENS&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc((trace.prompt_tokens + trace.completion_tokens).toLocaleString("en-HK"))}<br>
    API COST&nbsp;&nbsp;&nbsp; $${esc(trace.external_api_cost_usd.toFixed(2))}`;
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    render();
  }));
  render();
}

boot().catch(error => {
  document.querySelector("#story-view").innerHTML = `<p style="padding:24px;color:#ff7b72">Unable to load trace: ${esc(error.message)}</p>`;
});
