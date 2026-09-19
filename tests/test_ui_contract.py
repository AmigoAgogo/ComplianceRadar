import unittest
from pathlib import Path


class UiContractTests(unittest.TestCase):
    def test_model_gateway_uses_selects_for_provider_and_model(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")

        self.assertIn('select id="model-provider"', html)
        self.assertIn('select id="model-model-id"', html)
        self.assertNotIn('input id="model-model-id"', html)

    def test_model_gateway_auto_loads_catalog_when_credentials_change(self) -> None:
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn('model-base-url', js)
        self.assertIn('model-api-key', js)
        self.assertIn('loadModelCatalog', js)
        self.assertIn('addEventListener("change"', js)

    def test_all_update_buttons_have_bound_handlers(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn('id="update-all-events"', html)
        self.assertIn('data-busy-action="sync"', html)
        self.assertIn('id="event-sync-progress"', html)
        self.assertIn('syncSources', js)
        self.assertIn('describeSyncResult', js)
        self.assertIn('setProgressState', js)
        self.assertIn("Only real article-level records fetched from configured sources are shown here.", html)

    def test_dashboard_is_management_focused(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("Penalty Intelligence", html)
        self.assertIn("Financial Compliance Early Warning", html)
        self.assertIn('id="penalty-intelligence"', html)
        self.assertIn('id="early-warning-panel"', html)
        self.assertIn("renderManagementDashboard", js)
        self.assertNotIn("Highest Enforcement Region", html)
        self.assertIn("Control Domains", html)
        self.assertIn("Management Actions", html)
        self.assertIn('id="loaded-agent-name"', html)

    def test_event_library_uses_table_layout_and_period_filters(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn('id="event-period-from"', html)
        self.assertIn('id="event-period-to"', html)
        self.assertIn('id="clear-event-filters"', html)
        self.assertIn('id="event-filter-summary"', html)
        self.assertIn('id="events-table-shell"', html)
        self.assertIn('class="scroll-region events-scroll"', html)
        self.assertIn('renderEventsTable', js)
        self.assertIn('applyEventFilters', js)
        self.assertIn("Source Link", js)
        self.assertIn("Actions", js)
        self.assertIn("Edit Review", js)
        self.assertIn("deleteEvent", js)
        self.assertIn("editEventReview", js)
        self.assertIn("Original Subject", js)
        self.assertIn("Open Source Article", js)
        self.assertIn("Confidence", js)
        self.assertIn("isDisplayableEvent", js)
        self.assertNotIn("<th>Title</th>", js)
        self.assertNotIn("<th>Analysis</th>", js)
        self.assertNotIn("<th>Evidence</th>", js)
        self.assertIn("event.sources", js)

    def test_review_desk_is_risk_outlook_not_approval_queue(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("Regulatory Radar", html)
        self.assertIn('id="review-outlook"', html)
        self.assertIn('class="scroll-region watchpoint-scroll"', html)
        self.assertIn('id="review-kpi-major"', html)
        self.assertIn('id="review-kpi-theme"', html)
        self.assertIn('renderRiskOutlook', js)
        self.assertNotIn("Approve</button>", html)

    def test_source_center_is_minimal_add_form(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn('id="source-discovery-input"', html)
        self.assertIn('id="discover-source"', html)
        self.assertIn('deleteSource', js)
        self.assertIn('discoverSource', js)
        self.assertIn('Check Latest', js)
        self.assertIn("Health Status", html)
        self.assertIn("Only valid live regulatory URLs or recognized regulator names can be added.", html)
        self.assertNotIn("Live Workflow Validation", html)
        self.assertNotIn("Ad Hoc Source Workflow", html)
        self.assertNotIn('id="run-direct-workflow"', html)
        self.assertNotIn('id="run-adhoc-workflow"', html)
        self.assertNotIn('id="source-parser"', html)
        self.assertNotIn("Preview Parse", html)
        self.assertNotIn("Edit From Form", html)

    def test_topbar_removes_sync_button_and_reports_nav(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")

        self.assertNotIn('id="sync-sources"', html)
        self.assertNotIn('data-view="reports"', html)

    def test_ai_console_is_merged_into_review_workspace(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertNotIn('data-view="ai"', html)
        self.assertIn('id="copilot-current-model"', html)
        self.assertIn('id="ai-context-lens"', html)
        self.assertIn('id="ai-context-agent-folder"', html)
        self.assertIn("Regulatory Output", html)
        self.assertIn('renderAiResponse', js)
        self.assertNotIn("Events In Scope", html)
        self.assertNotIn("How Leading Platforms Simplify AI", html)

    def test_frontend_can_discover_local_api_when_current_origin_fails(self) -> None:
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("detectApiBase", js)
        self.assertIn("/api/health", js)
        self.assertIn("127.0.0.1", js)

    def test_successful_bootstrap_writes_loaded_workspace_activity(self) -> None:
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn("function describeLoadedWorkspace", js)
        self.assertIn("logActivity(describeLoadedWorkspace(state.dashboard))", js)
        self.assertIn("Event Library record(s)", js)
        self.assertIn("configured source(s)", js)

    def test_ai_console_is_simplified_and_keeps_export_actions(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertNotIn("Weekly Brief", html)
        self.assertNotIn("Board Alert", html)
        self.assertNotIn("Global Note", html)
        self.assertNotIn('data-audience="board"', html)
        self.assertNotIn('data-audience="compliance"', html)
        self.assertNotIn('data-audience="risk"', html)
        self.assertNotIn('data-audience="global"', html)
        self.assertNotIn("Radar Digest", html)
        self.assertNotIn("Agent Guidance Files", html)
        self.assertIn('id="ai-copy-full"', html)
        self.assertIn('id="ai-export-brief"', html)
        self.assertIn('id="ai-edit-opinion"', html)
        self.assertIn('id="ai-brief-china"', html)
        self.assertIn('id="ai-brief-global"', html)
        self.assertIn('parseStructuredResponse', js)
        self.assertIn('downloadAiBrief', js)
        self.assertIn('editAiOpinion', js)

    def test_update_all_sources_uses_modal_period_picker(self) -> None:
        html = Path("templates/index.html").read_text(encoding="utf-8")
        js = Path("static/app.js").read_text(encoding="utf-8")

        self.assertIn('id="sync-period-modal"', html)
        self.assertIn("Choose Update Window", html)
        self.assertIn("showSyncPeriodModal", js)
        self.assertIn("hideSyncPeriodModal", js)
        self.assertNotIn('id="sync-period-toolbar"', html)
