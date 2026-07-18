# Changelog

All notable ComplianceRadar changes should be recorded here before pushing to GitHub.

## [Unreleased]

### Added

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

- Reduced the risk of losing historical crawled data, Agent opinions, or human review notes during rebuilds and iterations.
- Prevented AI opinion edits and announcement deletions from silently overwriting prior runtime records.
