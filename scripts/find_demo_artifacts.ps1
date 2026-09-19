param(
    [Parameter(Mandatory=$false)]
    [string[]]$Roots = @(
        "C:\MINISTERIUM\repos\ComplianceRadar",
        "D:\Openmontage",
        "D:\VistaMediaTank",
        "E:\VistaMediaTank"
    ),

    [Parameter(Mandatory=$false)]
    [string]$OutputPath = "C:\MINISTERIUM\repos\ComplianceRadar\dist\evidence\demo_artifact_search_latest.txt"
)

$ErrorActionPreference = "Stop"
$extensions = @(".mp4", ".mov", ".mkv", ".avi", ".webm", ".json", ".md")
$results = New-Object System.Collections.Generic.List[string]
$rg = Get-Command rg -ErrorAction SilentlyContinue

foreach ($root in $Roots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $candidatePaths = @()
    if ($rg) {
        $candidatePaths = & $rg.Source --files --hidden --no-ignore $root 2>$null |
            Where-Object {
                $lower = $_.ToLowerInvariant()
                ($lower.Contains("complianceradar") -or $lower.Contains("compliance_radar") -or $lower.Contains("compliance radar")) -and
                ($extensions | Where-Object { $lower.EndsWith($_) })
            }
    } else {
        $candidatePaths = Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $name = $_.FullName.ToLowerInvariant()
                $isSupported = $extensions -contains $_.Extension.ToLowerInvariant()
                $isComplianceRadar = $name.Contains("complianceradar") -or $name.Contains("compliance_radar") -or $name.Contains("compliance radar")
                $isSupported -and $isComplianceRadar
            } |
            ForEach-Object { $_.FullName }
    }

    $candidatePaths |
        ForEach-Object {
            $path = $_
            if (-not [System.IO.Path]::IsPathRooted($path)) {
                $path = Join-Path $root $path
            }
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                Get-Item -LiteralPath $path
            }
        } |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            $results.Add(("{0}`t{1}`t{2}`t{3}" -f $_.FullName, $_.Length, $_.CreationTime.ToString("o"), $_.LastWriteTime.ToString("o")))
        }
}

$header = @(
    "ComplianceRadar artifact search",
    "Generated: $(Get-Date -Format o)",
    "Roots: $($Roots -join '; ')",
    "Columns: FullName, SizeBytes, CreationTime, LastWriteTime",
    ""
)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
($header + $results) | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Output $OutputPath
