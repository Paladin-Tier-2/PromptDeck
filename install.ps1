$ErrorActionPreference = "Stop"

$Root = Join-Path $env:LOCALAPPDATA "PromptDeck"
$Venv = Join-Path $Root "venv"
$Bin = Join-Path $Root "bin"

py -m venv $Venv
& (Join-Path $Venv "Scripts\python.exe") -m pip install --upgrade promptdeck-qt
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$Command = Join-Path $Bin "promptdeck.cmd"
Set-Content -Path $Command -Value "@`"$Venv\Scripts\promptdeck.exe`" %*" -Encoding ASCII

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $Bin) {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$Bin", "User")
}
& $Command setup --no-service @args
