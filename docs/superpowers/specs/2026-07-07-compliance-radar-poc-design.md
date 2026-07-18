# ComplianceRadar POC Design

> Minimal single-repo demo for a China regulatory enforcement intelligence platform with a management dashboard, event library, review desk, AI console, and model gateway.

## Goal

Prove a realistic enforcement-intelligence loop with the least amount of engineering: seeded source records stand in for first-wave real ingestion while the UI demonstrates reviewable events, evidence traceability, and AI-assisted summaries.

## Scope

- Single Python application serving API and GUI
- Local JSON-backed state for speed
- Seeded demo events and source registry
- AI gateway stub with model switching and "last used" behavior

## Out of Scope

- Full production crawling infrastructure
- Authentication and role-based access control
- Heavy workflow/case management
- Full desktop packaging

## Architecture

- FastAPI serves both browser UI and JSON APIs
- Seed data bootstraps runtime state into `data/runtime/state.json`
- Dashboard analytics are computed from event records at request time
- Review decisions and current model choice persist locally for demo repeatability
