[CmdletBinding()]
param(
    [string]$JavaPath = "",
    [string]$CrystalPath = "C:\Apps\Crystal-Launcher"
)

. (Join-Path $PSScriptRoot "_common.ps1")

$worldgenArgs = @(
    "doctor",
    "--crystal-path", $CrystalPath,
    "--output", "runs/worldgen/doctor.json"
)
if ($JavaPath) {
    $worldgenArgs += @("--java", $JavaPath)
}

Invoke-MCStegoWorldgen -WorldgenArguments $worldgenArgs
