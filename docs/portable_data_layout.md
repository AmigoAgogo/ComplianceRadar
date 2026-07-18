# ComplianceRadar Portable Data Layout

ComplianceRadar should be portable as a small bundle:

```text
ComplianceRadarPortable/
  ComplianceRadarFinal.exe
  runtime/
```

The executable contains application code, templates, static assets, seed sources, and default Agent config templates. The `runtime/` folder contains user and business data. Replacing or rebuilding the executable must not delete `runtime/`.

## Runtime Partitions

```text
runtime/
  state.json
  agent_configs/
  evidence/
  logs/
    update_runs/
  ai_opinions/
    llm_runs.jsonl
  user_reviews/
    review_decisions.jsonl
  intelligence/
    deleted_events.jsonl
  exports/
```

`state.json` stores the local working state, including sources, models, and current event metadata.

`evidence/` stores source HTML, PDF extracts, and original evidence snapshots generated during crawling.

`logs/update_runs/` stores update receipts: processed sources, accepted events, rejected articles, LLM usage, and errors.

`ai_opinions/llm_runs.jsonl` stores Agent or model compliance opinions as append-only records.

`user_reviews/review_decisions.jsonl` stores human review decisions as append-only records.

`intelligence/deleted_events.jsonl` stores manual Event Library deletions as append-only records. Deleting an event removes it from the active working view, but the deletion record keeps the event id, title, source URL, deleter, and deletion time so external audit tooling can reconstruct the action.

`agent_configs/` stores user-supplied Agent files. Application updates may add missing defaults, but must not overwrite existing files.

Recommended Agent config bundle:

```text
agent_configs/
  00_role_and_boundaries.md
  10_signal_intake.md
  20_control_taxonomy.md
  30_china_management_brief.md
  40_global_compliance_brief.md
  50_output_schema.json
  60_style_and_length.md
  70_escalation_triggers.md
```

Legacy single-file drafts may remain in the folder for reference, but the runtime should prefer the numbered bundle when it exists.

## Preservation Rules

- Do not delete `runtime/` during rebuild, packaging, or upgrade.
- Do not write mutable business data inside the PyInstaller `_MEI...` temporary bundle.
- Do not commit `runtime/`, `dist/`, `build/`, or generated logs to git.
- Treat evidence, Agent opinions, and user approvals as protected artifacts.
- Reset/demo actions may refresh default config, but must preserve existing crawled events and review decisions.
- Manual correction actions should update the current working state and write a JSONL ledger record instead of destroying evidence snapshots or historical opinion records.

## External Parsing

Runtime ledgers are JSON or JSONL so external tools can parse them without launching the GUI.

Every durable record should include a stable identifier where applicable:

```json
{
  "event_id": "nfra-1236230",
  "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1236230.pdf",
  "recorded_at": "2026-07-13T10:00:00+00:00"
}
```
