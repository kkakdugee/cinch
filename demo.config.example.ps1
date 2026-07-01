# Cinch demo configuration — template.
#
# Copy this to demo.config.ps1 and fill in your own Azure values:
#
#   Copy-Item demo.config.example.ps1 demo.config.ps1
#   # then edit demo.config.ps1
#
# demo.config.ps1 is gitignored, so your Azure identifiers stay local and the repo
# stays portable and agent-agnostic. These are identifiers and resource names, not
# secrets (they're useless without Azure auth + RBAC), but there's no reason to
# commit them. launch.ps1 / demo_reset.ps1 / exercise_reads.ps1 all read this file.

$Cfg = @{
  # --- Azure context ---
  SubscriptionId = "00000000-0000-0000-0000-000000000000"
  ResourceGroup  = "rg-your-demo"
  WorkspaceId    = "00000000-0000-0000-0000-000000000000"  # Log Analytics workspace GUID
  Location       = "eastus2"

  # --- the agent identity Cinch analyzes ---
  AgentName      = "your-agent"                             # display name (and the UAMI resource name)
  AgentRole      = "AI agent"                               # one-line description shown in the roster
  AgentObjectId  = "00000000-0000-0000-0000-000000000000"  # managed identity principal / object id
  AgentClientId  = "00000000-0000-0000-0000-000000000000"  # managed identity client id (for exercise_reads)

  LookbackDays   = "1"

  # Extra agents to show in the roster: "name:principalId:role" joined by "|". Optional.
  ExtraAgents    = ""

  # --- demo resources (used by demo_reset.ps1 / exercise_reads.ps1) ---
  DataStorage    = "yourdatastorage"     # primary storage account
  ArchiveStorage = "yourarchivestorage"  # a second storage account (unused, for the "before" wall)
  KeyVault       = "your-keyvault"
  UsedContainer  = "model-results"       # the one container the agent actually reads
  UsedBlob       = "latest-results.json" # the blob it reads
  UsedSecret     = "model-api-key"       # the one secret it actually reads
  # Unused containers granted broadly to build the over-permissioned "before" wall.
  WallContainers = @("training-data", "model-checkpoints", "experiment-runs", "eval-results", "model-registry")
}
