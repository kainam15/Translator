param(
    [string]$PythonCommand = "python",
    [switch]$Isolated
)

$ErrorActionPreference = "Stop"
$translatorScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$translatorProjectRoot = Split-Path -Parent $translatorScriptDir
if ($Isolated) {
    $translatorDistPath = Join-Path $translatorProjectRoot ".artifacts\dist"
    $translatorWorkPath = Join-Path $translatorProjectRoot ".artifacts\build"
}
else {
    $translatorDistPath = Join-Path $translatorProjectRoot "dist"
    $translatorWorkPath = Join-Path $translatorProjectRoot "build"
}
$translatorExecutable = Join-Path $translatorDistPath "Translator.exe"

Push-Location $translatorProjectRoot
try {
    if (Test-Path -LiteralPath $translatorExecutable) {
        try {
            $translatorLockProbe = [IO.File]::Open(
                $translatorExecutable,
                [IO.FileMode]::Open,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None
            )
            $translatorLockProbe.Dispose()
        }
        catch {
            throw "Cannot replace $translatorExecutable. Exit that Translator instance, then rebuild."
        }
    }

    & $PythonCommand -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $translatorDistPath `
        --workpath $translatorWorkPath `
        .\Translator.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
    Write-Host "Build complete: $translatorExecutable"
}
finally {
    Pop-Location
}
