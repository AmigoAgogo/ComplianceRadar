param(
    [Parameter(Mandatory=$true)]
    [string]$SourceVideo,

    [Parameter(Mandatory=$false)]
    [string]$ProjectRoot = "C:\MINISTERIUM\repos\ComplianceRadar",

    [Parameter(Mandatory=$false)]
    [string]$Version = "review_v1",

    [Parameter(Mandatory=$false)]
    [string]$Status = "review",

    [Parameter(Mandatory=$false)]
    [string]$Note = "Published from verified OpenMontage review package."
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredFile {
    param([string]$Path)
    $resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
        throw "Required file is not a file: $Path"
    }
    return $resolved.Path
}

function Get-VideoProbe {
    param([string]$VideoPath)
    $json = & ffprobe -v error -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate -of json $VideoPath
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        throw "ffprobe failed for $VideoPath"
    }
    return $json | ConvertFrom-Json
}

$source = Resolve-RequiredFile $SourceVideo
$root = Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop
$mediaDir = Join-Path $root "dist\demo_media"
$evidenceDir = Join-Path $root "dist\evidence"
New-Item -ItemType Directory -Force -Path $mediaDir, $evidenceDir | Out-Null

$dateStamp = Get-Date -Format "yyyyMMdd"
$targetName = "ComplianceRadar_Demo_${dateStamp}_${Version}.mp4"
$target = Join-Path $mediaDir $targetName
$latest = Join-Path $mediaDir "ComplianceRadar_Demo_LATEST.mp4"

Copy-Item -LiteralPath $source -Destination $target -Force
Copy-Item -LiteralPath $source -Destination $latest -Force

$probe = Get-VideoProbe $target
$videoStream = $probe.streams | Where-Object { $_.codec_type -eq "video" } | Select-Object -First 1
$audioStream = $probe.streams | Where-Object { $_.codec_type -eq "audio" } | Select-Object -First 1
if (-not $videoStream) { throw "Published file has no video stream: $target" }
if (-not $audioStream) { throw "Published file has no audio stream: $target" }

$file = Get-Item -LiteralPath $target
$manifestPath = Join-Path $root "dist\delivery_manifest.json"
$existing = @()
if (Test-Path -LiteralPath $manifestPath) {
    $raw = Get-Content -LiteralPath $manifestPath -Raw
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        $parsed = $raw | ConvertFrom-Json
        if ($parsed -is [array]) { $existing = @($parsed) } else { $existing = @($parsed) }
    }
}

$entry = [ordered]@{
    project = "ComplianceRadar"
    artifact_type = "demo_video"
    artifact_name = $targetName
    status = $Status
    version = $Version
    source_video = $source
    delivery_path = $target
    latest_alias = $latest
    created_at = (Get-Date).ToString("o")
    source_last_write_time = (Get-Item -LiteralPath $source).LastWriteTime.ToString("o")
    size_bytes = $file.Length
    duration_seconds = [double]$probe.format.duration
    video_codec = $videoStream.codec_name
    audio_codec = $audioStream.codec_name
    width = $videoStream.width
    height = $videoStream.height
    frame_rate = $videoStream.r_frame_rate
    note = $Note
}

$updated = @($existing | Where-Object { $_.delivery_path -ne $target }) + @($entry)
$updated | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$readme = @"
# ComplianceRadar Demo Video Delivery

Latest demo video:

`$latest`

Current dated delivery:

`$target`

Source review package video:

`$source`

Validation:

- Video stream: $($videoStream.codec_name), $($videoStream.width)x$($videoStream.height), $($videoStream.r_frame_rate)
- Audio stream: $($audioStream.codec_name)
- Duration seconds: $($probe.format.duration)
- Size bytes: $($file.Length)
- Manifest: `$manifestPath`

Operational rule:

Every Agent-produced user-facing artifact must be copied or registered into `dist` with a manifest entry before it is reported as delivered.
"@
$readmePath = Join-Path $mediaDir "README_DEMO_VIDEO.md"
$readme | Set-Content -LiteralPath $readmePath -Encoding UTF8

$evidence = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    action = "publish_demo_video"
    source = $source
    target = $target
    latest = $latest
    manifest = $manifestPath
    readme = $readmePath
    ffprobe = $probe
}
$evidencePath = Join-Path $evidenceDir "demo_video_publish_${dateStamp}_${Version}.json"
$evidence | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding UTF8

[ordered]@{
    target = $target
    latest = $latest
    manifest = $manifestPath
    readme = $readmePath
    evidence = $evidencePath
} | ConvertTo-Json -Depth 4
