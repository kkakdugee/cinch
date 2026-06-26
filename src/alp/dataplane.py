"""Collect what an agent identity ACTUALLY did at the DATA PLANE, from Azure
resource diagnostic logs -- the exact signal CIEM's control-plane model misses.

This is the load-bearing collector that makes the "data-plane blind spot" claim
DEMONSTRATED rather than designed. An agent's blob reads and secret fetches never
appear in the Azure Activity Log (control plane), so CIEM cannot see them. They DO
appear in the *target resource's* own diagnostic logs:

  * Azure Storage blob ops -> ``StorageBlobLogs`` (resource-specific table).
  * Key Vault secret ops   -> ``AzureDiagnostics`` (category ``AuditEvent``) or the
    resource-specific ``AZKVAuditLogs`` table, depending on the diagnostic setting.

Both carry the *caller's AAD object id*, so we attribute every operation to the
agent identity's principal and reconstruct the (resource, operation) set it
exercised. Validated live (2026-06): a user-assigned identity granted Storage Blob
Data Owner + Key Vault Secrets Officer read a blob + a secret; the reads landed in
``StorageBlobLogs`` (``OperationName`` GetBlob/ListBlobs, ``AuthenticationType``
OAuth, ``RequesterObjectId`` == the identity) and the KV audit log.

Requires ``pip install -e ".[azure]"`` and ``Log Analytics Reader`` on the
workspace the diagnostics flow to.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional
from urllib.parse import urlsplit

from . import auditlog as A
from .models import DELETE, LIST, OTHER, READ, WRITE, UsedOperation

STORAGE_AUDIENCE = "https://storage.azure.com"
KEYVAULT_AUDIENCE = "https://vault.azure.net"

# Azure Storage blob OperationName -> normalized operation.
_STORAGE_OPS = {
    "getblob": READ,
    "getblobproperties": READ,
    "getblobmetadata": READ,
    "getblobtags": READ,
    "listblobs": LIST,
    "listcontainers": LIST,
    "putblob": WRITE,
    "putblock": WRITE,
    "putblocklist": WRITE,
    "setblobproperties": WRITE,
    "setblobmetadata": WRITE,
    "setblobtags": WRITE,
    "copyblob": WRITE,
    "deleteblob": DELETE,
}

# Key Vault OperationName -> normalized operation (secrets data plane).
_KEYVAULT_OPS = {
    "secretget": READ,
    "secretlist": LIST,
    "secretlistversions": LIST,
    "secretset": WRITE,
    "secretupdate": WRITE,
    "secretbackup": READ,
    "secretdelete": DELETE,
    "secretpurge": DELETE,
}


def _norm_storage_op(name: str) -> str:
    return _STORAGE_OPS.get((name or "").strip().lower(), OTHER)


def _norm_keyvault_op(name: str) -> str:
    return _KEYVAULT_OPS.get((name or "").strip().lower(), OTHER)


def _container_resource_id(uri: str, sub: str, rg: str) -> Optional[str]:
    """Map a blob-service URI to the container's ARM resource id.

    ``https://acct.blob.core.windows.net:443/reports/2026-06.md`` ->
    ``/subscriptions/.../storageAccounts/acct/blobServices/default/containers/reports``
    Blob-level ops roll up to the container (roles scope at container/account).
    """
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if ".blob." not in host:
        return None
    account = host.split(".", 1)[0]
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return None
    container = segments[0]
    return (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Storage"
        f"/storageAccounts/{account}/blobServices/default/containers/{container}"
    )


def _secret_resource_id(uri: str, sub: str, rg: str) -> Optional[str]:
    """Map a Key Vault request URI to the secret's ARM resource id.

    ``https://vault.vault.azure.net/secrets/db-conn/<ver>`` ->
    ``/subscriptions/.../vaults/vault/secrets/db-conn``
    """
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if ".vault." not in host:
        return None
    vault = host.split(".", 1)[0]
    segments = [s for s in parts.path.split("/") if s]
    # expect ['secrets', '<name>', '<version>?']
    if len(segments) < 2 or segments[0] != "secrets":
        return None
    secret = segments[1]
    return (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.KeyVault"
        f"/vaults/{vault}/secrets/{secret}"
    )


def _aggregate(rows: list[UsedOperation]) -> list[UsedOperation]:
    """Collapse duplicate (service, resource_id, operation) rows, summing counts."""
    acc: dict[tuple, UsedOperation] = {}
    for u in rows:
        key = (u.service, u.resource_id, u.operation)
        if key in acc:
            acc[key].count += u.count
        else:
            acc[key] = u
    return list(acc.values())


def _query(client, workspace_id: str, kql: str, lookback_days: int):
    """Run a KQL query, tolerating tables/columns that don't exist in this
    workspace (returns [] instead of raising) so multi-schema fallbacks work.
    """
    from azure.core.exceptions import HttpResponseError
    from azure.monitor.query import LogsQueryStatus

    try:
        resp = client.query_workspace(
            workspace_id, kql, timespan=timedelta(days=lookback_days)
        )
    except HttpResponseError:
        # Typically a missing table/column (e.g. AZKVAuditLogs not provisioned).
        return []
    if resp.status != LogsQueryStatus.SUCCESS or not resp.tables:
        return []
    table = resp.tables[0]
    cols = list(table.columns)
    return [dict(zip(cols, row)) for row in table.rows]


def collect_storage(
    client, workspace_id: str, principal_id: str, sub: str, rg: str, lookback_days: int
) -> list[UsedOperation]:
    kql = f"""StorageBlobLogs
| where TimeGenerated > ago({lookback_days}d)
| where RequesterObjectId == '{principal_id}'
| where StatusText =~ 'Success'
| project OperationName, Uri
"""
    A.tag("LOGS", "querying StorageBlobLogs (blob data-plane access)")
    used: list[UsedOperation] = []
    for rec in _query(client, workspace_id, kql, lookback_days):
        op = _norm_storage_op(rec.get("OperationName", ""))
        if op == OTHER:
            continue
        rid = _container_resource_id(str(rec.get("Uri", "")), sub, rg)
        if not rid:
            continue
        used.append(
            UsedOperation(
                service="storage",
                audience=STORAGE_AUDIENCE,
                resource_id=rid,
                operation=op,
                count=1,
            )
        )
    out = _aggregate(used)
    for u in out:
        A.usage(u.operation, u.count, u.resource_id.split("/")[-1])
    return out


def collect_keyvault(
    client, workspace_id: str, principal_id: str, sub: str, rg: str, lookback_days: int
) -> list[UsedOperation]:
    """Key Vault audit events. Tries resource-specific AZKVAuditLogs first, then
    falls back to the legacy AzureDiagnostics schema -- whichever the diagnostic
    setting populated.
    """
    queries = [
        # Resource-specific table.
        (
            "AZKVAuditLogs",
            f"""AZKVAuditLogs
| where TimeGenerated > ago({lookback_days}d)
| where identity_claim_oid_g == '{principal_id}'
| where ResultType == 'Success'
| project OperationName, requestUri_s
""",
            "requestUri_s",
        ),
        # Legacy AzureDiagnostics table.
        (
            "AzureDiagnostics",
            f"""AzureDiagnostics
| where TimeGenerated > ago({lookback_days}d)
| where ResourceProvider == 'MICROSOFT.KEYVAULT'
| where identity_claim_oid_g == '{principal_id}'
| where ResultType == 'Success'
| project OperationName, requestUri_s, id_s
""",
            "requestUri_s",
        ),
    ]
    A.tag("LOGS", "querying Key Vault AuditEvent (secret data-plane access)")
    for _table, kql, uri_col in queries:
        rows = _query(client, workspace_id, kql, lookback_days)
        if not rows:
            continue
        used: list[UsedOperation] = []
        for rec in rows:
            op = _norm_keyvault_op(rec.get("OperationName", ""))
            if op == OTHER:
                continue
            uri = str(rec.get(uri_col) or rec.get("id_s") or "")
            rid = _secret_resource_id(uri, sub, rg)
            if not rid:
                continue
            used.append(
                UsedOperation(
                    service="keyvault",
                    audience=KEYVAULT_AUDIENCE,
                    resource_id=rid,
                    operation=op,
                    count=1,
                )
            )
        if used:
            out = _aggregate(used)
            for u in out:
                A.usage(u.operation, u.count, u.resource_id.split("/")[-1])
            return out
    return []


def collect_dataplane(
    workspace_id: str,
    principal_id: str,
    subscription_id: str,
    resource_group: str,
    lookback_days: int = 30,
) -> list[UsedOperation]:
    """Reconstruct the agent identity's data-plane usage from diagnostic logs.

    ``workspace_id`` is the Log Analytics workspace GUID the diagnostics flow to.
    ``principal_id`` is the agent identity's AAD object id. ``subscription_id`` /
    ``resource_group`` are used to build ARM resource ids that prefix-match the
    granted role scopes. (Production note: for resources spread across many
    resource groups, resolve account/vault name -> ARM id via Azure Resource Graph
    instead of assuming a single resource group.)
    """
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient

    client = LogsQueryClient(DefaultAzureCredential())
    used: list[UsedOperation] = []
    used += collect_storage(
        client, workspace_id, principal_id, subscription_id, resource_group, lookback_days
    )
    used += collect_keyvault(
        client, workspace_id, principal_id, subscription_id, resource_group, lookback_days
    )
    return used
