"""Tiny Flask server behind the Cinch dashboard.

The analysis is computed by the SAME deterministic engine the CLI uses
(``alp.recommend``), so the web UI and the command line never diverge. The server
just serves the static ``web/`` dashboard and returns the analysis as JSON; all
rendering happens client-side in HTML/CSS/JS.

Run:
    pip install -e ".[web]"
    python server.py
    # open http://127.0.0.1:5000
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).parent / "src"))

from alp.cli import _find, _load_granted, _load_used  # noqa: E402
from alp.diff import covered_operations  # noqa: E402
from alp.models import (  # noqa: E402
    GrantedRole,
    GrantedTool,
    UsedOperation,
    UsedTool,
)
from alp.recommend import recommend  # noqa: E402
from alp import auditlog as A  # noqa: E402

log = logging.getLogger("cinch")

WEB = Path(__file__).parent / "web"
app = Flask(__name__, static_folder=str(WEB), static_url_path="")

# Roster of agent identities to scan. The first is the env-configured live demo
# agent (active, with real usage); the others are additional real identities.
# Each entry: id (principal/object id), name, role (one-line description).
def _roster():
    primary = os.environ.get("ALP_PRINCIPAL_ID", "")
    roster = []
    if primary:
        roster.append({
            "id": primary,
            "name": os.environ.get("ALP_AGENT_NAME") or "agent",
            "role": os.environ.get("ALP_AGENT_ROLE") or "AI agent",
        })
    extra = os.environ.get("ALP_AGENTS", "")  # "name:pid:role|name:pid:role"
    for chunk in [c for c in extra.split("|") if c.strip()]:
        parts = chunk.split(":", 2)
        if len(parts) >= 2:
            roster.append({
                "name": parts[0].strip(),
                "id": parts[1].strip(),
                "role": parts[2].strip() if len(parts) > 2 else "AI agent",
            })
    return roster


def _agent_name(pid: str) -> str:
    for a in _roster():
        if a["id"] == pid:
            return a["name"]
    return pid[:8]


# Cache the last scan so /api/rightsize logs the diff without re-hitting Azure.
LAST_SCAN: dict = {}


def _payload(principal, granted, used, gtools, utools):
    """Run the engine and shape a single JSON the dashboard can render."""
    result = recommend(principal, granted, used, granted_tools=gtools, used_tools=utools)
    return {
        "principal": principal,
        "blast_radius_before": result.blast_radius_before,
        "blast_radius_after": result.blast_radius_after,
        "tool_surface_before": result.tool_surface_before,
        "tool_surface_after": result.tool_surface_after,
        "granted": [
            {
                "role_name": g.role_name,
                "scope": g.scope,
                "service": g.service,
                "covers": sorted(covered_operations(g)),
            }
            for g in granted
        ],
        "used": [
            {
                "operation": u.operation,
                "count": u.count,
                "resource_id": u.resource_id,
                "service": u.service,
            }
            for u in used
        ],
        "keep": [
            {
                "role_name": k.role_name,
                "scope": k.scope,
                "covers_operations": list(k.covers_operations),
            }
            for k in result.keep
        ],
        "remove": [{"role_name": r.role_name, "scope": r.scope} for r in result.remove],
        "findings": [f.to_dict() for f in result.findings],
        "granted_tools": [
            {"name": t.name, "kind": t.kind, "permissions": t.permissions} for t in gtools
        ],
        "used_tools": [
            {"name": t.name, "permissions_used": t.permissions_used, "count": t.count}
            for t in utools
        ],
        "tool_keep": [t.to_dict() for t in result.tool_keep],
        "tool_remove": [{"name": t.name, "kind": t.kind} for t in result.tool_remove],
        "tool_findings": [f.to_dict() for f in result.tool_findings],
        "tool_guidance": list(result.tool_guidance),
        "az_cli": list(result.az_cli),
        "report": result.report,
        "recommendations": result.to_dict(),
    }


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/api/sample")
def api_sample():
    """Analyze the bundled sample (the default demo)."""
    g = _find("samples/granted_sample.json")
    u = _find("samples/usage_sample.json")
    principal, granted, gtools = _load_granted(g)
    used, utools = _load_used(u)
    return jsonify(_payload(principal, granted, used, gtools, utools))


@app.post("/api/analyze")
def api_analyze():
    """Analyze uploaded granted/used JSON (e.g. a run's live_granted/live_used)."""
    body = request.get_json(force=True) or {}
    gdata = body.get("granted", {}) or {}
    udata = body.get("used", {}) or {}
    principal = gdata.get("principal_id", "")
    granted = [GrantedRole.from_dict(d) for d in gdata.get("granted", [])]
    gtools = [GrantedTool.from_dict(d) for d in gdata.get("granted_tools", [])]
    used = [UsedOperation.from_dict(d) for d in udata.get("used", [])]
    utools = [UsedTool.from_dict(d) for d in udata.get("used_tools", [])]
    return jsonify(_payload(principal, granted, used, gtools, utools))


def _live_inputs(principal_id: str | None = None):
    """Pull the live granted RBAC + used operations from Azure, driven by env.

    ``principal_id`` overrides the env default (so a selected roster agent is
    scanned). Returns (principal, granted, used) or raises ValueError.
    """
    sub = os.environ.get("ALP_SUBSCRIPTION_ID")
    pid = principal_id or os.environ.get("ALP_PRINCIPAL_ID")
    ws = os.environ.get("ALP_WORKSPACE_ID")
    rg = os.environ.get("ALP_RESOURCE_GROUP") or os.environ.get("ALP_DEMO_RG")
    look = int(os.environ.get("ALP_LOOKBACK_DAYS", "1"))
    missing = [
        name
        for name, val in [
            ("ALP_SUBSCRIPTION_ID", sub),
            ("ALP_PRINCIPAL_ID", pid),
            ("ALP_WORKSPACE_ID", ws),
            ("ALP_RESOURCE_GROUP/ALP_DEMO_RG", rg),
        ]
        if not val
    ]
    if missing:
        raise ValueError("Set these env vars before starting the server: " + ", ".join(missing))

    from alp.dataplane import collect_dataplane
    from alp.granted import collect_granted

    granted = collect_granted(sub, pid)
    used = collect_dataplane(ws, pid, sub, rg, look)
    return pid, granted, used


@app.get("/api/agents")
def api_agents():
    """The roster of agent identities available to scan."""
    return jsonify({"agents": _roster()})


@app.get("/api/analyze-live")
def api_analyze_live():
    """SCAN the agent: read real RBAC + real data-plane usage. Logs the scan only
    (the right-sizing is a separate phase, so the terminal doesn't spoil it)."""
    pid = request.args.get("principal") or os.environ.get("ALP_PRINCIPAL_ID", "")
    name = _agent_name(pid)
    A.section("SCAN", name)
    t0 = time.time()
    try:
        pid, granted, used = _live_inputs(pid)
    except ValueError as e:
        log.warning("config error: %s", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001 - surface Azure errors to the UI
        log.exception("scan failed")
        return jsonify({"error": f"Scan failed: {e}"}), 500
    ops = sum(u.count for u in used)
    A.result(f"  scan complete: {len(granted)} grants, {ops} operations used  "
             f"({time.time() - t0:.1f}s)")
    LAST_SCAN[pid] = (pid, granted, used)
    LAST_SCAN["_last"] = pid
    return jsonify(_payload(pid, granted, used, [], []))


@app.post("/api/rightsize")
def api_rightsize():
    """Log the RIGHT-SIZE phase (diff + recommendation) for the terminal proof.

    Uses the cached scan so it's instant and doesn't re-hit Azure. The browser
    already has the data; this exists so the CLI mirrors the UI's phases.
    """
    body = request.get_json(silent=True) or {}
    pid = body.get("principal") or LAST_SCAN.get("_last", "")
    cached = LAST_SCAN.get(pid)
    if not cached:
        try:
            cached = _live_inputs(pid or None)
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e)}), 400
    pid, granted, used = cached
    result = recommend(pid, granted, used)
    A.section("RIGHT-SIZE", _agent_name(pid))
    for k in result.keep:
        A.keep(k.role_name, k.scope.split("/")[-1], ", ".join(k.covers_operations))
    for r in result.remove:
        A.cut(r.role_name, r.scope.split("/")[-1])
    pctt = 0
    if result.blast_radius_before:
        pctt = round(100 * (result.blast_radius_before - result.blast_radius_after)
                     / result.blast_radius_before)
    A.result(f"  exposure {result.blast_radius_before} -> {result.blast_radius_after} "
             f"({pctt}% smaller) · {len(result.az_cli)} az command(s) generated")
    return jsonify({"ok": True})


@app.post("/api/apply")
def api_apply():
    """Apply the least-privilege recommendation to the live identity, running the
    generated ``az`` commands. Demo-grade: a real product would emit a reviewable
    PR / Bicep instead of executing directly."""
    body = request.get_json(silent=True) or {}
    pid_arg = body.get("principal")
    try:
        pid, granted, used = _live_inputs(pid_arg)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Apply prep failed: {e}"}), 500

    result = recommend(pid, granted, used)
    A.section("APPLY", _agent_name(pid))
    applied = []
    for cmd in result.az_cli:
        A.cmd(cmd if len(cmd) < 110 else cmd[:107] + "...")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        ok = proc.returncode == 0
        verb = "created" if " create " in cmd else "deleted"
        role = cmd.split('--role "')[1].split('"')[0] if '--role "' in cmd else "?"
        A.cmd_result(ok, f"{verb} {role}" if ok else (proc.stderr or "").strip()[:120])
        applied.append({"cmd": cmd, "ok": ok, "err": (proc.stderr or "").strip()[:300]})
    LAST_SCAN.pop(pid, None)  # state changed; force a fresh scan next time
    A.result(f"  {sum(a['ok'] for a in applied)}/{len(applied)} applied · "
             f"agent is now least privilege")
    return jsonify({"applied": applied, "count": len(applied),
                    "ok": all(a["ok"] for a in applied)})


if __name__ == "__main__":
    # Force UTF-8 stdout so box-drawing + check glyphs render on Windows consoles
    # (default cp1252 can't encode them and would crash logging).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )
    # Quiet framework + SDK noise so the real backend log stands out clearly.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy",
                  "azure.identity", "urllib3", "msal"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    banner = r"""
   ____ _            _
  / ___(_)_ __   ___| |__     CINCH  -  least privilege for AI agents
 | |   | | '_ \ / __| '_ \    live backend  -  every Azure call is real
 | |___| | | | | (__| | | |
  \____|_|_| |_|\___|_| |_|   http://127.0.0.1:5000
"""
    print(banner)
    log.info("backend ready - RBAC reads, KQL log queries, and az apply commands print here")
    log.info("waiting for the dashboard...")
    app.run(host="127.0.0.1", port=5000, debug=False)
