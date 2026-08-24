$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\Dashboard\nse-dashboard"
$Python = "python"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "nse_ingestion.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Set-Location $ProjectRoot

"============================================================" | Out-File $LogFile -Append
"MarketPulse NSE ingestion started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $LogFile -Append

try {
    & $Python "src\backend\nse_ingestion.py" 2>&1 |
        Tee-Object -FilePath $LogFile -Append

    if ($LASTEXITCODE -ne 0) {
        throw "NSE ingestion exited with code $LASTEXITCODE"
    }

    "MarketPulse NSE ingestion completed successfully: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" |
        Out-File $LogFile -Append
}
catch {
    "NSE ingestion FAILED: $($_.Exception.Message)" |
        Out-File $LogFile -Append

    exit 1
}