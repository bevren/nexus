$ErrorActionPreference = "Stop"

$kernelDir = $PSScriptRoot
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $kernelDir "..\.."))
$entrypoint = Join-Path $repoRoot "index.js"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required but 'node' was not found on PATH."
}
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw "Could not find Nexus entrypoint: $entrypoint"
}

Push-Location -LiteralPath $kernelDir
try {
    python .\check_environment.py
    if ($LASTEXITCODE -ne 0) {
        throw "ARC prerequisites are not ready. Fix the preflight errors, then launch again."
    }
} finally {
    Pop-Location
}

Push-Location -LiteralPath $repoRoot
try {
    & node $entrypoint --solve $kernelDir
} finally {
    Pop-Location
}
