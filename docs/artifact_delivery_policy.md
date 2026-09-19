# ComplianceRadar Artifact Delivery Policy

## Purpose

ComplianceRadar artifacts must be findable after the producing Agent finishes work. Runtime folders remain useful for production, but user-facing deliverables must also be registered in the ComplianceRadar delivery area.

## Incident Root Cause

The demo video was not lost. It was produced under `D:\Openmontage\runtime\compliance_radar_demo_20260708`, while later searches focused on the ComplianceRadar repository, desktop folders, temporary folders, and VistaMediaTank locations. The original ScreenSketch recording referenced by the production manifest was no longer present, and the active review video used a production-oriented filename rather than a direct user-facing name.

## Required Delivery Locations

- User-facing demo media: `C:\MINISTERIUM\repos\ComplianceRadar\dist\demo_media`
- Machine-readable delivery index: `C:\MINISTERIUM\repos\ComplianceRadar\dist\delivery_manifest.json`
- Verification evidence: `C:\MINISTERIUM\repos\ComplianceRadar\dist\evidence`
- Recovery/search tooling: `C:\MINISTERIUM\repos\ComplianceRadar\scripts`

## Required Delivery Gate

Before an Agent reports a media artifact as delivered, it must verify:

- The artifact exists at the source path.
- The artifact has been copied or registered into `dist`.
- A manifest entry includes source path, delivery path, timestamp, size, duration, codec, resolution, and status.
- `ffprobe` or an equivalent tool confirms readable video and audio streams for videos.
- A human-readable README or delivery note points to the recommended file.

## Non-Destructive Rule

Do not delete, rename, or move OpenMontage runtime outputs during publishing. Publishing creates a delivery copy and a manifest trail while preserving the original production package.

## Recovery Rule

If a deliverable cannot be found, run:

```powershell
.\scripts\find_demo_artifacts.ps1
```

The script searches ComplianceRadar, OpenMontage, and VistaMediaTank roots and writes the latest recovery evidence under `dist\evidence`.

## Demo Video Commands

Publish a verified OpenMontage review video:

```powershell
.\scripts\publish_demo_video.ps1 -SourceVideo "D:\Openmontage\runtime\compliance_radar_demo_20260708\review_package_bgm02_v2_20260708\01_review_video\compliance_radar_demo_review_bgm02_v2_constant_bed_20260708.mp4" -Version "review_bgm02_v2_constant_bed_20260708" -Status "review_accepted"
```

Create or register a compressed 1080p delivery copy:

```powershell
.\scripts\compress_demo_video.ps1
```
