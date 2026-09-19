# Changelog

All notable ComplianceRadar changes should be recorded here before pushing to GitHub.

## [Unreleased]

### Added

- Added demo video publishing, compression, and recovery scripts so Agent-produced media artifacts are registered and recoverable.
- Added artifact delivery policy documenting required manifest, evidence, and verification gates for user-facing outputs.
- Documented the correct GitHub repository: `https://github.com/AmigoAgogo/ComplianceRader`.
- Added portable runtime data layout documentation.
- Added append-only runtime ledgers for AI opinions and user review decisions.
- Added manual announcement deletion from Event Library with a separate deletion ledger.
- Added editable AI opinions and editable human review opinions from the GUI/API.

### Changed

- Demo reset now preserves existing crawled events and review state.
- Runtime and generated artifacts are excluded from git to protect user data and local evidence.
- Human corrections now update the working view while preserving a machine-readable change trail.

### Fixed

- Published the recovered ComplianceRadar demo video into a stable `dist\demo_media` delivery location and registered both the original-quality and compressed versions.
- Reduced the risk of losing historical crawled data, Agent opinions, or human review notes during rebuilds and iterations.
- Prevented AI opinion edits and announcement deletions from silently overwriting prior runtime records.
