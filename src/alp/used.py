"""Collect what the agent ACTUALLY DID.

The VALIDATED live path is ``scripts/live_demo.py``: it reads tool name +
arguments authoritatively from the Foundry **run-steps API**
(``run_steps.list -> step_details.tool_calls``), confirmed end-to-end on a real
gpt-5-mini agent (2026-06). That is the source of truth for the tool/MCP layer.

This module is the **long-window App Insights adapter** -- a thin convenience for
aggregating historical usage once diagnostics are flowing. Two honest caveats
(see ``kql/agent_tool_usage.kql`` for the validated queries):

* App Insights reliably ties tool *activity* + outputs to an agent (via
  ``OperationId``), but on the SDK version we tested did NOT carry the tool
  *name* on its events -- so prefer run-steps for names.
* Data-plane *resource* access (blob read, secret get) is not in agent traces at
  all; it lives in the target resource's diagnostic logs (StorageBlobLogs / Key
  Vault AuditEvent). Enable those to populate the RBAC ``UsedOperation`` set.

The inline ``DEFAULT_KQL`` below is an illustrative skeleton, not a validated
schema; adjust it to whichever of the above sources you wire up.
"""

from __future__ import annotations

from datetime import timedelta

from .models import DELETE, LIST, OTHER, READ, WRITE, UsedOperation

# Illustrative skeleton ONLY (not a validated schema). The kql/ file is multi-query
# documentation; this inline query is what collect_used runs for the experimental
# CLI live-adapter. See the module docstring for the validated paths.
DEFAULT_KQL = """
let principalId = @PrincipalId;
dependencies
| extend cd = parse_json(customDimensions)
// --- VERIFY these attribute names against your trace schema ---
| extend agentPrincipal = tostring(cd['gen_ai.agent.principal_id'])
| extend audience       = tostring(cd['ai.resource.access_audience'])
| extend resourceId     = tostring(cd['ai.resource.id'])
| extend service        = tostring(cd['ai.service'])
| extend op             = tostring(cd['ai.operation.kind'])
// --------------------------------------------------------------
| where isnotempty(agentPrincipal) and agentPrincipal == principalId
| where isnotempty(resourceId)
| extend operation = case(
    op in ('read','get','GET'), 'read',
    op in ('list','LIST'), 'list',
    op in ('write','put','patch','post','PUT','PATCH','POST'), 'write',
    op in ('delete','DELETE'), 'delete',
    'other')
| summarize count=count() by service, audience, resource_id=resourceId, operation
| order by count desc
""".strip()


def _normalize_operation(raw: str) -> str:
    r = (raw or "").strip().lower()
    if r in ("read", "get"):
        return READ
    if r in ("list",):
        return LIST
    if r in ("write", "put", "patch", "post", "add", "move"):
        return WRITE
    if r in ("delete",):
        return DELETE
    return r if r in (READ, LIST, WRITE, DELETE) else OTHER


def collect_used(
    workspace_id: str, principal_id: str, lookback_days: int = 30
) -> list[UsedOperation]:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus

    credential = DefaultAzureCredential()
    client = LogsQueryClient(credential)
    query = DEFAULT_KQL.replace("@PrincipalId", f"'{principal_id}'")

    response = client.query_workspace(
        workspace_id, query, timespan=timedelta(days=lookback_days)
    )
    if response.status != LogsQueryStatus.SUCCESS or not response.tables:
        return []

    table = response.tables[0]
    columns = list(table.columns)
    used: list[UsedOperation] = []
    for row in table.rows:
        record = dict(zip(columns, row))
        used.append(
            UsedOperation(
                service=str(record.get("service", "") or ""),
                audience=str(record.get("audience", "") or ""),
                resource_id=str(record.get("resource_id", "") or ""),
                operation=_normalize_operation(str(record.get("operation", ""))),
                data_action=record.get("data_action"),
                count=int(record.get("count", 1) or 1),
            )
        )
    return used
