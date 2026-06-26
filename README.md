# Agent Least-Privilege Analyzer (`alp`)

**IAM Access Analyzer, but for AI agents.**

AI agents in Microsoft Foundry ship with whatever permissions a developer grants
to "just make it work" — usually broad, account-wide, read/write/delete. `alp`
reads what an agent was **granted** (its Entra agent-identity RBAC) and what it
**actually did** (tool/resource calls from Foundry traces), diffs them, and emits
a right-sized, least-privilege RBAC recommendation you can apply.

> Hackathon track: **Security and Trustworthy Systems**.

---

## Why this exists

Over-permissioned agents are a growing, concrete attack surface: a compromised
agent with `Storage Blob Data Owner` account-wide can read, overwrite, and delete
everything, even if it only ever needed to read one container. Microsoft's own
docs frame agent identity around *"apply least-privilege access with Azure RBAC"* —
but the tooling that computes least privilege from usage has a structural blind
spot for exactly what agents do (see [How this differs from Microsoft's CIEM](#how-this-differs-from-microsofts-ciem-defender-for-cloud)).

Verified against Microsoft Learn (June 2026):

- **Grant is readable.** Foundry provisions an Entra **agent identity**; **RBAC
  roles** are assigned to it. ([agent identity concepts])
- **Usage is observable on two layers.** The **tool / MCP** layer is captured by
  Foundry **tracing** (OpenTelemetry → Application Insights; authoritative tool
  name+args via the run-steps API). The **data-plane resource** layer — the
  specific blobs read and secrets fetched — is captured by each resource's own
  **diagnostic logs** (`StorageBlobLogs`, Key Vault `AuditEvent`), which record the
  calling agent identity's object id. ([agent tracing])

[agent identity concepts]: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity
[agent tracing]: https://learn.microsoft.com/en-us/azure/foundry/observability/concepts/trace-agent-concept

---

## How this differs from Microsoft's CIEM (Defender for Cloud)

Microsoft *does* right-size identity permissions from usage — Cloud Infrastructure
Entitlement Management (CIEM), now part of **Defender for Cloud** (the standalone
*Entra Permissions Management* product was retired Oct 2025). CIEM covers service
principals and agent identities and computes a "Permission Creep Index" of
granted-vs-used. So this is **not** "nobody does it" — be precise about the gap.

The gap is *which* usage they can see:

- **CIEM right-sizes from control-plane activity logs** — management actions
  (assign a role, create/delete a resource). ([Defender for Cloud CIEM])
- **Data-plane and tool-level actions are a blind spot.** Reading a blob, fetching
  a secret, or invoking a tool / MCP server is **not** recorded in Azure Activity
  Log (those need separate, per-resource diagnostic logging that's off by default).
  CIEM can flag a *wholly* unused role, but it cannot distinguish
  `Owner`-used-for-reads-only from `Owner`-used-for-writes-and-deletes.
- **AI agents live in the data plane** — they read data, fetch secrets, call tools.
  So CIEM is structurally weakest exactly where agents operate.

`alp` right-sizes from the agent's actual behavior on both layers CIEM's
activity-log model misses: **data-plane resource access** (blob read, secret
fetch) captured in **resource diagnostic logs** (`StorageBlobLogs`, Key Vault
`AuditEvent`), and the **tool / MCP** layer captured in **Foundry traces**. It
**complements** CIEM, not duplicates it.

> **Demonstrated, not designed (validated live 2026-06).** On a real Azure
> subscription we granted a real agent identity (a managed identity) over-broad
> roles — `Storage Blob Data Owner` (account-wide) + `Key Vault Secrets Officer` +
> an unused role on a second account — then had the identity actually read one
> blob and one secret. Those reads showed up in `StorageBlobLogs`
> (`OperationName` GetBlob/ListBlobs, `AuthenticationType` OAuth,
> `RequesterObjectId` == the agent identity) and the Key Vault audit log — exactly
> the data-plane signal CIEM's control-plane model can't see — and `alp`
> reconstructed them straight from the logs and right-sized Owner → read-only on
> the one container actually used. See `scripts/live_dataplane_demo.py`.

[Defender for Cloud CIEM]: https://learn.microsoft.com/en-us/azure/defender-for-cloud/permissions-management

---

## Quickstart (offline — no Azure needed)

The core analysis runs on bundled sample data with **zero** third-party
dependencies.

```bash
pip install -e .
alp analyze --offline
```

You'll see an over-privileged agent (Storage **Owner** account-wide, Key Vault
**Officer** vault-wide, plus an unused role) get right-sized to two narrow,
read-only, resource-scoped roles — a **~95% blast-radius reduction** — with
ready-to-run `az` commands.

Write artifacts (report, JSON, `apply.sh`, `main.bicep`):

```bash
alp analyze --offline --out out
```

Run the tests:

```bash
pip install -e ".[dev]"
pytest -q
```

### Visual UI (best for the pitch)

```bash
pip install -e ".[ui]"
streamlit run app.py
```

Gauges for blast-radius and tool attack surface, color-coded findings, a
before/after view, and downloadable `apply.sh`.

---

## How it works

```
                 ┌─────────────────────────┐
  granted  ──────│ Azure RBAC (agent ID)   │──┐
                 └─────────────────────────┘  │      ┌──────────┐     ┌──────────────┐
                                              ├─────▶│  diff    │────▶│  recommend   │
                 ┌─────────────────────────┐  │      └──────────┘     └──────────────┘
  used     ──────│ data-plane: diag logs   │──┘        findings        scoped roles +
                 │ tools/MCP: Foundry traces│                          az / bicep /
                 └─────────────────────────┘                           report
```

- `granted.py` — reads RBAC role assignments on the agent identity (Azure RBAC).
- `dataplane.py` — reconstructs **data-plane** usage (blob/secret read/list/write/
  delete on specific resources) from resource **diagnostic logs** (`StorageBlobLogs`
  + Key Vault `AuditEvent`), attributed to the agent identity's object id. *The
  CIEM-blind signal — validated live (see `scripts/live_dataplane_demo.py`).*
- `used.py` — the App Insights / tool-call adapter; authoritative tool name+args
  come from the Foundry **run-steps API**. *(See `kql/agent_tool_usage.kql` and
  `scripts/live_demo.py`.)*
- `diff.py` — flags `unused_role`, `overbroad_scope`, `excess_operations`.
- `recommend.py` — picks the narrowest role per used resource, emits `az`/Bicep
  and a blast-radius proxy.
- `tools.py` — right-sizes the **tool / MCP / API-permission** layer (unused
  tools, excess tool scopes) — the dimension CIEM can't see at all.
- `app.py` — Streamlit UI.

The Azure-touching parts are thin adapters; the engine (`diff` + `recommend`) is
pure and unit-tested offline.

---

## Live run (against your Azure)

```bash
pip install -e ".[azure]"
cp .env.example .env    # fill in subscription, agent principal id, workspace id,
                        # and resource group; then load the vars into your shell:
alp analyze --source diagnostics --out out   # data-plane logs (default)
alp analyze --source traces      --out out   # App Insights tool-call history
```

Required access: **Reader** on the subscription (to read role assignments) and
**Log Analytics Reader** on the workspace the resource diagnostic logs flow to.
`--source diagnostics` reconstructs data-plane usage from `StorageBlobLogs` + Key
Vault `AuditEvent`; enable those diagnostic settings on the resources first.

### Demo A — fully live, data-plane (nothing declared)

`scripts/live_dataplane_demo.py` is the **demonstrated** end-to-end run (validated
2026-06): **both** inputs are real Azure data. It reads the agent identity's real
RBAC (`granted.py`) and reconstructs the blob/secret operations it actually
performed from **resource diagnostic logs** (`dataplane.py`) — the exact
data-plane signal CIEM can't see — then right-sizes and writes
`out/dataplane/{report.txt,recommendations.json,apply.sh,main.bicep,live_granted.json,live_used.json}`.

```bash
pip install -e ".[azure]"
export ALP_SUBSCRIPTION_ID=... ALP_PRINCIPAL_ID=<agent-identity-object-id>
export ALP_WORKSPACE_ID=<log-analytics-guid> ALP_DEMO_RG=<resource-group>
export ALP_LOOKBACK_DAYS=1
python scripts/live_dataplane_demo.py
```

### Demo B — live Foundry agent, tool/MCP layer

`scripts/live_demo.py` creates an over-provisioned Foundry agent (5 tools wired, 3
needed), runs read-only tasks, collects exactly what it invoked from the
**run-steps API**, and right-sizes RBAC + tools.

```bash
pip install -e ".[azure,demo]"
export ALP_EP="https://<account>.services.ai.azure.com/api/projects/<project>"
export ALP_MODEL="gpt-5-mini"
export ALP_AI_CONN="<app-insights-connection-string>"   # optional (corroboration)
python scripts/live_demo.py
```

Re-run the analyzer on either run's captured data any time:
`alp analyze --granted out/<run>/live_granted.json --used out/<run>/live_used.json`

---

## Demo runbook (90 seconds)

1. `streamlit run app.py` (or `alp analyze --offline`) — the agent has **Owner**
   (account-wide) but only ever **read one container** and **read one secret**.
2. **Azure RBAC**: findings flag the unused role, over-broad scope, and unused
   write/delete → right-sized to **Reader**, scoped to the exact resources →
   **65 → 3** blast-radius.
3. **Tools / MCP** (the CIEM-blind layer): the agent can call a **payments MCP**
   (charge/refund) and **send email** but never has, and holds **Mail.ReadWrite**
   but only reads → remove the unused tools, downgrade the scopes → **7 → 2** tool
   attack surface.
4. Download `apply.sh` — one command set away from least privilege.

---

## Honest limitations (read before pitching)

- **Tracing is GA for prompt agents only** (hosted/workflow/external in preview) —
  demo on a prompt agent.
- **Cold-start / observation window.** A brand-new agent has no usage history;
  like IAM Access Analyzer, you must observe over a representative window. The
  recommendation is only as good as the window's coverage.
- **Granularity.** v1 right-sizes at **role + resource** level. For storage this
  is demonstrated down to the container (from `StorageBlobLogs` URIs); finer
  action-level splits depend on the diagnostic-log detail each service emits.
- **Data-plane signal — demonstrated live (2026-06).** A real agent identity's
  blob/secret reads were reconstructed straight from `StorageBlobLogs` + Key Vault
  `AuditEvent` (caller object id matched the identity), and right-sized end-to-end.
  This is the exact signal CIEM's control-plane model misses. Caveat: resource
  diagnostic settings are **off by default** and must be enabled per resource, and
  first-event ingestion can lag 10–30 min (Storage was ~3 min, Key Vault slower).
- **Trace schema — validated live (2026-06).** Tool name + arguments are read
  authoritatively from the Foundry **run-steps API** (`step_details.tool_calls`),
  confirmed end-to-end on a real gpt-5-mini agent. App Insights reliably ties
  tool *activity* + outputs to an agent (via `OperationId`) for long-window
  history, but on this SDK version did **not** carry the tool *name* on its
  events — so the collector uses run-steps as the source of truth (see
  `kql/agent_tool_usage.kql`). Data-plane *resource* access (blob read, secret
  get) lives in the target resource's diagnostic logs, not agent traces — which
  is exactly the signal CIEM's activity-log model misses.
- **Role catalog is a curated subset** (Storage + Key Vault) for the demo; a
  production version loads the full Azure role catalog programmatically.
- Concept is **borrowed from AWS IAM Access Analyzer** — novelty is "first for AI
  agents," and the legibility is the point.
- **Complements CIEM, doesn't replace it.** Defender for Cloud CIEM already
  right-sizes agents at the *control-plane* level; `alp`'s contribution is the
  *data-plane / tool-level* granularity CIEM's activity-log model misses. Never
  pitch it as "Microsoft has nothing" — pitch the precise blind spot.

---

## License

MIT. All dependencies are MIT / Azure-commercial — production-clean.
