"""FULLY-LIVE end-to-end demo: every input is real Azure data.

Unlike scripts/live_demo.py (which declares the over-broad RBAC and derives usage
from agent tool calls), this driver proves the DATA-PLANE claim with nothing
declared:

  GRANTED  <- real RBAC role assignments on a real agent identity (Entra), read
              via azure-mgmt-authorization (src/alp/granted.py).
  USED     <- real blob/secret operations the identity actually performed,
              reconstructed from Azure RESOURCE DIAGNOSTIC LOGS -- StorageBlobLogs
              + Key Vault AuditEvent -- the exact data-plane signal CIEM's
              control-plane (Activity Log) model cannot see (src/alp/dataplane.py).

The right-sizing is therefore computed from observed reality on both sides. This
is the "demonstrated, not designed" version of the pitch.

Env (validated student-sub defaults shown):
  ALP_SUBSCRIPTION_ID   subscription id
  ALP_PRINCIPAL_ID      the agent identity's AAD object (principal) id
  ALP_WORKSPACE_ID      Log Analytics workspace GUID the diagnostics flow to
  ALP_DEMO_RG           resource group holding the resources (default rg-alp-demo)
  ALP_LOOKBACK_DAYS     observation window (default 1 for the fresh demo)

Usage:
  python scripts/live_dataplane_demo.py --out out/dataplane
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from alp.dataplane import collect_dataplane  # noqa: E402
from alp.granted import collect_granted  # noqa: E402
from alp.recommend import recommend  # noqa: E402


def _write_artifacts(out_dir: Path, result, granted, used) -> None:
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
    # Capture the real inputs so the analysis is reproducible offline.
    (out_dir / "live_granted.json").write_text(
        json.dumps(
            {
                "principal_id": result.principal_id,
                "granted": [
                    {
                        "role_name": g.role_name,
                        "service": g.service,
                        "scope": g.scope,
                        "data_actions": g.data_actions,
                    }
                    for g in granted
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "live_used.json").write_text(
        json.dumps(
            {
                "used": [
                    {
                        "service": u.service,
                        "audience": u.audience,
                        "resource_id": u.resource_id,
                        "operation": u.operation,
                        "data_action": u.data_action,
                        "count": u.count,
                    }
                    for u in used
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fully-live data-plane least-privilege demo.")
    parser.add_argument("--out", default="out/dataplane", help="Artifact output dir.")
    args = parser.parse_args(argv)

    sub = os.environ["ALP_SUBSCRIPTION_ID"]
    pid = os.environ["ALP_PRINCIPAL_ID"]
    ws = os.environ["ALP_WORKSPACE_ID"]
    rg = os.environ.get("ALP_DEMO_RG", "rg-alp-demo")
    lookback = int(os.environ.get("ALP_LOOKBACK_DAYS", "1"))

    print(f"\n[1/3] Reading GRANTED RBAC from the live agent identity {pid}")
    granted = collect_granted(sub, pid)
    for g in granted:
        print(f"      - {g.role_name}  @  ...{g.scope[-60:]}")
    if not granted:
        print("      (no role assignments found -- check ALP_PRINCIPAL_ID)")

    print(f"\n[2/3] Reading USED operations from RESOURCE DIAGNOSTIC LOGS "
          f"(last {lookback}d)")
    print("      sources: StorageBlobLogs + Key Vault AuditEvent "
          "(the data-plane signal CIEM can't see)")
    used = collect_dataplane(ws, pid, sub, rg, lookback)
    for u in used:
        print(f"      - {u.operation:5s} x{u.count}  ...{u.resource_id[-70:]}")
    if not used:
        print("      (no data-plane operations found yet -- diagnostic-log "
              "ingestion can lag 10-20 min after the reads)")

    print("\n[3/3] Right-sizing granted-vs-used (RBAC, from real logs)")
    result = recommend(pid, granted, used, granted_tools=[], used_tools=[])

    out_dir = Path(args.out)
    _write_artifacts(out_dir, result, granted, used)

    print("\n" + "=" * 78)
    print(result.report)
    print("=" * 78)
    print(f"\nArtifacts + captured real inputs written to {out_dir}/")
    print("  Reproduce offline:  alp analyze "
          f"--granted {out_dir}/live_granted.json --used {out_dir}/live_used.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
