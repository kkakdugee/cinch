# Exercise the agent's real data-plane reads (run on recording day).
#
# Cinch's "after" (89 -> 3) depends on seeing the agent actually USE a sliver of its
# access. This deploys a one-shot container that runs AS the agent (its user-assigned
# managed identity) and reads exactly the two things its job needs: the used blob and
# the used secret. Those reads land in the resource diagnostic logs attributed to the
# agent identity, which is what Cinch reconstructs.
#
#   ./exercise_reads.ps1
#
# Then wait for ingestion before scanning: storage ~3 min, Key Vault can take longer
# (up to ~45 min on a cold vault). Record once the scan shows both reads.
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

$sub       = $Cfg.SubscriptionId
$rg        = $Cfg.ResourceGroup
$loc       = $Cfg.Location
$clientId  = $Cfg.AgentClientId
$data      = $Cfg.DataStorage
$container = $Cfg.UsedContainer
$blob      = $Cfg.UsedBlob
$vault     = $Cfg.KeyVault
$secret    = $Cfg.UsedSecret
$aci       = "cinch-read-job"
$uamiId    = "/subscriptions/$sub/resourcegroups/$rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$($Cfg.AgentName)"

az account set --subscription $sub | Out-Null

$yaml = @"
apiVersion: 2019-12-01
location: $loc
name: $aci
properties:
  osType: Linux
  restartPolicy: Never
  containers:
  - name: $aci
    properties:
      image: mcr.microsoft.com/azure-cli
      resources:
        requests:
          cpu: 1
          memoryInGB: 1.5
      command:
      - "/bin/bash"
      - "-c"
      - >-
        az login --identity --client-id $clientId -o none;
        for i in 1 2 3; do
        az storage blob list --account-name $data --container-name $container --auth-mode login -o none;
        az storage blob download --account-name $data --container-name $container --name $blob --auth-mode login --file /tmp/r`$i -o none;
        done;
        for i in 1 2 3 4; do az keyvault secret show --vault-name $vault --name $secret -o none; done;
        echo READS_DONE
identity:
  type: UserAssigned
  userAssignedIdentities:
    ${uamiId}: {}
"@

$path = "$env:TEMP\$aci.yaml"
$yaml | Out-File -Encoding ascii $path

Write-Host "Deploying $($Cfg.AgentName) read job..." -ForegroundColor Cyan
az container delete -g $rg --name $aci --yes 2>$null | Out-Null
az container create -g $rg --file $path -o none
Start-Sleep -Seconds 25
Write-Host "Container logs (expect READS_DONE, no 'az login' errors):" -ForegroundColor Cyan
az container logs -g $rg --name $aci
az container delete -g $rg --name $aci --yes 2>$null | Out-Null
Remove-Item $path -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Reads done. Wait for ingestion (storage ~3 min, Key Vault can be longer)," -ForegroundColor Green
Write-Host "then scan $($Cfg.AgentName) in Cinch. The 'used' side should show $container + $secret." -ForegroundColor Green
