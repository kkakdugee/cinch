"""Runtime configuration loaded from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    subscription_id: str
    principal_id: str  # the agent identity's Entra object (principal) id
    workspace_id: str  # Log Analytics workspace GUID backing the App Insights resource
    resource_group: str = ""  # holds the resources (for data-plane resource-id mapping)
    lookback_days: int = 30

    @staticmethod
    def from_env() -> "Config":
        required = ("ALP_SUBSCRIPTION_ID", "ALP_PRINCIPAL_ID", "ALP_WORKSPACE_ID")
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise SystemExit(
                "Missing required environment variables: "
                + ", ".join(missing)
                + " (copy .env.example to .env and fill it in)"
            )
        return Config(
            subscription_id=os.environ["ALP_SUBSCRIPTION_ID"],
            principal_id=os.environ["ALP_PRINCIPAL_ID"],
            workspace_id=os.environ["ALP_WORKSPACE_ID"],
            resource_group=os.getenv("ALP_RESOURCE_GROUP", os.getenv("ALP_DEMO_RG", "")),
            lookback_days=int(os.getenv("ALP_LOOKBACK_DAYS", "30")),
        )
