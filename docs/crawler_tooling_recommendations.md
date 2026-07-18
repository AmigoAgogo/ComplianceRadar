# ComplianceRadar Crawling Tooling Recommendations

## Current Diagnosis

The current `ComplianceRadar` implementation uses:

- `requests` for page fetch
- regex/HTML heuristics for list and detail parsing
- optional LLM enrichment only after an event is already created

This means the current stack can enrich a parsed event, but it cannot yet use the configured LLM as a real crawling orchestrator.

## Verified Source Findings

### `src-nfra` - National Financial Regulatory Administration

Real diagnosis result:

- `fetch_mode`: `dynamic_shell`
- `recommended_adapter`: `nfra_docinfo`
- page is an Angular-style shell with `<tpl>` placeholders
- the page does not expose a stable article list directly in the HTML
- front-end scripts reveal:
  - dynamic API root: `/cbircweb`
  - CDN data root: `/cn/static/data`
  - DocInfo-based loading path

Implication:

- this source needs a dedicated adapter
- generic `<li><a>` parsing is not sufficient as the primary strategy

### `src-pbc` - People's Bank of China

Real diagnosis result:

- `fetch_mode`: `network_error`
- `recommended_adapter`: `browser_required`
- direct HTTP access timed out in the current environment

Implication:

- this source needs browser-assisted capture, retries, or an alternative network path

## Recommended Tool Stack

### 1. Browser discovery

Use `Playwright`.

Purpose:

- open the exact regulator page the user configured
- wait for XHR/fetch calls
- capture the real list endpoint and detail endpoint
- capture the actual article URL pattern used by the site

Why:

- many China regulator sites render list data through XHR or template loaders
- browser network observation is the fastest reliable way to discover the true backend route

### 2. Low-token fetch layer

Use `requests`.

Purpose:

- once a list endpoint or stable detail URL template is known, switch to deterministic HTTP fetch
- reduce repeated browser cost
- keep runtime and token use low

### 3. HTML cleaning and text extraction

Use:

- `beautifulsoup4`
- `trafilatura`

Purpose:

- extract title, publish date, main body
- reduce boilerplate
- support later LLM analysis with cleaner evidence

### 4. Structured schemas and validation

Use `pydantic`.

Purpose:

- define `crawl_plan`
- define `article_record`
- define `event_record`
- force LLM outputs into a validated schema

This is critical because article URL, institution subject, and severity must not be guessed.

### 5. Scheduling

Use `APScheduler`.

Purpose:

- weekly runs
- retry queue
- major-event refresh triggers

### 6. Local analytical store

Use `DuckDB`.

Purpose:

- lightweight local evidence store
- weekly aggregation
- keyword trend and enforcement-theme analysis

## How LLM Should Be Used

The configured LLM should be used for:

- source classification
- crawl-plan generation
- field-mapping repair when HTML structure changes
- complex institution/violation extraction from raw article text
- compliance interpretation

The configured LLM should **not** be used to fetch raw web pages directly.

Recommended workflow:

1. Browser/HTTP layer collects raw evidence.
2. A low-token parser extracts candidate fields.
3. The configured LLM receives:
   - source URL
   - HTML snippet
   - candidate text
   - candidate metadata
4. The LLM returns validated structured fields or a crawl-plan update.

## Low-Code / Low-Token Scripts To Bundle

Bundle these inside `ComplianceRadar`:

- source diagnostics script
- adapter-specific fetch scripts
- HTML cleaning script
- structured event normalization script
- evidence snapshot writer

Do **not** rely on the LLM for:

- repeated page download
- repeated date normalization
- repeated dedupe checks
- repeated boilerplate stripping

Those should stay deterministic.

## Immediate Implementation Priority

1. Add a `source adapter` layer.
2. Implement `nfra_docinfo` as the first real adapter.
3. Add Playwright-based capture for browser-required sources.
4. Change the ingestion flow so only adapter-confirmed article URLs can become events.
5. Pass extracted raw fields to the configured LLM for analysis only after article truth is confirmed.
