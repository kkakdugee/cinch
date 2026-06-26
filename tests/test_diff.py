"""Unit tests for the pure analysis engine. No Azure required.

Run:  pip install -e ".[dev]" && pytest -q
"""

from __future__ import annotations

import json
from pathlib import Path

from alp.diff import diff
from alp.models import GrantedRole, UsedOperation
from alp.recommend import recommend

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _load():
    g = json.loads((SAMPLES / "granted_sample.json").read_text(encoding="utf-8"))
    u = json.loads((SAMPLES / "usage_sample.json").read_text(encoding="utf-8"))
    principal = g["principal_id"]
    granted = [GrantedRole.from_dict(d) for d in g["granted"]]
    used = [UsedOperation.from_dict(d) for d in u["used"]]
    return principal, granted, used


def test_diff_flags_unused_role():
    _, granted, used = _load()
    findings = diff(granted, used)
    kinds = {f.kind for f in findings}
    # The Contributor role on the never-touched 'acmearchive' account is unused.
    assert "unused_role" in kinds
    unused = [f for f in findings if f.kind == "unused_role"]
    assert any("acmearchive" in (f.scope or "") for f in unused)


def test_diff_flags_overbroad_scope_and_excess_ops():
    _, granted, used = _load()
    kinds = {f.kind for f in diff(granted, used)}
    assert "overbroad_scope" in kinds  # account/vault scope vs. specific child used
    assert "excess_operations" in kinds  # Owner/Officer grants write+delete; only read used


def test_recommend_downscopes_to_reader_roles():
    principal, granted, used = _load()
    result = recommend(principal, granted, used)
    kept = {(k.role_name, "reports" in k.scope or "db-conn" in k.scope) for k in result.keep}
    # Expect narrow reader-style roles scoped to the specific resources used.
    assert ("Storage Blob Data Reader", True) in kept
    assert ("Key Vault Secrets User", True) in kept


def test_recommend_removes_all_broad_grants():
    principal, granted, used = _load()
    result = recommend(principal, granted, used)
    removed_roles = {r.role_name for r in result.remove}
    assert "Storage Blob Data Owner" in removed_roles
    assert "Key Vault Secrets Officer" in removed_roles
    assert "Storage Blob Data Contributor" in removed_roles


def test_blast_radius_shrinks():
    principal, granted, used = _load()
    result = recommend(principal, granted, used)
    assert result.blast_radius_after < result.blast_radius_before


def test_az_commands_generated():
    principal, granted, used = _load()
    result = recommend(principal, granted, used)
    joined = "\n".join(result.az_cli)
    assert "az role assignment create" in joined
    assert "az role assignment delete" in joined
    assert principal in joined
