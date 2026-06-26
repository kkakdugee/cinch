"""Unit tests for the data-plane diagnostic-log collector's pure parsing.

These cover the URI -> ARM-resource-id and OperationName -> normalized-operation
logic that turns raw StorageBlobLogs / Key Vault AuditEvent rows into the engine's
``UsedOperation`` set. No Azure required. The shapes here mirror rows observed
live (2026-06): e.g. StorageBlobLogs ``GetBlob`` on
``https://acct.blob.core.windows.net:443/reports/2026-06.md``.
"""

from __future__ import annotations

from alp.dataplane import (
    _aggregate,
    _container_resource_id,
    _norm_keyvault_op,
    _norm_storage_op,
    _secret_resource_id,
)
from alp.models import DELETE, LIST, OTHER, READ, UsedOperation

SUB = "00000000-0000-0000-0000-000000000000"
RG = "rg-demo"


def test_storage_op_normalization():
    assert _norm_storage_op("GetBlob") == READ
    assert _norm_storage_op("ListBlobs") == LIST
    assert _norm_storage_op("DeleteBlob") == DELETE
    assert _norm_storage_op("WeirdOp") == OTHER


def test_keyvault_op_normalization():
    assert _norm_keyvault_op("SecretGet") == READ
    assert _norm_keyvault_op("SecretList") == LIST
    assert _norm_keyvault_op("SecretDelete") == DELETE
    assert _norm_keyvault_op("VaultGet") == OTHER


def test_container_resource_id_from_blob_uri():
    # Blob-level read rolls up to the container resource id.
    uri = "https://alpdata.blob.core.windows.net:443/reports/2026-06.md"
    rid = _container_resource_id(uri, SUB, RG)
    assert rid == (
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage"
        f"/storageAccounts/alpdata/blobServices/default/containers/reports"
    )


def test_container_resource_id_from_list_uri():
    # ListBlobs carries a query string; the container is still 'reports'.
    uri = "https://alpdata.blob.core.windows.net:443/reports?restype=container&comp=list"
    rid = _container_resource_id(uri, SUB, RG)
    assert rid.endswith("/containers/reports")


def test_secret_resource_id_from_kv_uri():
    uri = "https://alpkv.vault.azure.net/secrets/db-conn/abc123version"
    rid = _secret_resource_id(uri, SUB, RG)
    assert rid == (
        f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault"
        f"/vaults/alpkv/secrets/db-conn"
    )


def test_non_matching_uris_return_none():
    assert _container_resource_id("https://example.com/foo", SUB, RG) is None
    assert _secret_resource_id("https://alpkv.vault.azure.net/keys/k1", SUB, RG) is None


def test_aggregate_sums_duplicate_operations():
    rid = "/subscriptions/x/.../containers/reports"
    rows = [
        UsedOperation(service="storage", audience="a", resource_id=rid, operation=READ, count=1),
        UsedOperation(service="storage", audience="a", resource_id=rid, operation=READ, count=1),
        UsedOperation(service="storage", audience="a", resource_id=rid, operation=LIST, count=1),
    ]
    out = _aggregate(rows)
    by_op = {u.operation: u.count for u in out}
    assert by_op == {READ: 2, LIST: 1}
