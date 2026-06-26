"""A small catalog of Azure built-in data-plane roles used to pick the narrowest
role that covers a set of observed operations.

This is intentionally a curated subset (Storage + Key Vault) sufficient for the
demo. A production version would load the full Azure role catalog via
``azure-mgmt-authorization`` role definitions and map dataActions
programmatically. Each role lists the normalized operations it covers and a
``rank`` (higher = more privileged) so we can pick the least-privileged role
that still covers what the agent actually did.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DELETE, LIST, MANAGE, READ, WRITE


@dataclass(frozen=True)
class CatalogRole:
    name: str
    service: str
    covers: frozenset[str]
    rank: int


CATALOG: tuple[CatalogRole, ...] = (
    # ---- Azure Storage (blob data plane) ----
    CatalogRole("Storage Blob Data Reader", "storage", frozenset({READ, LIST}), 1),
    CatalogRole(
        "Storage Blob Data Contributor",
        "storage",
        frozenset({READ, LIST, WRITE, DELETE}),
        2,
    ),
    CatalogRole(
        "Storage Blob Data Owner",
        "storage",
        frozenset({READ, LIST, WRITE, DELETE, MANAGE}),
        3,
    ),
    # ---- Azure Key Vault (secrets data plane) ----
    CatalogRole("Key Vault Secrets User", "keyvault", frozenset({READ, LIST}), 1),
    CatalogRole(
        "Key Vault Secrets Officer",
        "keyvault",
        frozenset({READ, LIST, WRITE, DELETE}),
        2,
    ),
)


def pick_minimal_role(service: str, needed: set[str]) -> CatalogRole | None:
    """Return the lowest-rank role for *service* whose ``covers`` is a superset
    of *needed*, or ``None`` if the catalog has no match.
    """
    candidates = [
        r for r in CATALOG if r.service == service and needed.issubset(r.covers)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.rank)


def role_by_name(name: str) -> CatalogRole | None:
    for r in CATALOG:
        if r.name == name:
            return r
    return None


# Map an Azure dataAction string onto a normalized operation. Best-effort suffix
# matching; extend as needed for more services.
def operation_for_data_action(data_action: str) -> str:
    a = data_action.lower()
    if a.endswith("/read"):
        # listing containers/blobs is also a .../read action; callers may refine
        return READ
    if a.endswith("/write") or a.endswith("/add/action") or a.endswith("/move/action"):
        return WRITE
    if a.endswith("/delete"):
        return DELETE
    if "manageownership" in a or "modifypermissions" in a or a.endswith("/manage/action"):
        return MANAGE
    return "other"
