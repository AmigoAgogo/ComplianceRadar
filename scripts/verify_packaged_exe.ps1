$ErrorActionPreference = "Stop"

$exe = "C:\MINISTERIUM\repos\ComplianceRadar\dist\ComplianceRadarFinal.exe"
$process = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden

try {
    $health = $null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 750
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
            break
        }
        catch {
        }
    }

    if (-not $health) {
        throw "Packaged exe did not expose /api/health on port 8765."
    }

    $sync = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8765/api/sources/sync" `
        -Method Post `
        -ContentType "application/json" `
        -Body '{"period":"today"}' `
        -TimeoutSec 80

    [ordered]@{
        process_id = $process.Id
        health = $health
        synced_count = $sync.synced_count
        processed_sources = $sync.processed_sources
        source_results = $sync.source_results
        errors = $sync.errors
        run_receipt_path = $sync.run_receipt_path
    } | ConvertTo-Json -Depth 8
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force
    }
}
