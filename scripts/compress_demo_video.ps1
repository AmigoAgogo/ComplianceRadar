param(
    [Parameter(Mandatory=$false)]
    [string]$InputVideo = "C:\MINISTERIUM\repos\ComplianceRadar\dist\demo_media\ComplianceRadar_Demo_LATEST.mp4",

    [Parameter(Mandatory=$false)]
    [string]$OutputVideo = "C:\MINISTERIUM\repos\ComplianceRadar\dist\demo_media\ComplianceRadar_Demo_LATEST_compressed_1080p_hevc.mp4",

    [Parameter(Mandatory=$false)]
    [string]$ProjectRoot = "C:\MINISTERIUM\repos\ComplianceRadar",

    [Parameter(Mandatory=$false)]
    [switch]$ForceEncode
)

$ErrorActionPreference = "Stop"

function Get-VideoProbe {
    param([string]$VideoPath)
    $json = & ffprobe -v error -show_entries format=duration,size:stream=index,codec_type,codec_name,width,height,r_frame_rate -of json $VideoPath
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        throw "ffprobe failed for $VideoPath"
    }
    return $json | ConvertFrom-Json
}

if (-not (Test-Path -LiteralPath $InputVideo -PathType Leaf)) {
    throw "Input video not found: $InputVideo"
}

if ($ForceEncode -or -not (Test-Path -LiteralPath $OutputVideo -PathType Leaf)) {
    & ffmpeg -y -i $InputVideo -c:v libx265 -preset medium -crf 28 -tag:v hvc1 -c:a aac -b:a 96k -movflags +faststart $OutputVideo
    if ($LASTEXITCODE -ne 0) {
        throw "ffmpeg compression failed for $InputVideo"
    }
}

$inputProbe = Get-VideoProbe $InputVideo
$outputProbe = Get-VideoProbe $OutputVideo
$inputVideoStream = $inputProbe.streams | Where-Object { $_.codec_type -eq "video" } | Select-Object -First 1
$outputVideoStream = $outputProbe.streams | Where-Object { $_.codec_type -eq "video" } | Select-Object -First 1
$outputAudioStream = $outputProbe.streams | Where-Object { $_.codec_type -eq "audio" } | Select-Object -First 1
if (-not $outputVideoStream) { throw "Compressed file has no video stream: $OutputVideo" }
if (-not $outputAudioStream) { throw "Compressed file has no audio stream: $OutputVideo" }
if ($inputVideoStream.width -ne $outputVideoStream.width -or $inputVideoStream.height -ne $outputVideoStream.height) {
    throw "Compressed file changed resolution from $($inputVideoStream.width)x$($inputVideoStream.height) to $($outputVideoStream.width)x$($outputVideoStream.height)"
}

$root = Resolve-Path -LiteralPath $ProjectRoot
$manifestPath = Join-Path $root "dist\delivery_manifest.json"
$evidenceDir = Join-Path $root "dist\evidence"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

$inputFile = Get-Item -LiteralPath $InputVideo
$outputFile = Get-Item -LiteralPath $OutputVideo
$ratio = [math]::Round((1 - ($outputFile.Length / $inputFile.Length)) * 100, 2)

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
    artifact_type = "demo_video_compressed"
    artifact_name = (Split-Path -Leaf $OutputVideo)
    status = "delivery_ready"
    version = "compressed_1080p_hevc"
    source_video = (Resolve-Path -LiteralPath $InputVideo).Path
    delivery_path = (Resolve-Path -LiteralPath $OutputVideo).Path
    created_at = (Get-Date).ToString("o")
    size_bytes = $outputFile.Length
    source_size_bytes = $inputFile.Length
    size_reduction_percent = $ratio
    duration_seconds = [double]$outputProbe.format.duration
    video_codec = $outputVideoStream.codec_name
    audio_codec = $outputAudioStream.codec_name
    width = $outputVideoStream.width
    height = $outputVideoStream.height
    frame_rate = $outputVideoStream.r_frame_rate
    note = "Compressed without reducing resolution; HEVC/H.265 used for smaller review delivery file."
}

$updated = @($existing | Where-Object { $_.delivery_path -ne $entry.delivery_path }) + @($entry)
$updated | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$evidencePath = Join-Path $evidenceDir "demo_video_compression_${stamp}.json"
[ordered]@{
    generated_at = (Get-Date).ToString("o")
    action = "compress_demo_video"
    input_video = (Resolve-Path -LiteralPath $InputVideo).Path
    output_video = (Resolve-Path -LiteralPath $OutputVideo).Path
    input_probe = $inputProbe
    output_probe = $outputProbe
    size_reduction_percent = $ratio
    manifest = $manifestPath
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $evidencePath -Encoding UTF8

[ordered]@{
    output = (Resolve-Path -LiteralPath $OutputVideo).Path
    input_size_bytes = $inputFile.Length
    output_size_bytes = $outputFile.Length
    size_reduction_percent = $ratio
    manifest = $manifestPath
    evidence = $evidencePath
} | ConvertTo-Json -Depth 4
