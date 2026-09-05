param(
    [string]$PythonCommand = "python",
    [switch]$Isolated,
    [switch]$WithOcr
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
    if ($WithOcr) {
        $translatorOcrSource = Join-Path $translatorProjectRoot ".artifacts\ocr-dist\TranslatorOCR"
        $translatorModelSource = Join-Path $translatorProjectRoot ".artifacts\ocr-models"
        if (-not (Test-Path -LiteralPath (Join-Path $translatorOcrSource "TranslatorOCR.exe"))) {
            throw "Build the OCR helper first: .\scripts\build_ocr.ps1"
        }
        & $PythonCommand -X utf8 -B .\scripts\setup_ocr.py --verify-only
        if ($LASTEXITCODE -ne 0) { throw "OCR model verification failed." }
        $translatorOcrDestination = Join-Path $translatorDistPath "ocr"
        $translatorOcrExecutable = Join-Path $translatorOcrDestination "TranslatorOCR.exe"
        if (Test-Path -LiteralPath $translatorOcrExecutable) {
            $translatorOcrProbe = [IO.File]::Open(
                $translatorOcrExecutable, [IO.FileMode]::Open,
                [IO.FileAccess]::ReadWrite, [IO.FileShare]::None
            )
            $translatorOcrProbe.Dispose()
        }
    }
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
    if ($WithOcr) {
        New-Item -ItemType Directory -Path $translatorOcrDestination -Force | Out-Null
        Get-ChildItem -LiteralPath $translatorOcrSource | Copy-Item -Destination $translatorOcrDestination -Recurse -Force
        $translatorModelDestination = Join-Path $translatorOcrDestination "models"
        New-Item -ItemType Directory -Path $translatorModelDestination -Force | Out-Null
        Get-ChildItem -LiteralPath $translatorModelSource | Copy-Item -Destination $translatorModelDestination -Recurse -Force
        Copy-Item -LiteralPath (Join-Path $translatorProjectRoot "docs\ocr-models.md") -Destination (Join-Path $translatorOcrDestination "MODEL-NOTICES.md") -Force
        Write-Host "OCR helper and models: $translatorOcrDestination"
    }
    Write-Host "Build complete: $translatorExecutable"
}
finally {
    Pop-Location
}
