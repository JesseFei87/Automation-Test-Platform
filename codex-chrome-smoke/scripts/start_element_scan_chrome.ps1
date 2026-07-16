param(
    [int]$Port = 9222
)

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profilePath = Join-Path $PSScriptRoot "..\platform-data\chrome-element-scan"

if (-not (Test-Path -LiteralPath $chromePath)) {
    throw "Google Chrome was not found at $chromePath"
}

New-Item -ItemType Directory -Force -Path $profilePath | Out-Null
Start-Process -FilePath $chromePath -ArgumentList @(
    "--remote-debugging-address=127.0.0.1",
    "--remote-debugging-port=$Port",
    "--user-data-dir=$profilePath"
)

Write-Host "Dedicated element-scan Chrome started on http://127.0.0.1:$Port"
Write-Host "Sign in to ICM in that Chrome window, then start the element knowledge refresh."
