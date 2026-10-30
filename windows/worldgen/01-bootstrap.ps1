[CmdletBinding()]
param(
    [switch]$AcceptEula,
    [string]$JavaPath = "",
    [string]$CrystalPath = "C:\Apps\Crystal-Launcher"
)

. (Join-Path $PSScriptRoot "_common.ps1")

if (-not $AcceptEula) {
    throw "Najpierw przeczytaj https://aka.ms/MinecraftEULA, a potem uruchom ponownie z -AcceptEula."
}

$worldgenArgs = @(
    "bootstrap",
    "--accept-eula",
    "--crystal-path", $CrystalPath
)
if ($JavaPath) {
    $worldgenArgs += @("--java", $JavaPath)
}

Invoke-MCStegoWorldgen -WorldgenArguments $worldgenArgs
