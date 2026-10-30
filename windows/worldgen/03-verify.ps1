[CmdletBinding()]
param(
    [ValidateSet("train", "validation", "test")]
    [string]$Split = "train",
    [string]$WorldId = "",
    [switch]$UnlockTestSet,
    [string]$TestKeyPath = "",
    [switch]$SkipHashes
)

. (Join-Path $PSScriptRoot "_common.ps1")

$reportPath = "runs/worldgen/verification-$Split.json"
$worldgenArgs = @(
    "verify",
    "--split", $Split,
    "--output", $reportPath
)
if ($WorldId) {
    $worldgenArgs += @("--world-id", $WorldId)
}
if ($SkipHashes) {
    $worldgenArgs += "--skip-hashes"
}
if ($Split -eq "test") {
    if (-not $UnlockTestSet -or -not $TestKeyPath) {
        throw "Weryfikacja testu wymaga -UnlockTestSet i -TestKeyPath."
    }
    $worldgenArgs += @("--unlock-test-set", "--test-key", $TestKeyPath)
}

Invoke-MCStegoWorldgen -WorldgenArguments $worldgenArgs
