"""Command-line entrypoint.

Examples
--------
Offline (no Azure, uses bundled samples) -- great for the demo and CI:
    cinch analyze --offline

From explicit JSON files:
    cinch analyze --granted granted.json --used used.json

Live against Azure (needs env vars + ``pip install -e ".[azure]"``):
    cinch analyze
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import GrantedRole, GrantedTool, UsedOperation, UsedTool
from .recommend import recommend


def _find(relative: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.exists():
            return candidate
    return None


def _load_granted(path: Path) -> tuple[str, list[GrantedRole], list[GrantedTool]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    principal = data.get("principal_id", "")
    granted = [GrantedRole.from_dict(d) for d in data.get("granted", [])]
    tools = [GrantedTool.from_dict(d) for d in data.get("granted_tools", [])]
    return principal, granted, tools


def _load_used(path: Path) -> tuple[list[UsedOperation], list[UsedTool]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    used = [UsedOperation.from_dict(d) for d in data.get("used", [])]
    tools = [UsedTool.from_dict(d) for d in data.get("used_tools", [])]
    return used, tools


def _gather(args):
    if args.offline:
        g = _find("samples/granted_sample.json")
        u = _find("samples/usage_sample.json")
        if not g or not u:
            raise SystemExit("Sample files not found; run from the repo tree.")
        principal, granted, gtools = _load_granted(g)
        used, utools = _load_used(u)
        return principal, granted, used, gtools, utools

    if args.granted and args.used:
        principal, granted, gtools = _load_granted(Path(args.granted))
        used, utools = _load_used(Path(args.used))
        return principal, granted, used, gtools, utools

    # Live mode. (Tool/MCP collection from agent config + traces is future work;
    # RBAC right-sizing runs against live Azure today.)
    from .config import Config
    from .granted import collect_granted

    cfg = Config.from_env()
    granted = collect_granted(cfg.subscription_id, cfg.principal_id)

    if getattr(args, "source", "diagnostics") == "diagnostics":
        # Recommended: reconstruct data-plane usage from resource diagnostic logs
        # (StorageBlobLogs + Key Vault AuditEvent) -- the CIEM-blind signal.
        from .dataplane import collect_dataplane

        if not cfg.resource_group:
            raise SystemExit(
                "ALP_RESOURCE_GROUP (or ALP_DEMO_RG) is required for "
                "--source diagnostics (used to build resource ids)."
            )
        used = collect_dataplane(
            cfg.workspace_id,
            cfg.principal_id,
            cfg.subscription_id,
            cfg.resource_group,
            cfg.lookback_days,
        )
    else:
        from .used import collect_used

        used = collect_used(cfg.workspace_id, cfg.principal_id, cfg.lookback_days)

    return cfg.principal_id, granted, used, [], []


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cinch", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze an agent's granted vs. used access.")
    analyze.add_argument("--offline", action="store_true", help="Use bundled samples (no Azure).")
    analyze.add_argument("--granted", help="Path to a granted-roles JSON file.")
    analyze.add_argument("--used", help="Path to a used-operations JSON file.")
    analyze.add_argument(
        "--source",
        choices=("diagnostics", "traces"),
        default="diagnostics",
        help="Live usage source: 'diagnostics' (resource diagnostic logs -- the "
        "data-plane signal CIEM can't see; default) or 'traces' (App Insights).",
    )
    analyze.add_argument("--out", help="Directory to write report + apply.sh + main.bicep.")
    analyze.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    args = parser.parse_args(argv)

    if args.command == "analyze":
        principal, granted, used, granted_tools, used_tools = _gather(args)
        result = recommend(
            principal,
            granted,
            used,
            granted_tools=granted_tools,
            used_tools=used_tools,
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.report)
        if args.out:
            _write_artifacts(Path(args.out), result)
            print(f"\nArtifacts written to {args.out}/")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
