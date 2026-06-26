"""The diff engine: compare what an agent was granted vs. what it actually used.

Pure functions only -- no Azure dependencies -- so this is unit-testable and
runs in offline mode against sample JSON.
"""

from __future__ import annotations

from .models import (
    DELETE,
    MANAGE,
    WRITE,
    Finding,
    GrantedRole,
    UsedOperation,
)
from .role_catalog import operation_for_data_action, pick_minimal_role, role_by_name


def scope_contains(granted_scope: str, resource_id: str) -> bool:
    """True if *granted_scope* covers *resource_id* (prefix containment).

    Azure resource IDs are hierarchical paths, so an account-level scope is a
    prefix of a container-level resource ID under it. Comparison is
    case-insensitive on normalized paths.
    """
    g = granted_scope.rstrip("/").lower()
    r = resource_id.rstrip("/").lower()
    return r == g or r.startswith(g + "/")


def covered_operations(g: GrantedRole) -> set[str]:
    """Normalized operations a granted role permits.

    Prefers the curated catalog (by role name); falls back to deriving from the
    role's dataActions.
    """
    cat = role_by_name(g.role_name)
    if cat is not None:
        return set(cat.covers)
    ops = {operation_for_data_action(a) for a in g.data_actions}
    ops.discard("other")
    return ops


def used_under(scope: str, service: str, used: list[UsedOperation]):
    """Used operations whose resource falls under *scope* and matches *service*."""
    return [u for u in used if u.service == service and scope_contains(scope, u.resource_id)]


def diff(granted: list[GrantedRole], used: list[UsedOperation]) -> list[Finding]:
    """Produce least-privilege findings for one agent."""
    findings: list[Finding] = []

    for g in granted:
        hits = used_under(g.scope, g.service, used)
        granted_ops = covered_operations(g)

        # 1) The role (or its scope) was never exercised at all.
        if not hits:
            findings.append(
                Finding(
                    kind="unused_role",
                    severity="high",
                    detail=(
                        f"Role '{g.role_name}' at scope '{g.scope}' was granted "
                        f"but never used during the observed window. Remove it."
                    ),
                    role_name=g.role_name,
                    scope=g.scope,
                )
            )
            continue

        used_ops = set()
        used_resources = set()
        for u in hits:
            used_ops.add(u.operation)
            used_resources.add(u.resource_id)

        # 2) Scope is broader than the specific resources actually touched.
        broader_than_used = any(
            r.rstrip("/").lower() != g.scope.rstrip("/").lower() for r in used_resources
        )
        if broader_than_used:
            findings.append(
                Finding(
                    kind="overbroad_scope",
                    severity="medium",
                    detail=(
                        f"Role '{g.role_name}' is scoped to '{g.scope}' but the "
                        f"agent only touched: {sorted(used_resources)}. Narrow the "
                        f"scope to the resource(s) actually used."
                    ),
                    role_name=g.role_name,
                    scope=g.scope,
                )
            )

        # 3) Role grants powerful operations that were never used.
        excess = granted_ops - used_ops
        dangerous_excess = excess & {WRITE, DELETE, MANAGE}
        if dangerous_excess:
            narrower = pick_minimal_role(g.service, used_ops)
            if narrower is not None and narrower.name != g.role_name:
                findings.append(
                    Finding(
                        kind="excess_operations",
                        severity="high",
                        detail=(
                            f"Role '{g.role_name}' grants {sorted(dangerous_excess)} "
                            f"but the agent only performed {sorted(used_ops)}. "
                            f"Downgrade to '{narrower.name}'."
                        ),
                        role_name=g.role_name,
                        scope=g.scope,
                    )
                )

    return findings
