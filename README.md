# 🔐 Cinch

**Least privilege for AI agents.** Cinch reads what an agent identity was *granted* on
Azure and what it *actually did*, then right-sizes its permissions down to exactly what it
used.

> Hackathon track: **Security and Trustworthy Systems**.

---

## What it is

When you build an AI agent, you give its identity the access it needs to do its job, and
almost always a lot more than that. Broad Azure roles, whole storage accounts, entire key
vaults, plus tools and MCP servers wired up to get it working. That access rarely gets
tightened back down, because doing it by hand means tracing everything the agent ever
touched.

Cinch does that tracing for you. Point it at an agent identity and it produces a
right-sized, least-privilege replacement: the narrowest Azure role per resource the agent
actually used, as ready-to-run `az` and Bicep commands. The analysis is deterministic, not
model-based, so every recommendation is auditable and reproducible.

## Why it matters

An over-permissioned agent is a concrete attack surface. An agent holding
`Storage Blob Data Owner` account-wide can read, overwrite, and delete every file in the
account, even if its whole job is reading one container. If that agent is compromised (for
example through a prompt injection in a file it reads every day), the attacker inherits
everything the agent could reach, not just what it needed. Least privilege shrinks that
blast radius to almost nothing.

Azure already right-sizes some permissions from usage through CIEM (Cloud Infrastructure
Entitlement Management, now part of Defender for Cloud). The difference is *which* usage it
sees. CIEM computes granted-versus-used from control-plane activity logs: management
actions like assigning a role or creating a resource. But the things an agent actually
does, reading a blob or fetching a secret, are data-plane operations. Those do not appear
in the Azure Activity Log; they go to each resource's own diagnostic logs, which are off by
default. Microsoft's own documentation uses "getting a secret from a key vault" as the
example of a data-plane operation logged separately
([Activity log docs](https://learn.microsoft.com/en-us/azure/azure-monitor/platform/activity-log)).

That is the gap Cinch fills. It right-sizes from the agent's real data-plane behavior, the
layer CIEM's control-plane model does not ingest. It complements CIEM rather than
duplicating it.

## How it works

```
  granted ── Azure RBAC role assignments ──┐
            (on the agent identity)         │
                                            ├──▶ diff ──▶ recommend
  used ──── data-plane diagnostic logs ─────┤          findings   narrowed roles
            (StorageBlobLogs, KV AuditEvent)│                     + az / bicep / report
            + tool/MCP calls (Foundry traces)
```

1. **Granted.** Read the agent identity's Azure RBAC role assignments and resolve each to
   the data-plane actions it permits (`granted.py`).
2. **Used.** Reconstruct what the identity actually did from resource diagnostic logs,
   `StorageBlobLogs` and Key Vault `AuditEvent`, matched to the identity's object id
   (`dataplane.py`). Every blob read and secret fetch is attributed back to the agent.
3. **Diff.** Compare the two and flag `unused_role`, `overbroad_scope`, and
   `excess_operations` (`diff.py`).
4. **Recommend.** For each resource the agent touched, pick the narrowest built-in role
   that covers exactly those operations, cut everything else, and emit `az` commands, a
   Bicep snippet, and a report (`recommend.py`, `role_catalog.py`).

The same idea extends to the tool layer: `tools.py` right-sizes the tools and MCP servers
an agent can call against the ones it actually invoked (from Foundry run history), a
dimension CIEM does not cover at all.

The Azure-touching parts are thin adapters. The engine (`diff` + `recommend`) is pure and
unit-tested offline, so the CLI and the dashboard never diverge.

## How to run

### Offline (no Azure needed)

The core analysis runs on bundled sample data with no third-party dependencies.

```bash
pip install -e .
cinch analyze --offline
```

You will see an over-privileged agent (Storage **Owner** account-wide, Key Vault
**Officer** vault-wide, plus an unused role) get right-sized to two narrow, read-only,
resource-scoped roles. On the sample this cuts a blast-radius proxy from **65 to 3** and
the tool attack surface from **7 to 2**, with ready-to-run `az` commands. Add `--out out`
to write the report, `recommendations.json`, `apply.sh`, and `main.bicep`.

### Dashboard

```bash
pip install -e ".[web]"
python server.py     # then open http://127.0.0.1:5000
```

A three-panel walkthrough, **Granted → Used → Right-sized**, with animated reduction bars
and a downloadable `apply.sh`. It runs the same engine as the CLI. Loads the bundled sample
by default, or scans a live agent when the Azure env vars below are set.

### Live (against your Azure)

```bash
pip install -e ".[azure]"
cp .env.example .env    # fill in the values below, then load them into your shell
cinch analyze           # reads live RBAC + data-plane diagnostic logs
```

Required environment variables:

- `ALP_SUBSCRIPTION_ID`, `ALP_PRINCIPAL_ID` (the agent identity's object id),
  `ALP_WORKSPACE_ID` (the Log Analytics workspace the diagnostic logs flow to).
- `ALP_RESOURCE_GROUP` (or `ALP_DEMO_RG`) for the default `--source diagnostics`.
- `ALP_LOOKBACK_DAYS` is optional (default 30).

Required access: **Reader** on the subscription (to read role assignments) and **Log
Analytics Reader** on the workspace. Enable the `StorageBlobLogs` and Key Vault
`AuditEvent` diagnostic settings on the resources first. `scripts/live_dataplane_demo.py`
is a full end-to-end run that captures both real inputs and writes the artifacts.

### Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Repository layout

```
src/alp/        the analysis engine (granted, dataplane, diff, recommend, tools, ...)
server.py       Flask API for the dashboard
web/            dashboard (plain HTML/CSS/JS)
scripts/        live end-to-end demo drivers
samples/        bundled granted/used JSON for offline mode
kql/            reference KQL for the diagnostic-log queries
tests/          offline unit tests for the engine
```

## License

MIT.
