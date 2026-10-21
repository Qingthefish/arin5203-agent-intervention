const query = new URLSearchParams(window.location.search);
const state = {
  payload: null,
  family: query.get("family") || "held-y6",
  condition: query.get("condition") || "remove_action_critical",
  method: query.get("method") || "typed_card_retention",
  mode: query.get("mode") || "story",
  registry: query.get("proof") === "registry",
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

  document.querySelector("#registry-toggle").innerHTML = `
    <span>Proof source</span>
    <button class="${state.registry ? "" : "active"}" data-registry="off">Memory only</button>
    <button class="${state.registry ? "active" : ""}" data-registry="on">+ durable registry</button>`;

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
  document.querySelectorAll("[data-registry]").forEach(button => button.addEventListener("click", () => {
    state.registry = button.dataset.registry === "on";
    render();
  }));
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
  const overlay = run.durable_overlay;
  const finalDecision = state.registry ? overlay.decision : run.decision;
  const finalState = state.registry ? overlay.state : run.state;
  const finalLabel = state.registry ? overlay.decision_label : run.decision_label;
  const finalSummary = state.registry ? overlay.decision_summary : run.decision_summary;
  const routeCorrect = finalDecision === run.expected_decision;
  const changedByAudit = directDecision !== run.decision;
  const changedByRegistry = run.decision !== overlay.decision;
  const verdictText = routeCorrect ? "Safe route matches the oracle" : "Known failure boundary";
  const conditionCopy = run.condition === "remove_action_critical"
    ? `Compaction can no longer see the ${family.critical_fact}.`
    : run.condition === "remove_matched_noise"
      ? `Only equal-size irrelevant text disappeared; the ${family.critical_fact} remains visible.`
      : `Complete history still contains the ${family.critical_fact}.`;
  const outcomeTitle = finalState.harmful_mutation
    ? "A harmful change goes through"
    : finalState.mutation_applied
      ? "The verified change goes through"
      : "The tool call is paused";
  const routeVerb = finalDecision === "AUTO_EXECUTE" ? "executes" : finalDecision === "REQUEST_CONFIRMATION" ? "asks once" : "hands off";
  document.querySelector("#story-view").innerHTML = `
    <div class="story-opening">
      <article class="story-request">
        <span class="panel-label">A familiar agent request</span>
        <p class="request-text">“${esc(family.request)}”</p>
        <p class="story-rule"><strong>Control rule:</strong> ${esc(family.risk)}</p>
      </article>
      <article class="story-result ${finalState.harmful_mutation ? "danger" : ""}">
        <span class="panel-label">The next tool call</span>
        <div class="story-route ${routeClass(finalDecision)}">
          <strong>${esc(finalLabel)}</strong><span>The agent ${esc(routeVerb)}</span>
        </div>
        <p>${esc(outcomeTitle)}.</p>
        <div class="story-verdict ${routeCorrect ? "pass" : "fail"}">${esc(verdictText)}</div>
      </article>
    </div>
    <div class="story-causal">
      <article class="causal-step">
        <span class="step-number">01</span>
        <div>
          <span class="panel-label">Memory changes</span>
          <h3>${esc(run.condition_label)}</h3>
          <p>${esc(conditionCopy)}</p>
        </div>
      </article>
      <span class="causal-arrow">→</span>
      <article class="causal-step">
        <span class="step-number">02</span>
        <div>
          <span class="panel-label">Evidence is checked</span>
          <div class="compact-route">
            <span>${esc(decisionLabels[directDecision])}</span>
            <b>${changedByAudit ? "corrected to" : "verified as"}</b>
            <strong>${esc(run.decision_label)}</strong>
          </div>
          <p>${esc(run.method_label)} · ${esc(run.retained_card_ids.length)}/${esc(run.visible_card_ids.length)} visible proof cards retained</p>
        </div>
      </article>
      <span class="causal-arrow">→</span>
      <article class="causal-step ${finalState.harmful_mutation ? "danger" : ""}">
        <span class="step-number">03</span>
        <div>
          <span class="panel-label">External state reveals the cost</span>
          <h3>${esc(outcomeTitle)}</h3>
        <div class="state-diff">${stateRows({state: finalState})}</div>
        </div>
      </article>
    </div>
    <div class="story-lesson">
      <div>
        <span class="panel-label">The production lesson</span>
        <h2>Conversation memory is a cache—not the source of truth.</h2>
        <p>${state.registry && changedByRegistry ? "At the action boundary, the durable registry restores authoritative proof and prevents the mutation." : "A post-compaction audit can verify retained evidence, but it cannot recreate a hold that never reached active context."}</p>
      </div>
      <div class="source-comparison">
        <div class="source-route">
          <small>Memory only</small><strong class="${routeClass(run.decision)}">${esc(run.decision_label)}</strong>
        </div>
        <span>→</span>
        <div class="source-route emphasized">
          <small>+ durable registry</small><strong class="${routeClass(overlay.decision)}">${esc(overlay.decision_label)}</strong>
          <em>${overlay.new_card_ids.length ? `recovers ${esc(family.critical_fact)}` : "revalidates current proof"}</em>
        </div>
      </div>
    </div>`;
}

function renderTraceStamp() {
  const trace = state.payload.trace;
  const element = document.querySelector("#trace-stamp");
  if (state.mode === "story") {
    element.classList.add("compact");
    element.innerHTML = `<strong>FROZEN HELD-OUT TRACE</strong><span>${esc(trace.measured_generation_calls)} local calls · $${esc(trace.external_api_cost_usd.toFixed(2))} API cost</span>`;
    return;
  }
  element.classList.remove("compact");
  element.innerHTML = `
    TRACE&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.status)}<br>
    MODEL&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.model)} · local<br>
    CALLS&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc(trace.measured_generation_calls)} measured<br>
    TOKENS&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; ${esc((trace.prompt_tokens + trace.completion_tokens).toLocaleString("en-HK"))}<br>
    STORE GATE&nbsp; ${esc(trace.durable_gate_status.replace("PASS_DURABLE_PROOF_STORE_GATE", "PASS"))} · ${esc(trace.durable_gate_cases)} cases<br>
    API COST&nbsp;&nbsp;&nbsp; $${esc(trace.external_api_cost_usd.toFixed(2))}`;
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
      <p class="overlay-note">${state.registry ? esc(run.durable_overlay.label) : "Frozen memory-only trace"}</p>
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

function suiteCell(run) {
  const correct = run.decision === run.expected_decision;
  const harmful = run.state.harmful_mutation;
  const label = decisionLabels[run.decision];
  const detail = harmful ? "harmful mutation" : correct ? "matches oracle" : `expected ${decisionLabels[run.expected_decision]}`;
  return `<div class="suite-cell ${correct ? "pass" : "fail"} ${harmful ? "harmful" : ""}">
    <strong>${esc(label)}</strong><span>${esc(detail)}</span>
  </div>`;
}

function renderSuite() {
  const family = activeFamily();
  const runs = state.payload.runs.filter(item => item.family_id === state.family);
  const rows = state.payload.methods.map(method => {
    const methodRuns = state.payload.conditions.map(condition => runs.find(item =>
      item.method === method.id && item.condition === condition.id
    ));
    const correct = methodRuns.filter(item => item.route_correct).length;
    const harmful = methodRuns.filter(item => item.state.harmful_mutation).length;
    const meanPrecision = methodRuns.reduce((sum, item) => sum + (item.direct.proof_citation_precision ?? 0), 0) / methodRuns.length;
    return `<div class="suite-row">
      <div class="suite-method">
        <strong>${esc(method.label)}</strong>
        <span>${correct}/3 routes · ${harmful} harmful · ${esc(pct(meanPrecision))} citation precision</span>
      </div>
      ${methodRuns.map(suiteCell).join("")}
    </div>`;
  }).join("");
  const selected = runs.find(item => item.method === state.method && item.condition === state.condition);
  const registry = selected.durable_overlay;
  document.querySelector("#suite-view").innerHTML = `
    <div class="suite-head">
      <div>
        <span class="panel-label">Matched memory regression suite · frozen replay</span>
        <h2>${esc(family.label)}: change one fact, inspect the next action</h2>
        <p>${esc(family.risk)}</p>
      </div>
      <div class="suite-score ${selected.route_correct ? "pass" : "fail"}">
        <strong>${runs.filter(item => item.route_correct).length}/${runs.length}</strong>
        <span>audited routes match oracle</span>
      </div>
    </div>
    <div class="suite-table">
      <div class="suite-row suite-labels">
        <div>Memory strategy</div>
        ${state.payload.conditions.map(item => `<div>${esc(item.label)}</div>`).join("")}
      </div>
      ${rows}
    </div>
    <div class="suite-boundary">
      <div>
        <span class="panel-label">Selected architecture check</span>
        <strong>${esc(selected.method_label)} · ${esc(selected.condition_label)}</strong>
        <p>Memory says <b>${esc(selected.decision_label)}</b>. The durable registry says <b>${esc(registry.decision_label)}</b>${registry.new_card_ids.length ? ` after recovering ${esc(registry.new_card_ids.join(", "))}` : " with no new decisive proof"}.</p>
      </div>
      <div class="boundary-flow">
        <span class="route-chip ${routeClass(selected.decision)}"><small>Memory</small><strong>${esc(selected.decision_label)}</strong></span>
        <span>→</span>
        <span class="route-chip ${routeClass(registry.decision)}"><small>Registry</small><strong>${esc(registry.decision_label)}</strong></span>
      </div>
    </div>`;
}

function exportCurrentRun() {
  const run = activeRun();
  const payload = {
    exported_at: new Date().toISOString(),
    evidence_source: "typed_exact_budget_heldout_qwen_v1",
    architecture_overlay: "durable_proof_store_deterministic_v1",
    family: activeFamily(),
    run,
  };
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${run.case_id}-${run.method}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function normalizeState() {
  const familyIds = new Set(state.payload.families.map(item => item.family_id));
  const conditionIds = new Set(state.payload.conditions.map(item => item.id));
  const methodIds = new Set(state.payload.methods.map(item => item.id));
  if (!familyIds.has(state.family)) state.family = state.payload.families[0].family_id;
  if (!conditionIds.has(state.condition)) state.condition = state.payload.conditions[0].id;
  if (!methodIds.has(state.method)) state.method = state.payload.methods[0].id;
  if (!["story", "suite", "debug"].includes(state.mode)) state.mode = "story";
}

function syncDeepLink() {
  const params = new URLSearchParams({
    family: state.family,
    condition: state.condition,
    method: state.method,
    mode: state.mode,
    proof: state.registry ? "registry" : "memory",
  });
  window.history.replaceState(null, "", `?${params.toString()}`);
}

function render() {
  document.body.dataset.mode = state.mode;
  renderControls();
  const run = activeRun();
  const family = activeFamily();
  renderStory(run, family);
  renderSuite();
  renderDebug(run);
  document.querySelector("#story-view").classList.toggle("hidden", state.mode !== "story");
  document.querySelector("#suite-view").classList.toggle("hidden", state.mode !== "suite");
  document.querySelector("#debug-view").classList.toggle("hidden", state.mode !== "debug");
  document.querySelectorAll("[data-mode]").forEach(button => button.classList.toggle("active", button.dataset.mode === state.mode));
  renderTraceStamp();
  syncDeepLink();
}

async function boot() {
  const response = await fetch("/api/traces", { cache: "no-store" });
  if (!response.ok) throw new Error(`Trace API returned ${response.status}`);
  state.payload = await response.json();
  normalizeState();
  document.querySelectorAll("[data-mode]").forEach(button => button.addEventListener("click", () => {
    state.mode = button.dataset.mode;
    render();
  }));
  document.querySelector("#export-run").addEventListener("click", exportCurrentRun);
  render();
}

boot().catch(error => {
  document.querySelector("#story-view").innerHTML = `<p style="padding:24px;color:#ff7b72">Unable to load trace: ${esc(error.message)}</p>`;
});
