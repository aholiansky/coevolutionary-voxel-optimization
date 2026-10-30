[CmdletBinding()]
param(
    [ValidateSet("train", "validation", "test")]
    [string]$Split = "train",
    [string]$WorldId = "",
    [switch]$UnlockTestSet,
    [string]$TestKeyPath = "",
    [string]$JavaPath = "",
    [string]$CrystalPath = "C:\Apps\Crystal-Launcher"
)

. (Join-Path $PSScriptRoot "_common.ps1")

$worldgenArgs = @(
    "generate",
    "--split", $Split,
    "--crystal-path", $CrystalPath
)
if ($WorldId) {
    $worldgenArgs += @("--world-id", $WorldId)
}
if ($JavaPath) {
    $worldgenArgs += @("--java", $JavaPath)
}
if ($Split -eq "test") {
    if (-not $UnlockTestSet -or -not $TestKeyPath) {
        throw "Test is sealed. Use -UnlockTestSet and -TestKeyPath only for final evaluation."
    }
    $worldgenArgs += @("--unlock-test-set", "--test-key", $TestKeyPath)
}

Invoke-MCStegoWorldgen -WorldgenArguments $worldgenArgs
