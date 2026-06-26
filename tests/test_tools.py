"""Unit tests for the tool / MCP right-sizing engine. No Azure required."""

from __future__ import annotations

import json
from pathlib import Path

from alp.models import GrantedRole, GrantedTool, UsedOperation, UsedTool
from alp.recommend import recommend
from alp.tools import analyze_tools

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _load():
    g = json.loads((SAMPLES / "granted_sample.json").read_text(encoding="utf-8"))
    u = json.loads((SAMPLES / "usage_sample.json").read_text(encoding="utf-8"))
    return (
        g["principal_id"],
        [GrantedRole.from_dict(d) for d in g["granted"]],
        [UsedOperation.from_dict(d) for d in u["used"]],
        [GrantedTool.from_dict(d) for d in g["granted_tools"]],
        [UsedTool.from_dict(d) for d in u["used_tools"]],
    )


def test_unused_tool_flagged_and_removed():
    _, _, _, gtools, utools = _load()
    findings, keep, remove, guidance, before, after = analyze_tools(gtools, utools)
    removed = {t.name for t in remove}
    # The payments MCP (charge/refund) and the email function were never invoked.
    assert "payments-mcp" in removed
    assert "send_email" in removed
    # Never-invoked dangerous tools are HIGH severity.
    sev = {f.role_name: f.severity for f in findings if f.kind == "unused_tool"}
    assert sev.get("payments-mcp") == "high"


def test_excess_tool_permission_downscoped():
    _, _, _, gtools, utools = _load()
    findings, keep, remove, guidance, before, after = analyze_tools(gtools, utools)
    kept = {k.name: k.keep_permissions for k in keep}
    # Write/ReadWrite granted but only read used -> keep only the read scope.
    assert kept.get("github-mcp") == ["repo.read"]
    assert kept.get("Microsoft Graph") == ["Mail.Read"]
    assert any(f.kind == "excess_tool_permission" for f in findings)


def test_tool_attack_surface_shrinks():
    _, _, _, gtools, utools = _load()
    _, _, _, _, before, after = analyze_tools(gtools, utools)
    assert after < before


def test_recommend_includes_tool_dimension():
    principal, granted, used, gtools, utools = _load()
    result = recommend(principal, granted, used, granted_tools=gtools, used_tools=utools)
    assert result.tool_findings
    assert {t.name for t in result.tool_remove} == {"payments-mcp", "send_email"}
    assert "CIEM cannot see this layer" in result.report
