$ProjectRoot = "D:\dashboard\nse-dashboard"
$Cloudflared = "C:\Cloudflared\bin\cloudflared.exe"

Write-Host ""
Write-Host "=============================================="
Write-Host "       MarketPulse Public Backend"
Write-Host "=============================================="
Write-Host ""

# --------------------------------------------------
# Check Cloudflared
# --------------------------------------------------

if (!(Test-Path $Cloudflared)) {
    Write-Host "ERROR: cloudflared.exe not found:"
    Write-Host $Cloudflared
    exit 1
}

# --------------------------------------------------
# Start FastAPI
# --------------------------------------------------

Write-Host "Starting FastAPI..."

Start-Process `
    powershell `
    -ArgumentList @(
        "-NoExit",
        "-Command",
        "cd '$ProjectRoot'; uvicorn src.backend.api:app --host 127.0.0.1 --port 8000"
    )

Start-Sleep -Seconds 3

# --------------------------------------------------
# Verify FastAPI
# --------------------------------------------------

try {

    $health = Invoke-WebRequest `
        "http://127.0.0.1:8000/api/health" `
        -UseBasicParsing `
        -TimeoutSec 10

    Write-Host "FastAPI status: $($health.StatusCode)"

}
catch {

    Write-Host ""
    Write-Host "ERROR: FastAPI did not start."
    Write-Host $_
    exit 1
}

# --------------------------------------------------
# Start Cloudflare Quick Tunnel
# --------------------------------------------------

Write-Host ""
Write-Host "Starting Cloudflare Quick Tunnel..."
Write-Host ""

Start-Process `
    powershell `
    -ArgumentList @(
        "-NoExit",
        "-Command",
        "& '$Cloudflared' tunnel --url http://127.0.0.1:8000"
    )

Write-Host ""
Write-Host "=============================================="
Write-Host "FastAPI started."
Write-Host "Cloudflare Tunnel started."
Write-Host "=============================================="
Write-Host ""

Write-Host "IMPORTANT:"
Write-Host "Copy the new trycloudflare.com URL from the"
Write-Host "Cloudflare PowerShell window."
Write-Host ""
Write-Host "Then update:"
Write-Host "$ProjectRoot\.env"
Write-Host ""
Write-Host "VITE_API_BASE_URL=<NEW_URL>"
Write-Host ""