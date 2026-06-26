"use strict";

// --------------------------------------------------------------------------- //
// Helpers
// --------------------------------------------------------------------------- //
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function leaf(scope) {
  const p = (scope || "").replace(/\/+$/, "").split("/").filter(Boolean);
  return p.length >= 2 ? p.slice(-2).join("/") : (p[p.length - 1] || scope || "");
}
function lastSeg(scope) {
  const p = (scope || "").replace(/\/+$/, "").split("/").filter(Boolean);
  return p[p.length - 1] || "";
}
function whereText(scope) {
  const s = (scope || "").toLowerCase();
  if (s.includes("/containers/")) return `one container (${lastSeg(scope)})`;
  if (s.includes("/secrets/")) return `one secret (${lastSeg(scope)})`;
  if (s.includes("/storageaccounts/")) return "an entire storage account";
  if (s.includes("/vaults/")) return "an entire key vault";
  return leaf(scope);
}
function opsText(ops) {
  const set = new Set(ops || []);
  if (set.size && [...set].every((o) => o === "read" || o === "list")) return "read-only";
  return (ops || []).join(", ");
}
function pct(b, a) { return b ? Math.round((100 * (b - a)) / b) : 0; }
function countUp(node, to) {
  const dur = 1600, t0 = performance.now();
  (function tick(now) {
    const p = Math.min(1, (now - t0) / dur);
    node.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

let CURRENT = null;
let LIVE = false;
let SELECTED = null;  // { id, name } of the agent being scanned

// --------------------------------------------------------------------------- //
// Live console (the "analyze" stream)
// --------------------------------------------------------------------------- //
function logRaw(html, cls) {
  const c = $("console");
  c.appendChild(el("div", "cline" + (cls ? " " + cls : ""), html));
  c.scrollTop = c.scrollHeight;
}
async function logCmd(t) { logRaw(`<span class="c-prompt">$</span> ${esc(t)}`, "cmd"); await sleep(320); }
async function logStep(t) { logRaw(`<span class="c-arrow">▸</span> ${esc(t)}`, "step"); await sleep(280); }
async function logOk(t, indent) { logRaw(`<span class="c-ok">✓</span> ${esc(t)}`, "ok" + (indent ? " indent" : "")); await sleep(150); }

function hideAll() {
  ["landing", "loading", "console", "stage"].forEach((id) => $(id).classList.add("hidden"));
}

async function loadLive() {
  LIVE = true;
  hideAll();
  $("btn-rescan").classList.remove("hidden");
  const c = $("console");
  c.classList.remove("hidden");
  c.innerHTML = "";
  const q = SELECTED && SELECTED.id ? `?principal=${encodeURIComponent(SELECTED.id)}` : "";
  const fetchP = fetch("/api/analyze-live" + q)
    .then((r) => r.json())
    .catch(() => ({ error: "Scan failed (is the server running with the Azure env vars?)." }));

  const who = SELECTED && SELECTED.name ? `  # agent: ${SELECTED.name}` : "";
  await logCmd("cinch analyze --source diagnostics" + who);
  await logStep("authenticating to Azure (DefaultAzureCredential)");
  await logOk("signed in", true);
  await logStep("reading RBAC role assignments on the agent identity");

  const d = await fetchP;
  if (d.error) { LIVE = false; return fail(d.error); }

  for (const g of d.granted) await logOk(`${g.role_name}  →  ${leaf(g.scope)}`, true);
  await logStep("querying StorageBlobLogs + Key Vault AuditEvent (data-plane usage)");
  for (const u of d.used) await logOk(`${u.operation} ×${u.count}  →  ${leaf(u.resource_id)}`, true);
  const ops = d.used.reduce((a, u) => a + (u.count || 0), 0);
  await logStep("scan complete");
  await logOk(`${d.granted.length} grant(s) · ${ops} operation(s) actually used`, true);
  await sleep(550);
  showBefore(d);
}

function fail(m) {
  hideAll();
  $("loading").classList.remove("hidden");
  $("loading").textContent = m;
}

// --------------------------------------------------------------------------- //
// Phase 1 — the "before": granted access as a ledger of op chips
// --------------------------------------------------------------------------- //
function showBefore(d) {
  CURRENT = d;
  hideAll();
  $("stage").classList.remove("hidden");
  $("apply").classList.add("hidden");
  $("btn-rightsize").classList.remove("hidden");
  $("perms-title").textContent = "granted access";

  $("hero-eyebrow").textContent = "granted access";
  $("hero-num").classList.add("hidden");
  $("hero-raw").textContent = "";
  $("hero-title").textContent = "More access than it uses";
  const n = d.granted.length + d.granted_tools.length;
  $("hero-sub").textContent =
    `${n} access grant${n !== 1 ? "s" : ""} in Azure. Cinch keeps only what it actually exercises.`;

  renderPermsBefore(d);
}

// Which ops survive for a granted role = the narrowed role that replaces it.
function keepForRole(d, g) {
  const gs = g.scope.toLowerCase().replace(/\/+$/, "");
  return d.keep.find((k) => k.scope.toLowerCase().replace(/\/+$/, "").startsWith(gs)) || null;
}

function renderPermsBefore(d) {
  const ul = $("perms");
  ul.innerHTML = "";

  d.granted.forEach((g) => {
    const keep = keepForRole(d, g);
    const keptSet = new Set(keep ? keep.covers_operations : []);
    const li = el("li", "prow");
    if (!keep) li.dataset.removed = "1";

    const top = el("div", "prow-top");
    top.appendChild(el("span", "prole", esc(g.role_name)));
    top.appendChild(el("span", "pscope", "on " + whereText(g.scope)));
    if (!keep) top.appendChild(el("span", "badge badge-reason", "never used"));
    li.appendChild(top);

    const chips = el("div", "pchips");
    (g.covers || []).forEach((op) => {
      const chip = el("span", "chip", esc(op));
      chip.dataset.keep = keptSet.has(op) ? "1" : "0";
      chips.appendChild(chip);
    });
    li.appendChild(chips);

    if (keep) {
      li.appendChild(
        el("div", "pkeep",
          `→ ${esc(keep.role_name)} · ${esc(opsText(keep.covers_operations))} on ${esc(whereText(keep.scope))}`)
      );
    }
    ul.appendChild(li);
  });

  d.granted_tools.forEach((t) => {
    const keep = (d.tool_keep || []).find((k) => k.name === t.name);
    const keptSet = new Set(keep ? keep.keep_permissions : []);
    const li = el("li", "prow");
    if (!keep) li.dataset.removed = "1";

    const top = el("div", "prow-top");
    top.appendChild(el("span", "prole", esc(t.name)));
    top.appendChild(el("span", "pscope", "tool"));
    if (!keep) top.appendChild(el("span", "badge badge-reason", "never used"));
    li.appendChild(top);

    const chips = el("div", "pchips");
    (t.permissions || []).forEach((p) => {
      const chip = el("span", "chip", esc(p));
      chip.dataset.keep = keptSet.has(p) ? "1" : "0";
      chips.appendChild(chip);
    });
    li.appendChild(chips);
    ul.appendChild(li);
  });
}

// --------------------------------------------------------------------------- //
// Right-size — redline the unused, then settle into the "after"
// --------------------------------------------------------------------------- //
async function rightSize() {
  $("btn-rightsize").classList.add("hidden");
  $("perms-title").textContent = "redlining unused access";
  // Mirror this phase in the backend terminal (logs the diff + az preview).
  fetch("/api/rightsize", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ principal: SELECTED ? SELECTED.id : null }),
  }).catch(() => {});

  const rows = [...$("perms").children];
  for (const li of rows) {
    if (li.dataset.removed === "1") {
      li.classList.add("removing");
    } else {
      li.querySelectorAll('.chip[data-keep="1"]').forEach((c) => c.classList.add("kept"));
      li.querySelectorAll('.chip[data-keep="0"]').forEach((c) => c.classList.add("cut"));
      const cap = li.querySelector(".pkeep");
      if (cap) cap.classList.add("show");
    }
    await sleep(520);
  }
  await sleep(900);
  $("perms").querySelectorAll(".chip.cut").forEach((c) => c.classList.add("gone"));
  $("perms").querySelectorAll(".removing").forEach((li) => li.classList.add("gone"));
  await sleep(950);

  $("perms-title").textContent = "right-sized result";
  renderHeroAfter(CURRENT);
  showApply(CURRENT);
}

function isClean(d) {
  return d.remove.length + d.tool_remove.length === 0 &&
    d.findings.length + d.tool_findings.length === 0;
}

function renderHeroAfter(d) {
  $("hero-num").classList.remove("hidden");
  if (isClean(d)) {
    $("hero-eyebrow").textContent = "result";
    $("pct").textContent = "✓";
    $("pct-unit").classList.add("hidden");
    $("hero-raw").textContent = "";
    $("hero-title").textContent = "Least privilege";
    $("hero-sub").textContent = "This agent now holds only the access it actually uses.";
    return;
  }
  $("hero-eyebrow").textContent = "access removed";
  $("pct-unit").classList.remove("hidden");
  countUp($("pct"), pct(d.blast_radius_before, d.blast_radius_after));
  $("hero-raw").textContent = `exposure ${d.blast_radius_before} → ${d.blast_radius_after}`;
  const k = d.keep.length;
  if (k === 0) {
    $("hero-title").textContent = "Dormant — no access needed";
    $("hero-sub").textContent = "This agent never used any of its access. Cinch recommends removing all of it.";
  } else {
    $("hero-title").textContent = "Tightened to least privilege";
    $("hero-sub").textContent = `Cut to the ${k} resource${k !== 1 ? "s" : ""} it actually uses.`;
  }
}

function showApply(d) {
  $("apply-code").textContent = applyScript(d);
  $("apply-code").style.display = d.az_cli.length ? "" : "none";
  const hasChanges = d.remove.length + d.tool_remove.length > 0;
  $("btn-apply-azure").classList.toggle("hidden", !(LIVE && hasChanges));
  $("apply").classList.toggle("hidden", !d.az_cli.length && isClean(d));
}

// Static "after" (used after Apply, no animation): the surviving access, in green.
function renderPermsAfter(d) {
  const ul = $("perms");
  ul.innerHTML = "";
  const add = (name, scopeText, ops, tool) => {
    const li = el("li", "prow");
    const top = el("div", "prow-top");
    top.appendChild(el("span", "prole", esc(name)));
    top.appendChild(el("span", "pscope", scopeText));
    if (tool) top.appendChild(el("span", "badge badge-tool", "tool"));
    li.appendChild(top);
    const chips = el("div", "pchips");
    (ops || []).forEach((op) => chips.appendChild(el("span", "chip kept", esc(op))));
    li.appendChild(chips);
    ul.appendChild(li);
  };
  d.keep.forEach((k) => add(k.role_name, "on " + whereText(k.scope), k.covers_operations, false));
  (d.tool_keep || []).forEach((k) => add(k.name, "tool", k.keep_permissions, true));
  if (!ul.children.length) ul.appendChild(el("li", "prow", "<span class='pscope'>No standing access.</span>"));
}

function showAfterStatic(d) {
  CURRENT = d;
  hideAll();
  $("stage").classList.remove("hidden");
  $("btn-rightsize").classList.add("hidden");
  $("perms-title").textContent = "least-privilege access";
  renderHeroAfter(d);
  renderPermsAfter(d);
  showApply(d);
}

// --------------------------------------------------------------------------- //
// Apply to Azure
// --------------------------------------------------------------------------- //
async function applyAzure() {
  if (!confirm("Apply least privilege to the live agent identity?\n\nThis creates the narrow roles and deletes the broad ones in Azure.")) return;
  const btn = $("btn-apply-azure"), status = $("apply-status");
  btn.disabled = true; btn.textContent = "Applying…";
  status.classList.remove("hidden"); status.textContent = "Running az commands against Azure…";
  const pidBody = JSON.stringify({ principal: SELECTED ? SELECTED.id : null });
  const q = SELECTED && SELECTED.id ? `?principal=${encodeURIComponent(SELECTED.id)}` : "";
  try {
    const j = await (await fetch("/api/apply", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: pidBody,
    })).json();
    if (j.error) { status.textContent = "Apply failed: " + j.error; }
    else {
      const d = await (await fetch("/api/analyze-live" + q)).json();
      showAfterStatic(d);
      $("apply-status").classList.remove("hidden");
      $("apply-status").textContent = `✓ Applied ${j.count} change(s). The agent is now least privilege.`;
    }
  } catch (e) {
    status.textContent = "Apply failed: " + e;
  } finally {
    btn.disabled = false; btn.textContent = "Apply to Azure";
  }
}

function applyScript(d) {
  return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + d.az_cli.join("\n") + "\n";
}
function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

// --------------------------------------------------------------------------- //
// Agent roster (landing)
// --------------------------------------------------------------------------- //
async function loadAgents() {
  hideAll();
  $("landing").classList.remove("hidden");
  $("btn-rescan").classList.add("hidden");
  const list = $("agent-list");
  list.innerHTML = "";
  let agents = [];
  try {
    agents = (await (await fetch("/api/agents")).json()).agents || [];
  } catch { /* fall through to empty */ }

  if (!agents.length) {
    // No roster configured — offer a single direct scan.
    const b = el("button", "btn btn-primary btn-lg", "Scan this agent");
    b.addEventListener("click", () => { SELECTED = null; loadLive(); });
    list.appendChild(b);
    return;
  }
  agents.forEach((a) => {
    const card = el("button", "agent-card");
    card.innerHTML =
      `<div class="agent-ico">⌖</div>` +
      `<div class="agent-meta"><div class="agent-name">${esc(a.name)}</div>` +
      `<div class="agent-role">${esc(a.role || "AI agent")}</div></div>` +
      `<div class="agent-go">Scan →</div>`;
    card.addEventListener("click", () => { SELECTED = { id: a.id, name: a.name }; loadLive(); });
    list.appendChild(card);
  });
}

// --------------------------------------------------------------------------- //
// Wire up
// --------------------------------------------------------------------------- //
$("btn-rescan").addEventListener("click", loadAgents);
$("btn-rightsize").addEventListener("click", rightSize);
$("btn-apply-azure").addEventListener("click", applyAzure);
$("btn-copy").addEventListener("click", async () => {
  if (!CURRENT) return;
  await navigator.clipboard.writeText(applyScript(CURRENT));
  const b = $("btn-copy"); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1300);
});
$("dl-apply").addEventListener("click", () => CURRENT && download("apply.sh", applyScript(CURRENT)));

loadAgents();
