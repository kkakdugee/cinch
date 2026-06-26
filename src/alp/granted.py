"""Collect what the agent was GRANTED: RBAC role assignments on its Entra agent
identity, resolved to role definitions (with data-plane actions) and scopes.

Live Azure adapter -- requires ``pip install -e ".[azure]"`` and credentials.
The exact SDK surface can shift between versions; call shapes below match
``azure-mgmt-authorization`` 4.x. Verify against your installed version.
"""

from __future__ import annotations

from . import auditlog as A

from .models import GrantedRole


def service_from_scope(scope: str) -> str:
    s = scope.lower()
    if "microsoft.storage" in s:
        return "storage"
    if "microsoft.keyvault" in s:
        return "keyvault"
    return ""


def collect_granted(subscription_id: str, principal_id: str) -> list[GrantedRole]:
    """Return all role assignments for *principal_id* under the subscription,
    resolved to their role definitions' data actions.
    """
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.authorization import AuthorizationManagementClient

    credential = DefaultAzureCredential()
    client = AuthorizationManagementClient(credential, subscription_id)
    scope = f"/subscriptions/{subscription_id}"

    A.tag("RBAC", "reading role assignments on the agent identity")
    granted: list[GrantedRole] = []
    # NOTE: filter syntax verified for azure-mgmt-authorization; principalId eq '<id>'
    assignments = client.role_assignments.list_for_scope(
        scope, filter=f"principalId eq '{principal_id}'"
    )
    for a in assignments:
        try:
            role_def = client.role_definitions.get_by_id(a.role_definition_id)
        except Exception:  # pragma: no cover - network/permissions dependent
            continue
        data_actions: list[str] = []
        actions: list[str] = []
        for perm in role_def.permissions or []:
            data_actions += list(perm.data_actions or [])
            actions += list(perm.actions or [])
        role_name = role_def.role_name or "(unknown)"
        granted.append(
            GrantedRole(
                role_name=role_name,
                scope=a.scope,
                service=service_from_scope(a.scope),
                data_actions=data_actions,
                actions=actions,
                role_definition_id=a.role_definition_id,
            )
        )
        A.grant(role_name, a.scope.split("/")[-1])
    A.result(f"  {len(granted)} role assignment(s) granted")
    return granted
