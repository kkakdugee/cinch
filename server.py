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

import sys
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

WEB = Path(__file__).parent / "web"
app = Flask(__name__, static_folder=str(WEB), static_url_path="")


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
