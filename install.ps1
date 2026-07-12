$ErrorActionPreference = "Stop"

$Root = Join-Path $env:LOCALAPPDATA "PromptDeck"
$Venv = Join-Path $Root "venv"
$Bin = Join-Path $Root "bin"
$Package = if ($env:PROMPTDECK_PACKAGE) { $env:PROMPTDECK_PACKAGE } else { "promptdeck-qt" }

Write-Host "Installing PromptDeck..."
py -m venv $Venv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Venv "Scripts\python.exe") -m pip install --quiet --upgrade $Package
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$Command = Join-Path $Bin "promptdeck.cmd"
Set-Content -Path $Command -Value "@`"$Venv\Scripts\promptdeck.exe`" %*" -Encoding ASCII

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $Bin) {
    $NewPath = if ([string]::IsNullOrWhiteSpace($UserPath)) { $Bin } else { "$UserPath;$Bin" }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
}
$env:Path = "$Bin;$env:Path"
& $Command setup --no-service @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "`nPromptDeck is ready."
