"use strict";

const $ = (id) => document.getElementById(id);

function leaf(scope) {
  const p = (scope || "").replace(/\/+$/, "").split("/").filter(Boolean);
  return p.length >= 2 ? p.slice(-2).join("/") : (p[p.length - 1] || scope || "");
}
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function pct(b, a) { return b ? Math.round((100 * (b - a)) / b) : 0; }
function countUp(node, to) {
  const dur = 700, t0 = performance.now();
  (function tick(now) {
    const p = Math.min(1, (now - t0) / dur);
    node.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(tick);
  })(t0);
}

// Plain-English "where" for a role scope.
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
  if ([...set].every((o) => o === "read" || o === "list")) return "read-only";
  return (ops || []).join(", ");
}

let CURRENT = null;

function render(d) {
  CURRENT = d;
  $("loading").classList.add("hidden");
  ["hero", "changes", "apply"].forEach((id) => $(id).classList.remove("hidden"));
  renderHero(d);
  renderChanges(d);
  $("apply-code").textContent = applyScript(d);
}

function renderHero(d) {
  const p = pct(d.blast_radius_before, d.blast_radius_after);
  countUp($("pct"), p);
  $("hero-sub").textContent =
    "This agent was granted far more than it used. Cinch keeps only what it needs.";
  requestAnimationFrame(() => {
    $("seg-removed").style.width = p + "%";
    $("seg-kept").style.width = (100 - p) + "%";
  });
}

function row(name, meta, badge) {
  const li = el("li", "row");
  li.appendChild(el("div", "name", esc(name) + (badge || "")));
  if (meta) li.appendChild(el("div", "meta", meta));
  return li;
}

function renderChanges(d) {
  const rem = $("remove-list"), keep = $("keep-list");
  rem.innerHTML = keep.innerHTML = "";

  // Reasons for removed roles, derived from findings.
  const reason = {};
  d.findings.forEach((f) => { if (f.role_name) reason[f.role_name] = f.kind === "unused_role" ? "never used" : "too broad"; });

  // REMOVE: broad roles + unused tools.
  d.remove.forEach((x) =>
    rem.appendChild(row(
      x.role_name,
      `had access to ${whereText(x.scope)}`,
      reason[x.role_name] ? `<span class="badge badge-reason">${reason[x.role_name]}</span>` : ""
    ))
  );
  d.tool_remove.forEach((x) =>
    rem.appendChild(row(x.name, "wired up but never called",
      `<span class="badge badge-tool">tool</span><span class="badge badge-reason">never used</span>`))
  );
  if (!rem.children.length) rem.appendChild(el("li", "empty-note", "Nothing to remove."));

  // KEEP: narrowed roles + kept tools.
  d.keep.forEach((k) =>
    keep.appendChild(row(k.role_name, `${opsText(k.covers_operations)} on ${whereText(k.scope)}`))
  );
  d.tool_keep.forEach((k) =>
    keep.appendChild(row(k.name, `${(k.keep_permissions || []).join(", ") || "—"}`,
      `<span class="badge badge-tool">tool</span>`))
  );
  if (!keep.children.length) keep.appendChild(el("li", "empty-note", "Nothing kept."));

  renderWhy(d);
}

function renderWhy(d) {
  const why = $("why");
  why.innerHTML = "";
  why.appendChild(el("h4", null, "Everything the agent actually did, from logs and traces"));
  if (!d.used.length && !d.used_tools.length) {
    why.appendChild(el("div", "muted", "No activity observed in the window."));
  }
  d.used.forEach((u) =>
    why.appendChild(el("div", "used-row",
      `<span class="op">${esc(u.operation)}</span> &times;${u.count} on <code>${esc(leaf(u.resource_id))}</code>`))
  );
  d.used_tools.forEach((u) =>
    why.appendChild(el("div", "used-row",
      `called <span class="op">${esc(u.name)}</span> &times;${u.count} <span class="muted">(${esc((u.permissions_used || []).join(", ") || "—")})</span>`))
  );
}

function applyScript(d) {
  return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + d.az_cli.join("\n") + "\n";
}

// ---- data ----
async function loadSample() {
  showLoading();
  try { render(await (await fetch("/api/sample")).json()); }
  catch { fail("Could not load the sample."); }
}
async function analyze(granted, used) {
  showLoading();
  try {
    const res = await fetch("/api/analyze", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ granted, used }),
    });
    render(await res.json());
  } catch { fail("Analysis failed. Check the JSON."); }
}
function showLoading() {
  $("loading").classList.remove("hidden");
  $("loading").textContent = "Analyzing…";
  ["hero", "changes", "apply"].forEach((id) => $(id).classList.add("hidden"));
}
function fail(m) { $("loading").classList.remove("hidden"); $("loading").textContent = m; }

const picked = { granted: null, used: null };
function readJson(input, key) {
  const f = input.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    try { picked[key] = JSON.parse(r.result); } catch { return fail("That file isn't valid JSON."); }
    if (picked.granted && picked.used) analyze(picked.granted, picked.used);
  };
  r.readAsText(f);
}
function download(name, text, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

// ---- wire up ----
$("btn-sample").addEventListener("click", loadSample);
$("file-granted").addEventListener("change", (e) => readJson(e.target, "granted"));
$("file-used").addEventListener("change", (e) => readJson(e.target, "used"));
$("why-toggle").addEventListener("click", () => {
  const w = $("why"), btn = $("why-toggle");
  const open = w.classList.toggle("hidden") === false;
  btn.textContent = open ? "Hide what the agent actually did ▴" : "Show what the agent actually did ▾";
});
$("btn-copy").addEventListener("click", async () => {
  if (!CURRENT) return;
  await navigator.clipboard.writeText(applyScript(CURRENT));
  const b = $("btn-copy"); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1300);
});
$("dl-apply").addEventListener("click", () => CURRENT && download("apply.sh", applyScript(CURRENT)));

loadSample();
