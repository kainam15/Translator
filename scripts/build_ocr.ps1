param(
    [string]$Python = "",
    [switch]$SkipInstall,
    [switch]$SkipModelDownload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentRoot = Join-Path $projectRoot ".artifacts\ocr-env"
$ocrPython = Join-Path $environmentRoot "Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "ocr-requirements.txt"
$modelSetup = Join-Path $PSScriptRoot "setup_ocr.py"
$distRoot = Join-Path $projectRoot ".artifacts\ocr-dist"
$workRoot = Join-Path $projectRoot ".artifacts\ocr-build"
$specFile = Join-Path $projectRoot "OcrHelper.spec"
$previousNoUserSite = $env:PYTHONNOUSERSITE

Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONNOUSERSITE = "1"
    if (-not (Test-Path -LiteralPath $ocrPython)) {
        if ($Python) {
            & $Python -m venv $environmentRoot
        } elseif (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.11 -m venv $environmentRoot
        } else {
            throw "Python 3.11 is required. Pass its executable with -Python; the helper environment is project-local."
        }
        if ($LASTEXITCODE -ne 0) { throw "Unable to create the isolated OCR environment." }
    }
    & $ocrPython -c "import sys; assert sys.prefix != sys.base_prefix, 'OCR dependencies require an isolated venv'; assert sys.version_info[:2] == (3, 11), 'Use Python 3.11 for this pinned OCR build'"
    if ($LASTEXITCODE -ne 0) { throw "Invalid OCR Python environment." }
    if (-not $SkipInstall) {
        & $ocrPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw "OCR dependency installation failed." }
    }
    if ($SkipModelDownload) {
        & $ocrPython -X utf8 -B $modelSetup --verify-only
    } else {
        & $ocrPython -X utf8 -B $modelSetup
    }
    if ($LASTEXITCODE -ne 0) { throw "OCR model verification failed." }
    & $ocrPython -X utf8 -B -m PyInstaller --noconfirm --clean --distpath $distRoot --workpath $workRoot $specFile
    if ($LASTEXITCODE -ne 0) { throw "OCR helper build failed." }
    $helperPath = Join-Path $distRoot "TranslatorOCR\TranslatorOCR.exe"
    if (-not (Test-Path -LiteralPath $helperPath)) { throw "OCR helper executable was not produced." }
    Write-Output "Built $helperPath"
    Write-Output "Models stay external in .artifacts\ocr-models; this command does not deploy to dist."
} finally {
    $env:PYTHONNOUSERSITE = $previousNoUserSite
    Pop-Location
}
