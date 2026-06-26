"""Streamlit UI for the Agent Least-Privilege Analyzer.

Run:
    pip install -e ".[ui]"
    streamlit run app.py

Shows the over-privileged -> right-sized reveal visually: blast-radius and
tool-attack-surface gauges, findings, before/after, and the generated commands.
Uses the bundled sample by default; you can also upload granted/used JSON.
"""

from __future__ import annotations

import json

import streamlit as st

from alp.cli import _find, _load_granted, _load_used
from alp.models import GrantedRole, GrantedTool, UsedOperation, UsedTool
from alp.recommend import recommend

st.set_page_config(page_title="Agent Least-Privilege Analyzer", layout="wide")


def _severity(box, finding):
    msg = f"**{finding.kind}** — {finding.detail}"
    if finding.severity == "high":
        box.error(msg)
    elif finding.severity == "medium":
        box.warning(msg)
    else:
        box.info(msg)


def _load_inputs():
    st.sidebar.header("Input")
    source = st.sidebar.radio("Data source", ["Bundled sample", "Upload JSON"])
    if source == "Bundled sample":
        g = _find("samples/granted_sample.json")
        u = _find("samples/usage_sample.json")
        principal, granted, gtools = _load_granted(g)
        used, utools = _load_used(u)
        return principal, granted, used, gtools, utools

    gfile = st.sidebar.file_uploader("granted.json", type="json")
    ufile = st.sidebar.file_uploader("used.json", type="json")
    if not gfile or not ufile:
        st.info("Upload a granted.json and used.json, or switch to the bundled sample.")
        st.stop()
    gdata = json.load(gfile)
    udata = json.load(ufile)
    principal = gdata.get("principal_id", "")
    granted = [GrantedRole.from_dict(d) for d in gdata.get("granted", [])]
    gtools = [GrantedTool.from_dict(d) for d in gdata.get("granted_tools", [])]
    used = [UsedOperation.from_dict(d) for d in udata.get("used", [])]
    utools = [UsedTool.from_dict(d) for d in udata.get("used_tools", [])]
    return principal, granted, used, gtools, utools


st.title("🔐 Agent Least-Privilege Analyzer")
st.caption(
    "AI agents ship with god-mode access. We right-size them from what they "
    "**actually do** — including the tool/MCP layer Microsoft's CIEM can't see."
)

principal, granted, used, gtools, utools = _load_inputs()
result = recommend(principal, granted, used, granted_tools=gtools, used_tools=utools)

st.markdown(f"**Agent principal:** `{principal}`")

c1, c2 = st.columns(2)
rbac_red = (
    round(100 * (result.blast_radius_before - result.blast_radius_after) / result.blast_radius_before)
    if result.blast_radius_before
    else 0
)
tool_red = (
    round(100 * (result.tool_surface_before - result.tool_surface_after) / result.tool_surface_before)
    if result.tool_surface_before
    else 0
)
c1.metric(
    "RBAC blast-radius",
    f"{result.blast_radius_before} → {result.blast_radius_after}",
    delta=f"-{rbac_red}%",
    delta_color="inverse",
)
c2.metric(
    "Tool attack surface",
    f"{result.tool_surface_before} → {result.tool_surface_after}",
    delta=f"-{tool_red}%",
    delta_color="inverse",
)

st.divider()
st.subheader("Azure RBAC")
g, r = st.columns(2)
g.markdown("**Granted (before)**")
for x in granted:
    g.write(f"• `{x.role_name}` @ …/{x.scope.split('/')[-1]}")
r.markdown("**Right-sized (after)**")
for k in result.keep:
    r.write(f"✅ `{k.role_name}` @ …/{k.scope.split('/')[-1]} — {k.covers_operations}")
for x in result.remove:
    r.write(f"❌ remove `{x.role_name}` @ …/{x.scope.split('/')[-1]}")

st.markdown("**Findings**")
for f in result.findings:
    _severity(st, f)

st.divider()
st.subheader("Tools / MCP / API permissions")
st.caption("🔎 This layer is invisible to control-plane CIEM (Defender for Cloud).")
tg, tr = st.columns(2)
tg.markdown("**Wired to the agent (before)**")
for x in gtools:
    tg.write(f"• `{x.name}` ({x.kind}) — {x.permissions}")
tr.markdown("**Right-sized (after)**")
for k in result.tool_keep:
    tr.write(f"✅ `{k.name}` ({k.kind}) → {k.keep_permissions}")
for x in result.tool_remove:
    tr.write(f"❌ remove `{x.name}` ({x.kind})")
for f in result.tool_findings:
    _severity(st, f)

st.divider()
st.subheader("Apply")
apply_sh = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(result.az_cli) + "\n"
st.code(apply_sh, language="bash")
if result.tool_guidance:
    st.markdown("**Tool/agent-config changes:**")
    for gtext in result.tool_guidance:
        st.write(f"• {gtext}")

d1, d2, d3 = st.columns(3)
d1.download_button("report.txt", result.report, file_name="report.txt")
d2.download_button(
    "recommendations.json",
    json.dumps(result.to_dict(), indent=2),
    file_name="recommendations.json",
)
d3.download_button("apply.sh", apply_sh, file_name="apply.sh")
