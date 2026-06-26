"""End-to-end LIVE demo for the Least-Privilege Analyzer.

Runs a real Microsoft Foundry agent that is deliberately wired to MORE tools than
it needs, observes what it ACTUALLY invokes, reconstructs granted-vs-used, and
produces a right-sized least-privilege recommendation (RBAC + tools) with
ready-to-apply artifacts.

WHAT IS LIVE HERE
  * The agent, its threads/runs, and every tool invocation -- pulled from the
    run-steps API (run_steps.list -> step_details.tool_calls), the AUTHORITATIVE
    source for tool name + arguments. Validated live 2026-06 (gpt-5-mini).
  * OpenTelemetry traces exported to Application Insights (corroboration + the
    long-observation-window history a production collector would aggregate).

WHAT IS DECLARED (the realistic "before" state)
  * The over-broad RBAC grant on the agent identity and the resource IDs the read
    tools map to. Agent-identity *data-plane* RBAC is the part of the platform
    still maturing; the analyzer's logic (granted vs. observed) is identical no
    matter how the grant was made, so we declare a realistic over-provisioned
    starting point and right-size it from the live tool usage.

HONEST SCHEMA NOTE (validated live, not assumed)
  Tool NAME + ARGUMENTS are reliably available from the run-steps API. Through the
  current OTel -> App Insights export, AppTraces carried the tool OUTPUT
  (gen_ai.tool.message) and AppDependencies proved the invocation occurred
  (submit_tool_outputs span tied to gen_ai.agent.id), but did not carry the tool
  name on every event/SDK version. So this collector treats run-steps as the
  source of truth and App Insights as corroboration. The KQL in
  kql/agent_tool_usage.kql documents both.

Usage:
    python scripts/live_demo.py            # run agent, analyze, write out/live/
    python scripts/live_demo.py --no-trace # skip App Insights export
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make the package importable when run from the repo without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alp.models import (  # noqa: E402
    GrantedRole,
    GrantedTool,
    UsedOperation,
    UsedTool,
)
from alp.recommend import recommend  # noqa: E402

# --------------------------------------------------------------------------- #
# Config (env-overridable; defaults point at the validated student-sub demo).
# --------------------------------------------------------------------------- #
ENDPOINT = os.environ.get(
    "ALP_EP", "https://alp-fdry-52f3ok.services.ai.azure.com/api/projects/alp-project"
)
MODEL = os.environ.get("ALP_MODEL", "gpt-5-mini")
APPINSIGHTS_CONN = os.environ.get("ALP_AI_CONN", "")

SUB = os.environ.get("ALP_SUBSCRIPTION_ID", "bae3d5e2-719b-4cc9-8447-f762f0fc0b33")
RG = os.environ.get("ALP_DEMO_RG", "rg-alp-demo")
STORAGE_ACCT = os.environ.get("ALP_DEMO_STORAGE", "alpdemodata")
ARCHIVE_ACCT = os.environ.get("ALP_DEMO_ARCHIVE", "alpdemoarchive")
KEY_VAULT = os.environ.get("ALP_DEMO_KV", "alp-demo-kv")

_BASE = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers"
STORAGE_ID = f"{_BASE}/Microsoft.Storage/storageAccounts/{STORAGE_ACCT}"
ARCHIVE_ID = f"{_BASE}/Microsoft.Storage/storageAccounts/{ARCHIVE_ACCT}"
KV_ID = f"{_BASE}/Microsoft.KeyVault/vaults/{KEY_VAULT}"


def _container_id(container: str) -> str:
    return f"{STORAGE_ID}/blobServices/default/containers/{container}"


def _secret_id(name: str) -> str:
    return f"{KV_ID}/secrets/{name}"


# --------------------------------------------------------------------------- #
# The DECLARED "before" state: over-broad RBAC + a wide tool loadout.
# --------------------------------------------------------------------------- #
GRANTED_ROLES = [
    GrantedRole(
        role_name="Storage Blob Data Owner",
        service="storage",
        scope=STORAGE_ID,
        data_actions=[
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/manageOwnership/action",
        ],
    ),
    GrantedRole(
        role_name="Key Vault Secrets Officer",
        service="keyvault",
        scope=KV_ID,
        data_actions=[
            "Microsoft.KeyVault/vaults/secrets/read",
            "Microsoft.KeyVault/vaults/secrets/update/action",
            "Microsoft.KeyVault/vaults/secrets/delete",
        ],
    ),
    # A whole role on a second account the agent never touches -> unused_role.
    GrantedRole(
        role_name="Storage Blob Data Contributor",
        service="storage",
        scope=ARCHIVE_ID,
        data_actions=[
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
            "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
        ],
    ),
]

# Tools the agent is WIRED to. read_report/list_reports/get_db_secret are needed;
# send_email and charge_payment are powerful and -- as we will observe -- never
# invoked. (Function tools here; an MCP server is governed identically: granted
# vs. invoked. The CIEM-blind layer.)
GRANTED_TOOLS = [
    GrantedTool(name="read_report", kind="function", permissions=["read"]),
    GrantedTool(name="list_reports", kind="function", permissions=["list"]),
    GrantedTool(name="get_db_secret", kind="function", permissions=["read"]),
    GrantedTool(name="send_email", kind="function", permissions=["send"]),
    GrantedTool(name="charge_payment", kind="function", permissions=["charge"]),
]

# How an observed tool call maps to a data-plane operation / tool exercise.
TOOL_MAP = {
    "read_report": dict(
        service="storage", audience="https://storage.azure.com", operation="read",
        perm="read", resource=lambda a: _container_id(a.get("container", "reports")),
        data_action="Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    ),
    "list_reports": dict(
        service="storage", audience="https://storage.azure.com", operation="list",
        perm="list", resource=lambda a: _container_id(a.get("container", "reports")),
        data_action=None,
    ),
    "get_db_secret": dict(
        service="keyvault", audience="https://vault.azure.net", operation="read",
        perm="read", resource=lambda a: _secret_id(a.get("name", "db-conn")),
        data_action="Microsoft.KeyVault/vaults/secrets/read",
    ),
}

REPRESENTATIVE_TASKS = [
    "Summarize the latest monthly report in the reports container.",
    "List the available reports, then read the newest one and summarize it.",
    "What does the latest report say about churn? Read it from the reports container.",
    "Confirm the db-conn secret exists by reading it, but do NOT print its value.",
]


# --------------------------------------------------------------------------- #
# Mock tool implementations. Only the INVOCATION (name + args) matters for the
# analyzer; the return values are representative stand-ins.
# --------------------------------------------------------------------------- #
def read_report(container: str) -> str:
    """Read the latest monthly report from a blob container.

    :param container: the blob container name.
    :return: the report text.
    """
    return f"[mock] report in '{container}': revenue +12% QoQ, churn down 0.4pts."


def list_reports(container: str) -> str:
    """List available reports in a blob container.

    :param container: the blob container name.
    :return: a list of report names.
    """
    return f"[mock] {container}: 2026-04.md, 2026-05.md, 2026-06.md"


def get_db_secret(name: str) -> str:
    """Read a secret from Key Vault (presence check only).

    :param name: the secret name.
    :return: a confirmation that the secret is present.
    """
    return f"[mock] secret '{name}' is present."


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email. (Powerful: should not be used for read-only reporting.)

    :param to: recipient address.
    :param subject: email subject.
    :param body: email body.
    :return: a send confirmation.
    """
    return f"[mock] email queued to {to}"


def charge_payment(account: str, amount: float) -> str:
    """Charge a payment. (Powerful: should not be used for read-only reporting.)

    :param account: the account to charge.
    :param amount: the amount to charge.
    :return: a charge confirmation.
    """
    return f"[mock] charged {amount} to {account}"


TOOL_FUNCS = {read_report, list_reports, get_db_secret, send_email, charge_payment}


# --------------------------------------------------------------------------- #
# Tracing (OpenTelemetry -> Application Insights). Corroboration only.
# --------------------------------------------------------------------------- #
def _setup_tracing():
    if not APPINSIGHTS_CONN:
        print("  (no ALP_AI_CONN set; skipping App Insights export)")
        return None
    os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
    from azure.ai.agents.telemetry import AIAgentsInstrumentor
    from azure.core.settings import settings
    from azure.core.tracing.ext.opentelemetry_span import OpenTelemetrySpan
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    settings.tracing_implementation = OpenTelemetrySpan
    provider = TracerProvider()
    provider.add_span_processor(
        SimpleSpanProcessor(AzureMonitorTraceExporter(connection_string=APPINSIGHTS_CONN))
    )
    trace.set_tracer_provider(provider)
    AIAgentsInstrumentor().instrument()
    return provider


# --------------------------------------------------------------------------- #
# Authoritative usage collection from the run-steps API.
# --------------------------------------------------------------------------- #
def _extract_tool_calls(step) -> list[tuple[str, dict]]:
    """Return [(tool_name, arguments_dict)] from a RunStep, defensively."""
    out: list[tuple[str, dict]] = []
    details = getattr(step, "step_details", None)
    tool_calls = getattr(details, "tool_calls", None) if details else None
    if not tool_calls:
        return out
    for call in tool_calls:
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", None) if fn else None
        raw_args = getattr(fn, "arguments", None) if fn else None
        if name is None:  # tolerate dict-shaped payloads
            try:
                name = call["function"]["name"]
                raw_args = call["function"].get("arguments")
            except Exception:
                continue
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            args = {}
        out.append((name, args if isinstance(args, dict) else {}))
    return out


def build_used(tool_calls_seen: list) -> tuple[list[UsedOperation], list[UsedTool]]:
    """Aggregate raw tool calls into UsedOperation (RBAC) + UsedTool (tool dim)."""
    op_counts: dict[tuple, dict] = {}
    tool_counts: dict[str, dict] = defaultdict(lambda: {"count": 0, "perms": set()})

    for name, args in tool_calls_seen:
        spec = TOOL_MAP.get(name)
        # Tool dimension: every observed tool counts, mapped to its exercised perm.
        perm = spec["perm"] if spec else "invoke"
        tool_counts[name]["count"] += 1
        tool_counts[name]["perms"].add(perm)
        # RBAC dimension: only tools that hit Azure data-plane resources.
        if not spec or spec["operation"] is None:
            continue
        rid = spec["resource"](args)
        key = (spec["service"], rid, spec["operation"])
        if key not in op_counts:
            op_counts[key] = {
                "service": spec["service"],
                "audience": spec["audience"],
                "resource_id": rid,
                "operation": spec["operation"],
                "data_action": spec["data_action"],
                "count": 0,
            }
        op_counts[key]["count"] += 1

    used_ops = [UsedOperation(**v) for v in op_counts.values()]
    used_tools = [
        UsedTool(name=n, permissions_used=sorted(v["perms"]), count=v["count"])
        for n, v in tool_counts.items()
    ]
    return used_ops, used_tools


# --------------------------------------------------------------------------- #
# Serialization helpers (so the CLI can re-run on the captured JSON).
# --------------------------------------------------------------------------- #
def _granted_to_json(principal_id: str) -> dict:
    return {
        "principal_id": principal_id,
        "granted": [
            {
                "role_name": r.role_name,
                "service": r.service,
                "scope": r.scope,
                "data_actions": r.data_actions,
            }
            for r in GRANTED_ROLES
        ],
        "granted_tools": [
            {"name": t.name, "kind": t.kind, "permissions": t.permissions}
            for t in GRANTED_TOOLS
        ],
    }


def _used_to_json(used_ops, used_tools) -> dict:
    return {
        "used": [
            {
                "service": o.service,
                "audience": o.audience,
                "resource_id": o.resource_id,
                "operation": o.operation,
                "data_action": o.data_action,
                "count": o.count,
            }
            for o in used_ops
        ],
        "used_tools": [
            {"name": t.name, "permissions_used": t.permissions_used, "count": t.count}
            for t in used_tools
        ],
    }


def _write_artifacts(out_dir: Path, result) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.txt").write_text(result.report, encoding="utf-8")
    (out_dir / "recommendations.json").write_text(
        json.dumps(result.to_dict(), indent=2), encoding="utf-8"
    )
    (out_dir / "apply.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(result.az_cli) + "\n",
        encoding="utf-8",
    )
    (out_dir / "main.bicep").write_text(result.bicep, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="End-to-end live least-privilege demo.")
    parser.add_argument("--no-trace", action="store_true", help="Skip App Insights export.")
    parser.add_argument("--out", default="out/live", help="Artifact output dir.")
    parser.add_argument("--keep-agent", action="store_true", help="Do not delete the agent.")
    args = parser.parse_args(argv)

    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import FunctionTool, ToolSet
    from azure.identity import DefaultAzureCredential

    provider = None if args.no_trace else _setup_tracing()

    print(f"\n[1/5] Connecting to Foundry project: {ENDPOINT}")
    client = AgentsClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())

    toolset = ToolSet()
    toolset.add(FunctionTool(TOOL_FUNCS))
    client.enable_auto_function_calls(toolset)

    print("[2/5] Creating an over-provisioned agent (5 tools wired; needs 3)")
    agent = client.create_agent(
        model=MODEL,
        name="alp-live-demo",
        instructions=(
            "You are a read-only reporting assistant. To answer questions, call "
            "read_report and list_reports on the 'reports' container, and "
            "get_db_secret only to confirm a secret's presence. NEVER call "
            "send_email or charge_payment -- you have no reason to."
        ),
        toolset=toolset,
    )
    print(f"      agent id: {agent.id}")

    tool_calls_seen: list = []
    print(f"[3/5] Running {len(REPRESENTATIVE_TASKS)} representative read-only tasks")
    for i, task in enumerate(REPRESENTATIVE_TASKS, 1):
        thread = client.threads.create()
        client.messages.create(thread.id, role="user", content=task)
        run = client.runs.create_and_process(
            thread_id=thread.id, agent_id=agent.id, toolset=toolset
        )
        task_calls = _step_names(client, thread.id, run.id)
        tool_calls_seen.extend(task_calls)
        invoked = sorted({n for n, _ in task_calls})
        print(f"      [{run.status}] task {i}: tools -> {invoked or '(none)'}")

    used_ops, used_tools = build_used(tool_calls_seen)
    invoked_names = sorted({n for n, _ in tool_calls_seen})
    print(f"\n      Observed tool invocations (authoritative, run-steps API):")
    print(f"        used     : {invoked_names}")
    print(f"        wired    : {[t.name for t in GRANTED_TOOLS]}")
    never = sorted({t.name for t in GRANTED_TOOLS} - set(invoked_names))
    print(f"        NEVER used (attack surface): {never}")

    print("\n[4/5] Right-sizing granted-vs-used (RBAC + tools)")
    result = recommend(
        agent.id,
        GRANTED_ROLES,
        used_ops,
        granted_tools=GRANTED_TOOLS,
        used_tools=used_tools,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "live_granted.json").write_text(
        json.dumps(_granted_to_json(agent.id), indent=2), encoding="utf-8"
    )
    (out_dir / "live_used.json").write_text(
        json.dumps(_used_to_json(used_ops, used_tools), indent=2), encoding="utf-8"
    )
    _write_artifacts(out_dir, result)

    print("\n" + "=" * 78)
    print(result.report)
    print("=" * 78)
    print(f"\n[5/5] Artifacts + captured live data written to {out_dir}/")
    print("      - live_granted.json / live_used.json  (re-run: alp analyze "
          "--granted .../live_granted.json --used .../live_used.json)")
    print("      - report.txt / recommendations.json / apply.sh / main.bicep")

    if provider is not None:
        provider.force_flush()
        print("\n      Traces flushed to App Insights (ingestion ~1-4 min). "
              "Corroborate with kql/agent_tool_usage.kql.")

    if not args.keep_agent:
        try:
            client.delete_agent(agent.id)
            print(f"      Cleaned up agent {agent.id}.")
        except Exception as e:  # noqa: BLE001
            print(f"      (could not delete agent: {e})")

    return 0


def _step_names(client, thread_id, run_id):
    """Per-task helper: list (name, args) without mutating the global accumulator."""
    seen = []
    for step in client.run_steps.list(thread_id=thread_id, run_id=run_id):
        seen.extend(_extract_tool_calls(step))
    return seen


if __name__ == "__main__":
    raise SystemExit(main())
