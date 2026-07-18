# ComplianceRadar POC Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-repo demo that shows dashboard, event review, evidence traceability, AI console, and model switching for China regulatory enforcement intelligence.

**Architecture:** Use one FastAPI app to serve HTML, APIs, and local state. Seed demo records into a JSON runtime store so the UI can reset and replay the same event-review workflow without external dependencies.

**Tech Stack:** Python, FastAPI, Jinja2, vanilla JavaScript, pytest

---

### Task 1: Create the demo test harness

**Files:**
- Create: `tests/test_ingestion.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**
- [ ] **Step 2: Run `python -m pytest -q` and confirm imports fail before implementation**
- [ ] **Step 3: Implement the minimal backend to satisfy the tests**
- [ ] **Step 4: Re-run `python -m pytest -q` until green**

### Task 2: Create the demo application skeleton

**Files:**
- Create: `app/main.py`
- Create: `app/models.py`
- Create: `app/store.py`
- Create: `app/services/*.py`
- Create: `templates/index.html`
- Create: `static/app.js`
- Create: `static/styles.css`

- [ ] **Step 1: Serve a browser UI and JSON APIs from one process**
- [ ] **Step 2: Persist seed data to runtime state for repeatable demos**
- [ ] **Step 3: Add dashboard, event list, review actions, AI console, and model switching**

### Task 3: Seed the demo data and docs

**Files:**
- Create: `data/seeds/sample_events.json`
- Create: `data/sources/demo_sources.json`
- Create: `README.md`

- [ ] **Step 1: Add realistic demo records with evidence paths and review statuses**
- [ ] **Step 2: Add source registry seed data**
- [ ] **Step 3: Document local setup and run flow**
