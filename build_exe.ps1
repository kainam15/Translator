param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$translatorProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location $translatorProjectRoot
try {
    & $PythonCommand -m PyInstaller --noconfirm --clean .\Translator.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建失败，退出码: $LASTEXITCODE"
    }
    Write-Host "构建完成: $translatorProjectRoot\dist\Translator.exe"
}
finally {
    Pop-Location
}
