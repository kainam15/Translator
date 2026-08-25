param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$translatorScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$translatorProjectRoot = Split-Path -Parent $translatorScriptDir
$translatorExecutable = Join-Path $translatorProjectRoot "dist\Translator.exe"

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
            throw "Cannot replace dist\Translator.exe. Exit Translator from its tray menu, then rebuild."
        }
    }

    & $PythonCommand -m PyInstaller --noconfirm --clean .\Translator.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
    Write-Host "Build complete: $translatorExecutable"
}
finally {
    Pop-Location
}
