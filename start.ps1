# Start relay (hidden) + opencode TUI on the deepseek-chat web model.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$here\relay\.websession.json")) {
    Write-Host "no session token. run: python relay\extract.py   (Firefox closed first)" -ForegroundColor Yellow
    exit 1
}

$relay = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*relay2.py*" } |
    Select-Object -First 1

if (-not $relay) {
    Start-Process python -ArgumentList "`"$here\relay\relay2.py`"" -WorkingDirectory $here -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

try {
    $null = Invoke-WebRequest "http://127.0.0.1:20232/v1/models" -TimeoutSec 5
} catch {
    Write-Host "relay not answering on 20232. check relay\relay2.log" -ForegroundColor Red
    exit 1
}

opencode @args
