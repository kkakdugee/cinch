"""Core data models shared across collectors and the analysis engine.

These are deliberately plain dataclasses with tolerant ``from_dict`` loaders so
the same shapes serialize to/from the sample JSON used in offline mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Normalized data-plane operations. Azure RBAC dataActions are mapped onto these
# coarse buckets so granted vs. used comparisons are tractable.
READ = "read"
LIST = "list"
WRITE = "write"
DELETE = "delete"
MANAGE = "manage"  # ownership / ACL / POSIX permission management
OTHER = "other"

OPERATIONS = (READ, LIST, WRITE, DELETE, MANAGE, OTHER)


@dataclass
class GrantedRole:
    """An RBAC role assignment on the agent identity's principal.

    ``scope`` is the assignment scope (e.g. a subscription, resource group, or a
    specific resource). ``data_actions``/``actions`` come from the role
    definition; we mostly reason over data-plane actions.
    """

    role_name: str
    scope: str
    service: str = ""  # e.g. "storage", "keyvault" (best-effort, for grouping)
    data_actions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    role_definition_id: str = ""

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "GrantedRole":
        return GrantedRole(
            role_name=d["role_name"],
            scope=d["scope"],
            service=d.get("service", ""),
            data_actions=list(d.get("data_actions", [])),
            actions=list(d.get("actions", [])),
            role_definition_id=d.get("role_definition_id", ""),
        )


@dataclass
class UsedOperation:
    """One access the agent actually performed, reconstructed from traces.

    ``audience`` is the OAuth resource the tool token targeted (e.g.
    ``https://storage.azure.com``). ``resource_id`` is the best-effort specific
    resource touched (e.g. a single container). ``operation`` is normalized.
    """

    service: str
    audience: str
    resource_id: str
    operation: str
    data_action: Optional[str] = None
    count: int = 1

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "UsedOperation":
        return UsedOperation(
            service=d["service"],
            audience=d.get("audience", ""),
            resource_id=d["resource_id"],
            operation=d.get("operation", OTHER),
            data_action=d.get("data_action"),
            count=int(d.get("count", 1)),
        )


@dataclass
class Finding:
    """A single least-privilege issue."""

    kind: str  # unused_role | overbroad_scope | excess_operations | unused_resource
    severity: str  # high | medium | low
    detail: str
    role_name: Optional[str] = None
    scope: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
            "role_name": self.role_name,
            "scope": self.scope,
        }


@dataclass
class RecommendedAssignment:
    """A right-sized assignment to keep (role scoped to a used resource)."""

    role_name: str
    scope: str
    covers_operations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_name": self.role_name,
            "scope": self.scope,
            "covers_operations": list(self.covers_operations),
        }


# ----- Tool / MCP / API-permission grants (the dimension CIEM cannot see) -----
# An agent is also wired to tools: MCP servers, local functions, and Graph/API
# permissions. These are NOT Azure RBAC and never appear in cloud activity logs,
# so CIEM is fully blind to them. We right-size them the same way: granted vs.
# actually-invoked.

# Permission keywords that represent elevated/destructive capability on a tool.
DANGEROUS_TOOL_PERMS = {
    "write",
    "delete",
    "manage",
    "admin",
    "charge",
    "refund",
    "send",
    "execute",
    "readwrite",
}


@dataclass
class GrantedTool:
    """A tool/connector the agent is configured to access."""

    name: str
    kind: str  # mcp_server | function | api_permission
    permissions: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "GrantedTool":
        return GrantedTool(
            name=d["name"],
            kind=d.get("kind", "tool"),
            permissions=list(d.get("permissions", [])),
        )


@dataclass
class UsedTool:
    """A tool the agent actually invoked, with the scopes it exercised."""

    name: str
    permissions_used: list[str] = field(default_factory=list)
    count: int = 0

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "UsedTool":
        return UsedTool(
            name=d["name"],
            permissions_used=list(d.get("permissions_used", [])),
            count=int(d.get("count", 0)),
        )


@dataclass
class ToolRecommendation:
    name: str
    kind: str
    keep_permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "keep_permissions": list(self.keep_permissions),
        }


@dataclass
class AnalysisResult:
    """Bundle of everything the engine produces for one agent."""

    principal_id: str
    findings: list[Finding] = field(default_factory=list)
    keep: list[RecommendedAssignment] = field(default_factory=list)
    remove: list[GrantedRole] = field(default_factory=list)
    az_cli: list[str] = field(default_factory=list)
    bicep: str = ""
    report: str = ""
    blast_radius_before: int = 0
    blast_radius_after: int = 0
    # Tool / MCP dimension (CIEM-blind).
    tool_findings: list[Finding] = field(default_factory=list)
    tool_keep: list[ToolRecommendation] = field(default_factory=list)
    tool_remove: list[GrantedTool] = field(default_factory=list)
    tool_guidance: list[str] = field(default_factory=list)
    tool_surface_before: int = 0
    tool_surface_after: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "findings": [f.to_dict() for f in self.findings],
            "keep": [k.to_dict() for k in self.keep],
            "remove": [r.role_name + " @ " + r.scope for r in self.remove],
            "az_cli": list(self.az_cli),
            "blast_radius_before": self.blast_radius_before,
            "blast_radius_after": self.blast_radius_after,
            "tool_findings": [f.to_dict() for f in self.tool_findings],
            "tool_keep": [t.to_dict() for t in self.tool_keep],
            "tool_remove": [t.name for t in self.tool_remove],
            "tool_guidance": list(self.tool_guidance),
            "tool_surface_before": self.tool_surface_before,
            "tool_surface_after": self.tool_surface_after,
        }
