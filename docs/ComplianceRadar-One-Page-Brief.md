# ComplianceRadar POC: One-Page Brief

## What ComplianceRadar Is

ComplianceRadar is a POC intelligence platform for monitoring public regulatory enforcement signals relevant to financing leasing and factoring in mainland China. It is designed to support Siemens Financial Leasing management, compliance, legal, risk, and global leadership with a single workflow that collects signals, preserves evidence, structures events, and produces management-ready interpretation.

## Development Journey

The product started as a lightweight weekly monitoring demo focused on three goals: prove that public enforcement data can be collected from Chinese regulatory sources, show evidence-backed structured event records, and test whether LLM-assisted interpretation can make the output more valuable for management. The first iteration established a local Flask application, packaged Windows executable, source registry, event library, model gateway, and report export flow. Later iterations added persistent cloud-model profiles, source discovery, update actions, evidence snapshots, AI enrichment of synced events, and a more management-facing UI. The current iteration also hardens local runtime behavior by allowing the UI to rediscover the local API if the preferred port is already occupied.

## How It Works

1. Source registry:
   The tool stores a managed list of public sources such as regulator sites, WeChat monitoring sources, and public databases.
2. Sync and parsing:
   When the user clicks an update action, the app fetches supported sources, parses notice content, and converts it into normalized event records.
3. Evidence preservation:
   Each synced event keeps a source trail and writes an HTML evidence snapshot into the local runtime folder.
4. Event library:
   Structured events are surfaced in a filterable table so users can review date, regulator, institution, topic, severity, evidence, and LLM enrichment status.
5. Regulatory outlook:
   Recent events are aggregated into a management-facing outlook that explains what changed, why it matters, and what management should watch next.
6. AI console:
   The user can send a question to the currently selected cloud model. The prompt is grounded in the current radar snapshot and framed from the Siemens Financial Leasing perspective.

## What Is Live in the Current POC

- Windows executable packaging
- Persistent local runtime state
- Source management and update actions
- Event sync with evidence snapshots
- Event filtering by date range
- LLM model catalog loading, switching, and testing
- LLM-backed event enrichment and AI console analysis
- CSV, HTML, and PDF report export
- Local API fallback discovery when the default port is unavailable

## Current POC Boundaries

- Source coverage is still seed-and-demo heavy rather than full production scale
- Some event narratives still use demo-style content even though the workflow is real
- Review and escalation logic is directional, not yet a full operating model
- The AI console is functional, but still needs simplification for faster executive use
- The regulatory outlook needs another round of refinement to become a true board-ready alert desk

## Recommended Next Step

Move from “feature-complete demo” to “trustworthy pilot” by tightening three areas in parallel: source reliability, management-facing interpretation quality, and review-desk operating logic. That will make the product easier to trust, easier to explain internally, and more useful in real weekly reporting.
