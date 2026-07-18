# ComplianceRadar POC

GitHub repository: https://github.com/AmigoAgogo/ComplianceRadar

Minimal demo for a China regulatory enforcement intelligence platform with:

- Dashboard for management-facing trend summaries
- Event library with evidence and review status
- Review desk for lightweight analyst approvals
- AI console with configurable model gateway

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m flask --app app.main run --debug
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Demo Behaviors

- Bootstraps sample enforcement events and sources on first run
- Persists runtime data next to the executable in `runtime/` when packaged
- Keeps crawled intelligence, AI opinions, and user review decisions in separate runtime ledgers
- Offers API endpoints for dashboard, event review, AI chat, model switching, and demo reset
- Syncs a small set of official-source adapters and stores HTML evidence under the runtime folder
- Exports weekly report files in CSV, HTML, and PDF

## Portable Data Safety

Packaged builds are designed to be moved with the smallest practical bundle:

```text
ComplianceRadarFinal.exe
runtime/
```

The `runtime/` folder is protected user data. Do not delete it during rebuilds or code iterations. It contains:

- `state.json` for local source/model/event state
- `evidence/` for raw source evidence
- `logs/update_runs/` for update receipts
- `ai_opinions/llm_runs.jsonl` for Agent/LLM compliance opinions
- `user_reviews/review_decisions.jsonl` for human review decisions
- `agent_configs/` for user-provided Agent configuration files

Code updates should replace the executable and source code only. Runtime data must remain outside git and outside the PyInstaller temporary bundle.

## Build EXE

```powershell
pip install -r requirements.txt
.\build_exe.ps1
```

The packaged app will be created under `dist\ComplianceRadar\ComplianceRadar.exe`.

## Test

```powershell
python -m pytest tests -q
```

## Release Discipline

Every push to `AmigoAgogo/ComplianceRadar` should update:

- `README.md` if usage, packaging, or data layout changes
- `CHANGELOG.md` for user-visible changes
- `docs/portable_data_layout.md` if runtime storage changes
