"""Right-size an agent's TOOL / MCP / API-permission grants -- the dimension
Microsoft CIEM cannot see at all (these never touch Azure RBAC or activity logs).

An agent is typically wired to more tools than it uses: MCP servers it can call,
functions it can invoke, Graph/API permissions it holds. An unused but powerful
tool (e.g. a payments MCP server, or `Mail.ReadWrite`) is pure attack surface if
the agent is compromised. Same idea as RBAC right-sizing: granted vs. invoked.

Pure functions -- runs offline.
"""

from __future__ import annotations

from .models import (
    DANGEROUS_TOOL_PERMS,
    Finding,
    GrantedTool,
    ToolRecommendation,
    UsedTool,
)


def _norm(p: str) -> str:
    return p.strip().lower().replace(".", "").replace("_", "")


def _is_dangerous(perm: str) -> bool:
    n = _norm(perm)
    return any(d in n for d in DANGEROUS_TOOL_PERMS)


def analyze_tools(
    granted: list[GrantedTool], used: list[UsedTool]
) -> tuple[list[Finding], list[ToolRecommendation], list[GrantedTool], list[str], int, int]:
    """Return (findings, keep, remove, guidance, surface_before, surface_after)."""
    used_by_name = {u.name: u for u in used}

    findings: list[Finding] = []
    keep: list[ToolRecommendation] = []
    remove: list[GrantedTool] = []
    guidance: list[str] = []

    for g in granted:
        u = used_by_name.get(g.name)
        if u is None or u.count == 0:
            # Granted but never invoked. Severity rises if it can do damage.
            severe = any(_is_dangerous(p) for p in g.permissions)
            findings.append(
                Finding(
                    kind="unused_tool",
                    severity="high" if severe else "medium",
                    detail=(
                        f"Tool '{g.name}' ({g.kind}) is wired to the agent with "
                        f"{g.permissions or ['(access)']} but was never invoked. "
                        f"Remove it from the agent configuration."
                    ),
                    role_name=g.name,
                )
            )
            remove.append(g)
            guidance.append(f"Remove {g.kind} '{g.name}' from the agent's tool configuration.")
            continue

        granted_perms = {_norm(p): p for p in g.permissions}
        used_perms = {_norm(p) for p in u.permissions_used}
        excess = [orig for n, orig in granted_perms.items() if n not in used_perms]
        dangerous_excess = [p for p in excess if _is_dangerous(p)]

        kept = [orig for n, orig in granted_perms.items() if n in used_perms] or g.permissions
        keep.append(ToolRecommendation(name=g.name, kind=g.kind, keep_permissions=sorted(kept)))

        if dangerous_excess:
            findings.append(
                Finding(
                    kind="excess_tool_permission",
                    severity="high",
                    detail=(
                        f"Tool '{g.name}' grants {dangerous_excess} but the agent "
                        f"only used {sorted(u.permissions_used)}. Restrict it to "
                        f"{sorted(kept)}."
                    ),
                    role_name=g.name,
                )
            )
            if g.kind == "api_permission":
                guidance.append(
                    f"Downgrade API permission on '{g.name}' to {sorted(kept)} "
                    f"(remove {dangerous_excess})."
                )
            else:
                guidance.append(
                    f"Restrict {g.kind} '{g.name}' to {sorted(kept)} (remove {dangerous_excess})."
                )

    surface_before = sum(max(1, len(g.permissions)) for g in granted)
    surface_after = sum(max(1, len(k.keep_permissions)) for k in keep)
    return findings, keep, remove, guidance, surface_before, surface_after
