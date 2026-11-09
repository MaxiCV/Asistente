param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Executable (código $LASTEXITCODE)" }
}

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    Invoke-Checked $Python @('-m', 'venv', '.venv')
}
Invoke-Checked '.venv/Scripts/python.exe' @('-m', 'pip', 'install', '--cache-dir', '.cache/pip', 'uv==0.13.7')
Invoke-Checked '.venv/Scripts/uv.exe' @('sync', '--frozen')
Invoke-Checked '.venv/Scripts/python.exe' @('-m', 'app.cli', 'init')
Invoke-Checked 'npm.cmd' @('--prefix', 'frontend', 'ci', '--cache', '.cache/npm', '--no-fund', '--no-audit')
Write-Output 'Entorno instalado. Configura OPENALEX_API_KEY en .env y sigue el primer arranque del README.'

