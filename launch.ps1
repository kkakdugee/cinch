# Cinch demo launcher.
# Opens the live backend in its own console window (your "proof" terminal — every
# Azure RBAC read, KQL log query, and `az` apply command prints there as it runs),
# then opens the dashboard in your browser.
#
#   ./launch.ps1
#
# The agent identity / workspace / resources come from demo.config.ps1 (gitignored).
# Copy demo.config.example.ps1 to demo.config.ps1 and fill in your values first.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$cfgPath = Join-Path $root "demo.config.ps1"
if (-not (Test-Path $cfgPath)) {
  Write-Error "Missing demo.config.ps1 — copy demo.config.example.ps1 to demo.config.ps1 and fill in your Azure values."
  exit 1
}
. $cfgPath

# --- demo target (the live agent identity Cinch analyzes) ---
$envVars = @{
  ALP_SUBSCRIPTION_ID = $Cfg.SubscriptionId
  ALP_PRINCIPAL_ID    = $Cfg.AgentObjectId
  ALP_AGENT_NAME      = $Cfg.AgentName
  ALP_AGENT_ROLE      = $Cfg.AgentRole
  ALP_WORKSPACE_ID    = $Cfg.WorkspaceId
  ALP_DEMO_RG         = $Cfg.ResourceGroup
  ALP_LOOKBACK_DAYS   = $Cfg.LookbackDays
  # Extra agents for the roster: "name:principalId:role" joined by |
  ALP_AGENTS          = $Cfg.ExtraAgents
}

# Build a command that sets the env in the new window, then runs the server.
$setEnv = ($envVars.GetEnumerator() | ForEach-Object { "`$env:$($_.Key)='$($_.Value)'" }) -join "; "
$inner  = "$setEnv; Set-Location '$root'; python server.py"

Write-Host "Opening the Cinch backend console…" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", $inner

Start-Sleep -Seconds 4
Write-Host "Opening the dashboard at http://127.0.0.1:5000" -ForegroundColor Cyan
Start-Process "http://127.0.0.1:5000"

Write-Host ""
Write-Host "The console window is the live backend. Keep it visible during the demo —" -ForegroundColor DarkGray
Write-Host "it prints the real Azure calls behind every button you press." -ForegroundColor DarkGray
