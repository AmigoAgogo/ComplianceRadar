# ComplianceRadar 4-Hour Trust Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen ComplianceRadar within 4 hours so that article-level source links, original subjects, LLM-backed analysis, update receipts, and packaged demo behavior are all trustworthy and verifiable.

**Architecture:** Keep the current Flask + desktop-shell POC structure, but tighten the crawl-validation path, add credibility metadata to each event, generate run receipts for every update, shift analytics toward Siemens-facing control warnings, and reduce change risk by extracting a few focused helpers from the oversized ingestion service. The implementation should reuse the existing crawler, AI service, analytics logic, and packaging flow rather than rebuilding the platform.

**Tech Stack:** Python, Flask, requests, BeautifulSoup, pdfplumber, JSON state store, vanilla JS, HTML/CSS, pytest/unittest, PyInstaller.

---

## File Map

**Core backend services**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\article_crawler.py`
  - Tighten article-level URL validation, source-specific extraction branches, direct-article verification helpers.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ingestion.py`
  - Wire credibility fields into events, produce run receipts, call health summarizers, and delegate focused responsibilities to helpers.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\analytics.py`
  - Replace weak broad summary emphasis with Siemens-focused control-domain early warning outputs.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\source_diagnostics.py`
  - Surface source health metrics that can be shown in Source Center.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ai.py`
  - Mark successful LLM workflow completion explicitly so the UI and receipts can prove real model invocation.
- Create: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\run_receipts.py`
  - Serialize and persist update receipts under runtime logs.
- Create: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\event_quality.py`
  - Centralize credibility field computation such as source link verification and extraction confidence.

**API and UI**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\main.py`
  - Expose any extra receipt or source-health data needed by the frontend.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\templates\index.html`
  - Add compact UI hooks for confidence state, source health, and clearer update status.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\static\app.js`
  - Render source-link verification, original-subject truth indicators, source health, and update receipt summaries.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\static\styles.css`
  - Minimal styling for confidence badges, health labels, and receipt summaries.

**Packaging and docs**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\ComplianceRadarFinal.spec`
  - Standardize the release spec used for the final EXE.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\build_exe.ps1`
  - Ensure packaging points to the single approved release spec and output path.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\README.md`
  - Update the quick-start and build notes to match the hardened workflow.

**Tests**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py`
  - Add coverage for credibility fields, receipt generation, and event acceptance/rejection logic.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py`
  - Cover new API-visible fields and update flow outputs.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py`
  - Assert presence of confidence/status UI strings and control-based early warning sections.
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_run_demo.py`
  - Keep packaging/runtime launch expectations aligned with the hardened demo path.
- Create if needed: `C:\MINISTERIUM\repos\ComplianceRadar\tests\fixtures\bj_finance_listing.html`
- Create if needed: `C:\MINISTERIUM\repos\ComplianceRadar\tests\fixtures\sh_finance_listing.html`

### Task 1: Lock the article-level truth gate

**Files:**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\article_crawler.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py`

- [ ] **Step 1: Write the failing tests for article-level acceptance and rejection**

```python
def test_rejects_index_like_source_links():
    service = make_service()
    assert service._looks_like_article_url("https://example.gov.cn/index.html") is False


def test_accepts_real_article_link_with_detail_path():
    service = make_service()
    assert service._looks_like_article_url("https://example.gov.cn/art/2026/7/9/art_123.html") is True
```

- [ ] **Step 2: Run the targeted test to verify the failure or missing coverage**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py -k article -v`
Expected: FAIL or no matching assertions yet for article-truth gating.

- [ ] **Step 3: Implement stricter article URL validation and direct article verification helpers**

```python
def _looks_like_article_url(self, url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    normalized = url.lower()
    bad_patterns = ["/index.html", "javascript:", "void(0)", "#"]
    if any(pattern in normalized for pattern in bad_patterns):
        return False
    article_signals = ["/art/", "/content/", "docid=", ".shtml", ".html", ".pdf"]
    return any(signal in normalized for signal in article_signals)
```

- [ ] **Step 4: Add source-specific extraction branches for the four default regulators**

```python
if "jrj.beijing.gov.cn" in list_url:
    return self._extract_bj_finance_links(html, list_url)
if "jrj.sh.gov.cn" in list_url:
    return self._extract_sh_finance_links(html, list_url)
if "pbc.gov.cn" in list_url:
    return self._extract_pbc_links(html, list_url)
if "nfra.gov.cn" in list_url or parser == "nfra_docinfo":
    return self._fetch_nfra_relevant_articles(source, expanded_keywords, limit)
```

- [ ] **Step 5: Re-run the targeted crawler tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py -k article -v`
Expected: PASS.

- [ ] **Step 6: Commit the crawler truth-gate change**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add app/services/article_crawler.py tests/test_ingestion.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "feat: harden article-level crawl validation"
```

### Task 2: Add event credibility fields and extraction confidence

**Files:**
- Create: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\event_quality.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ingestion.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ai.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py`

- [ ] **Step 1: Write failing tests for credibility fields**

```python
def test_event_contains_credibility_flags_after_sync(client):
    payload = client.post('/api/sources/sync', json={'period': 'today'}).get_json()
    event = payload['events'][0]
    assert 'source_link_verified' in event
    assert 'article_opened' in event
    assert 'original_subject_extracted' in event
    assert 'llm_analysis_completed' in event
    assert 'extraction_confidence' in event
```

- [ ] **Step 2: Run the tests to confirm the missing fields**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py -k credibility -v`
Expected: FAIL because the fields do not exist yet.

- [ ] **Step 3: Implement a focused event-quality helper**

```python
def build_event_quality(article_url: str, title: str, institution_name: str, llm_completed: bool) -> dict:
    subject_present = institution_name not in {"", "Not disclosed in source article"}
    confidence = "high" if article_url and subject_present else "medium" if article_url else "low"
    return {
        "source_link_verified": bool(article_url),
        "article_opened": bool(title),
        "original_subject_extracted": subject_present,
        "llm_analysis_completed": llm_completed,
        "extraction_confidence": confidence,
    }
```

- [ ] **Step 4: Attach credibility fields during event creation and LLM enrichment**

```python
quality = build_event_quality(
    article.get("source_url", ""),
    title,
    institution_name,
    llm_completed=False,
)
event.update(quality)

if enrichment["used_llm"]:
    updated["llm_analysis_completed"] = True
```

- [ ] **Step 5: Re-run the credibility tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py -k credibility -v`
Expected: PASS.

- [ ] **Step 6: Commit the credibility-field change**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add app/services/event_quality.py app/services/ingestion.py app/services/ai.py tests/test_api.py tests/test_ingestion.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "feat: add event credibility signals"
```

### Task 3: Generate update run receipts and surface source health

**Files:**
- Create: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\run_receipts.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ingestion.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\source_diagnostics.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\main.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py`

- [ ] **Step 1: Write the failing tests for run receipts and source-health fields**

```python
def test_sync_writes_run_receipt(tmp_path):
    writer = RunReceiptWriter(tmp_path)
    path = writer.write({"run_id": "sync-1", "accepted_events": 2})
    assert path.exists()


def test_source_payload_contains_health_fields(client):
    source = client.get('/api/sources').get_json()[0]
    assert 'health_status' in source
```

- [ ] **Step 2: Run the receipt and source-health tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py -k "receipt or health" -v`
Expected: FAIL because the writer and health fields do not exist yet.

- [ ] **Step 3: Add a small run-receipt writer service**

```python
class RunReceiptWriter:
    def __init__(self, runtime_root: Path) -> None:
        self.output_dir = runtime_root / 'logs' / 'update_runs'

    def write(self, receipt: dict) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{receipt['run_id']}.json"
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        return path
```

- [ ] **Step 4: Persist accepted/rejected article outcomes and source health summaries during sync**

```python
receipt = {
    'run_id': run_id,
    'period': period,
    'sources_checked': checked_sources,
    'accepted_events': accepted_events,
    'rejected_articles': rejected_articles,
    'llm_model_used': llm_model,
    'started_at': started_at,
    'ended_at': ended_at,
}
receipt_path = self.run_receipts.write(receipt)
```

- [ ] **Step 5: Re-run the tests for receipts and source health**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py -k "receipt or health" -v`
Expected: PASS.

- [ ] **Step 6: Commit the receipt and source-health change**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add app/services/run_receipts.py app/services/ingestion.py app/services/source_diagnostics.py app/main.py tests/test_ingestion.py tests/test_api.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "feat: add update receipts and source health tracking"
```

### Task 4: Shift analytics to Siemens-facing control warnings

**Files:**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\analytics.py`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\app\services\ai.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py`

- [ ] **Step 1: Write the failing tests for control-based early warning sections**

```python
def test_dashboard_early_warning_uses_control_sections(client):
    dashboard = client.get('/api/dashboard').get_json()
    warning = dashboard['management_dashboard']['early_warning']
    assert 'control_domains' in warning
    assert 'management_actions' in warning
```

- [ ] **Step 2: Run the targeted dashboard tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py -k warning -v`
Expected: FAIL because the dashboard still uses the old generic structure.

- [ ] **Step 3: Update analytics to emit control-domain warnings grounded in fetched events**

```python
early_warning = {
    'headline': 'Control-focused regulatory early warning',
    'summary': summary_text,
    'control_domains': [
        'Asset Authenticity and Penetration Review',
        'Disclosure and Reporting Discipline',
        'Related-Party Governance',
    ],
    'management_actions': [
        'Review asset onboarding and penetration evidence.',
        'Reconfirm local filing and regulatory reporting timeliness.',
        'Recheck related-party approval and escalation controls.',
    ],
    'supporting_events': supporting_events,
}
```

- [ ] **Step 4: Ensure AI console / regulatory output uses only fetched event context and marks model usage**

```python
context_lines.append(
    f"LLM workflow status: {'completed' if any(event.get('llm_analysis_completed') for event in events) else 'not completed'}"
)
```

- [ ] **Step 5: Re-run the dashboard warning tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py -k warning -v`
Expected: PASS.

- [ ] **Step 6: Commit the warning-output change**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add app/services/analytics.py app/services/ai.py tests/test_api.py tests/test_ui_contract.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "feat: make early warning control-based"
```

### Task 5: Surface credibility and health in the UI

**Files:**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\templates\index.html`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\static\app.js`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\static\styles.css`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py`

- [ ] **Step 1: Write the failing UI contract tests for credibility and source-health labels**

```python
def test_ui_shows_source_link_and_confidence_labels(client):
    html = client.get('/').get_data(as_text=True)
    assert 'Source Link' in html
    assert 'Confidence' in html
    assert 'Health Status' in html
```

- [ ] **Step 2: Run the UI contract tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py -v`
Expected: FAIL because the labels or hooks are missing.

- [ ] **Step 3: Add compact credibility badges and source-health summaries to the UI**

```javascript
function renderConfidence(event) {
  return `<span class="badge confidence-${event.extraction_confidence}">${event.extraction_confidence}</span>`;
}

function renderSourceHealth(source) {
  return `${source.health_status || 'unknown'} | ${source.parser || 'n/a'} | ${source.last_sync_result || 'no sync yet'}`;
}
```

- [ ] **Step 4: Add minimal styling for the new UI state**

```css
.badge { border-radius: 999px; padding: 2px 8px; font-size: 12px; }
.confidence-high { background: #d8f5df; color: #18603a; }
.confidence-medium { background: #fff1cc; color: #7b5300; }
.confidence-low { background: #fde0df; color: #8b1e1e; }
```

- [ ] **Step 5: Re-run the UI contract tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py -v`
Expected: PASS.

- [ ] **Step 6: Commit the UI transparency change**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add templates/index.html static/app.js static/styles.css tests/test_ui_contract.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "feat: expose crawl confidence and source health"
```

### Task 6: Standardize packaging and runtime paths

**Files:**
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\ComplianceRadarFinal.spec`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\build_exe.ps1`
- Modify: `C:\MINISTERIUM\repos\ComplianceRadar\README.md`
- Test: `C:\MINISTERIUM\repos\ComplianceRadar\tests\test_run_demo.py`

- [ ] **Step 1: Write or update the failing runtime/packaging expectations**

```python
def test_runtime_root_for_frozen_build_uses_exe_runtime_folder():
    from app.main import resolve_runtime_root
    # assert expected runtime behavior through monkeypatch or existing helper coverage
```

- [ ] **Step 2: Run the packaging-related tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_run_demo.py -v`
Expected: FAIL or insufficient coverage for the final packaging path.

- [ ] **Step 3: Collapse packaging onto one approved spec and one output path**

```powershell
pyinstaller --clean C:\MINISTERIUM\repos\ComplianceRadar\ComplianceRadarFinal.spec
```

- [ ] **Step 4: Update build documentation and script comments to match the single release path**

```powershell
# build_exe.ps1 should always target ComplianceRadarFinal.spec
# output should be dist\ComplianceRadarFinal.exe or a single release folder path
```

- [ ] **Step 5: Re-run the packaging tests**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_run_demo.py -v`
Expected: PASS.

- [ ] **Step 6: Commit the packaging cleanup**

```bash
git -C C:\MINISTERIUM\repos\ComplianceRadar add ComplianceRadarFinal.spec build_exe.ps1 README.md tests/test_run_demo.py
git -C C:\MINISTERIUM\repos\ComplianceRadar commit -m "chore: standardize demo packaging path"
```

### Task 7: Real verification pass

**Files:**
- No code changes required unless fixes are found.
- Evidence output expected under runtime logs and packaged build artifacts.

- [ ] **Step 1: Run the core automated test suite**

Run: `pytest C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ingestion.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_api.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_ui_contract.py C:\MINISTERIUM\repos\ComplianceRadar\tests\test_run_demo.py -v`
Expected: PASS.

- [ ] **Step 2: Start the local app and hit the health endpoint**

Run: `python -m flask --app C:\MINISTERIUM\repos\ComplianceRadar\app\main.py run --port 8010`
Expected: Flask starts successfully.

Run: `curl http://127.0.0.1:8010/api/health`
Expected: `{"status":"ok"}`

- [ ] **Step 3: Perform a real update call against the local API**

Run: `curl -X POST http://127.0.0.1:8010/api/sources/sync -H "Content-Type: application/json" -d '{"period":"last_7_days"}'`
Expected: JSON response with events, source results, and receipt metadata.

- [ ] **Step 4: Inspect one run receipt and at least five article links**

Run: `Get-ChildItem C:\MINISTERIUM\repos\ComplianceRadar\data\runtime\logs\update_runs`
Expected: At least one JSON receipt file.

Run: `Get-Content <receipt-path>`
Expected: Contains sources checked, accepted events, rejected articles, and LLM model usage.

- [ ] **Step 5: Build the EXE and launch it once for smoke verification**

Run: `powershell -ExecutionPolicy Bypass -File C:\MINISTERIUM\repos\ComplianceRadar\build_exe.ps1`
Expected: Single approved packaged output created.

Run: Launch the packaged EXE manually or via `Start-Process` and confirm the GUI opens without a blocking fatal dialog.
Expected: App window opens and closes cleanly.

- [ ] **Step 6: Record the final delivery evidence**

```text
- final exe absolute path
- test command results
- run receipt path
- at least one confirmed article-level source link
- whether MiniMax workflow completed successfully
```

## Self-Review Checklist

- Every scoped item from the 4-hour goal is covered by at least one task.
- The plan stays within the current ComplianceRadar architecture and avoids a ground-up rebuild.
- The validation section requires real source sync, real receipt inspection, and real packaged-app launch.
- No placeholders remain for the engineer to infer critical behavior.

## Execution Handoff

Plan complete and saved to `C:\MINISTERIUM\repos\ComplianceRadar\docs\superpowers\plans\2026-07-09-compliance-radar-trust-upgrade.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
