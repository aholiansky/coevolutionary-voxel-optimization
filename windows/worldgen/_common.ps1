Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-MCStegoProjectRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Invoke-MCStegoWorldgen {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$WorldgenArguments
    )

    $projectRoot = Get-MCStegoProjectRoot
    $entrypoint = Join-Path $projectRoot "scripts\worldgen.py"
    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        $pythonExecutable = $pyLauncher.Source
        & $pythonExecutable -3 $entrypoint --project-root $projectRoot @WorldgenArguments
    }
    else {
        $python = Get-Command "python" -ErrorAction SilentlyContinue
        if ($null -eq $python) {
            throw "Nie znaleziono Pythona 3.10+. Zainstaluj Pythona i uruchom skrypt ponownie."
        }
        $pythonExecutable = $python.Source
        & $pythonExecutable $entrypoint --project-root $projectRoot @WorldgenArguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Worldgen command exited with code $LASTEXITCODE."
    }
}
