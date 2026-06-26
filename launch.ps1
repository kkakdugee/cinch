# Cinch demo launcher.
# Opens the live backend in its own console window (your "proof" terminal — every
# Azure RBAC read, KQL log query, and `az` apply command prints there as it runs),
# then opens the dashboard in your browser.
#
#   ./launch.ps1
#
# The env values below are this demo's Azure identifiers (not secrets). Edit them
# to point at a different agent identity / workspace.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# --- demo target (the live agent identity Cinch analyzes) ---
$envVars = @{
  ALP_SUBSCRIPTION_ID = "bae3d5e2-719b-4cc9-8447-f762f0fc0b33"
  ALP_PRINCIPAL_ID    = "60988bd7-de74-4f35-a8b2-ed4c0d7c1177"
  ALP_AGENT_NAME      = "report-reader"
  ALP_WORKSPACE_ID    = "357fb243-654e-488f-8f47-7d6c54ca7ff7"
  ALP_DEMO_RG         = "rg-alp-demo"
  ALP_LOOKBACK_DAYS   = "1"
  # Extra agents for the roster: "name:principalId:role" joined by |
  ALP_AGENTS          = "invoice-bot:14cb280a-6779-45e1-bfdd-a2f2d51b88a8:Processes invoices (dormant)|export-agent:82ad7c16-9a8d-47be-afca-74e504b412b4:Exports data nightly (dormant)"
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
