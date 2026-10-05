const state = { payload: null, domain: "mas_travel", decision: "AUTO_EXECUTE", mode: "story" };

const routeOrder = ["AUTO_EXECUTE", "REQUEST_CONFIRMATION", "HANDOFF"];
const statusLabels = {
  authority_status: "Authority",
  clearance_status: "Clearance",
  hold_status: "Active hold",
  delegation_status: "Delegation",
  recovery_status: "Recovery",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function activeScenario() {
  return state.payload.scenarios.find(
    item => item.domain === state.domain && item.decision === state.decision,
  );
}

function statusClass(value) {
  if (["MISSING", "BLOCKED"].includes(value)) return value.toLowerCase();
  if (value === "REPAIRABLE_GAP") return "gap";
  return "";
}

function routeClass(decision) {
  if (decision === "REQUEST_CONFIRMATION") return "confirm";
  if (decision === "HANDOFF") return "handoff";
  return "execute";
}

function renderControls() {
  const domains = [...new Map(state.payload.scenarios.map(item => [item.domain, item])).values()];
  document.querySelector("#domain-tabs").innerHTML = domains.map(item => `
    <button class="${item.domain === state.domain ? "active" : ""}" data-domain="${esc(item.domain)}">
      ${esc(item.domain_label)}
    </button>`).join("");

  const domainCases = state.payload.scenarios.filter(item => item.domain === state.domain);
  document.querySelector("#condition-strip").innerHTML = routeOrder.map(decision => {
    const item = domainCases.find(candidate => candidate.decision === decision);
    return `<button class="${decision === state.decision ? "active" : ""}" data-decision="${decision}">
      ${esc(item.condition)} · ${esc(item.decision_label)}
    </button>`;
  }).join("");

  document.querySelectorAll("[data-domain]").forEach(button => button.addEventListener("click", () => {
    state.domain = button.dataset.domain;
    render();
  }));
  document.querySelectorAll("[data-decision]").forEach(button => button.addEventListener("click", () => {
    state.decision = button.dataset.decision;
    render();
  }));
}

function cardRows(scenario, compact = false) {
  const decisive = new Set(scenario.result.decisive_card_ids);
  const ignored = new Set(scenario.result.ignored_card_ids);
  const cards = scenario.cards;
  if (compact) {
    return cards.map(card => `
      <div class="mini-card ${decisive.has(card.card_id) ? "decisive" : ""} ${ignored.has(card.card_id) ? "ignored" : ""}">
        <span>${esc(card.kind)}</span><span>${esc(card.card_id)}</span>
      </div>`).join("");
  }
  return cards.map(card => `
    <tr class="${ignored.has(card.card_id) ? "ignored" : ""}">
      <td><code>${esc(card.card_id)}</code><br><small>${esc(card.source_event_ids.join(", "))}</small></td>
      <td><span class="pill">${esc(card.kind)}</span></td>
      <td>${esc(card.issuer_id)}</td>
      <td>${esc(card.subject_id)}</td>
      <td>${esc(card.scope.map(pair => pair.join("=")).join(" · "))}</td>
      <td>${decisive.has(card.card_id) ? "Used" : ignored.has(card.card_id) ? "Ignored" : "Supporting"}</td>
    </tr>`).join("");
}

function renderStory(scenario) {
  const blocked = !scenario.mutation_allowed;
  document.querySelector("#story-view").innerHTML = `
    <div class="story-top">
      <article class="request-panel">
        <span class="panel-label">${esc(scenario.eyebrow)} · user request</span>
        <p class="request-text">“${esc(scenario.request)}”</p>
        <p class="risk-note">${esc(scenario.risk)}</p>
      </article>
      <article class="decision-panel">
        <span class="panel-label">Pre-action gate</span>
        <div class="route ${routeClass(scenario.decision)}"><span class="route-dot"></span><strong>${esc(scenario.decision_label)}</strong></div>
        <p>${esc(scenario.decision_summary)}</p>
        <p><code>${esc(scenario.case_id)}</code></p>
      </article>
    </div>
    <div class="journey">
      <article class="stage">
        <span class="panel-label">01 · long trajectory</span>
        <h3>Memory accumulates</h3>
        <p>Requests, tools, policy checks and routine logs compete for the same context window.</p>
        <div class="memory-stack">
          <span class="memory-line"></span><span class="memory-line"></span><span class="memory-line critical"></span><span class="memory-line"></span><span class="memory-line"></span>
        </div>
      </article>
      <div class="arrow">→</div>
      <article class="stage">
        <span class="panel-label">02 · retained proof</span>
        <h3>Compacted memory becomes evidence</h3>
        <div class="memory-stack">${cardRows(scenario, true)}</div>
      </article>
      <div class="arrow">→</div>
      <article class="stage">
        <span class="panel-label">03 · external state</span>
        <h3>${blocked ? "Mutation blocked" : "Mutation permitted"}</h3>
        <div class="state-diff">
          <div class="state-line">− ${esc(scenario.state_before)}</div>
          <div class="state-line ${blocked ? "blocked" : "after"}">+ ${esc(scenario.state_after)}${blocked ? " · no state change" : ""}</div>
        </div>
        <p>${blocked ? "The agent pauses before the tool call." : "Only the verified route can reach the tool."}</p>
      </article>
    </div>`;
}

function renderDebug(scenario) {
  const obligations = Object.entries(statusLabels).map(([key, label]) => {
    const value = scenario.result[key];
    return `<div class="obligation"><span>${esc(label)}</span><span class="status ${statusClass(value)}">${esc(value)}</span></div>`;
  }).join("");
  document.querySelector("#debug-view").innerHTML = `
    <div class="debug-head">
      <span class="panel-label">Runtime proof inspection</span>
      <h2>${esc(scenario.action.operation)} → ${esc(scenario.action.target_id)}</h2>
      <p>Actor ${esc(scenario.action.actor_id)} · effective ${esc(scenario.action.effective_at)}</p>
    </div>
    <div class="debug-grid">
      <aside class="obligations">
        <span class="panel-label">Proof obligations</span>
        ${obligations}
        <div class="obligation"><span>Final route</span><span class="status ${routeClass(scenario.decision)}">${esc(scenario.decision_label.toUpperCase())}</span></div>
      </aside>
      <div class="card-table">
        <table>
          <thead><tr><th>Card / source</th><th>Type</th><th>Issuer</th><th>Subject</th><th>Scope</th><th>Verdict</th></tr></thead>
          <tbody>${cardRows(scenario)}</tbody>
        </table>
      </div>
    </div>`;
}

function render() {
  renderControls();
  const scenario = activeScenario();
  renderStory(scenario);
  renderDebug(scenario);
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
    TRACE STATUS&nbsp; ${esc(trace.status)}<br>
    COMMIT&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.git_commit.slice(0, 9))}<br>
    MODEL CALLS&nbsp;&nbsp; 0 · deterministic<br>
    API COST&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; $${esc(trace.external_api_cost_usd.toFixed(2))}`;
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    render();
  }));
  render();
}

boot().catch(error => {
  document.querySelector("#story-view").innerHTML = `<p style="padding:24px;color:#ff7b72">Unable to load trace: ${esc(error.message)}</p>`;
});
