# Cinch demo reset — restore Atlas to the broad, over-permissioned "before" state.
#
# Run this before each demo take (and before recording the live demo). It clears
# the agent's current role assignments and re-grants the wall of broad roles, so the
# live right-size has the full pile to cut down.
#
#   ./demo_reset.ps1
#
# Reads Azure identifiers/resource names from demo.config.ps1 (gitignored).
# Copy demo.config.example.ps1 to demo.config.ps1 and fill in your values first.

$ErrorActionPreference = "Stop"

$cfgPath = Join-Path $PSScriptRoot "demo.config.ps1"
if (-not (Test-Path $cfgPath)) {
  Write-Error "Missing demo.config.ps1 — copy demo.config.example.ps1 to demo.config.ps1 and fill in your Azure values."
  exit 1
}
. $cfgPath

$sub      = $Cfg.SubscriptionId
$rg       = $Cfg.ResourceGroup
$data     = $Cfg.DataStorage      # primary storage account
$archive  = $Cfg.ArchiveStorage   # archive storage account
$vault    = $Cfg.KeyVault         # key vault
$atlas    = $Cfg.AgentObjectId    # agent identity object id

az account set --subscription $sub | Out-Null

$base   = "/subscriptions/$sub/resourceGroups/$rg/providers"
$dataAcc = "$base/Microsoft.Storage/storageAccounts/$data"
$archAcc = "$base/Microsoft.Storage/storageAccounts/$archive"
$vaultId = "$base/Microsoft.KeyVault/vaults/$vault"
function Container($name) { "$dataAcc/blobServices/default/containers/$name" }

# The broad "before" wall: 8 over-scoped grants. Two are the ones the agent actually
# uses (account-wide Owner over storage, vault-wide Officer over secrets) and get
# narrowed by Cinch; the rest are never used and get cut.
$grants = @(
  @{ role = "Storage Blob Data Owner";       scope = $dataAcc },
  @{ role = "Key Vault Secrets Officer";      scope = $vaultId },
  @{ role = "Storage Blob Data Contributor";  scope = $archAcc }
)
foreach ($c in $Cfg.WallContainers) {
  $role = if ($c -eq "eval-results") { "Storage Blob Data Contributor" } else { "Storage Blob Data Owner" }
  $grants += @{ role = $role; scope = (Container $c) }
}

Write-Host "Clearing $($Cfg.AgentName)'s current role assignments..." -ForegroundColor Cyan
$existing = az role assignment list --assignee $atlas --all --query "[].id" -o tsv 2>$null
foreach ($id in $existing) {
  if ($id) { az role assignment delete --ids $id 2>$null | Out-Null }
}

Write-Host "Granting the broad 'before' wall ($($grants.Count) roles)..." -ForegroundColor Cyan
foreach ($g in $grants) {
  az role assignment create `
    --assignee-object-id $atlas `
    --assignee-principal-type ServicePrincipal `
    --role $g.role `
    --scope $g.scope 2>$null | Out-Null
  Write-Host ("  + {0,-32} {1}" -f $g.role, ($g.scope -split "/")[-1]) -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "$($Cfg.AgentName) is back to the broad 'before' state. Verify:" -ForegroundColor Green
az role assignment list --assignee $atlas --all --query "length(@)" -o tsv 2>$null |
  ForEach-Object { Write-Host "  $_ role assignments on $($Cfg.AgentName)" -ForegroundColor Green }
