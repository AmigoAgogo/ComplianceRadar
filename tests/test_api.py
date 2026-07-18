import tempfile
import unittest
import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch

from app.main import create_app, resolve_runtime_root


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        app = create_app(data_dir=Path(self.tempdir.name))
        self.client = app.test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seed_fetch(self, url: str, timeout: int = 15) -> str:
        fixtures_dir = Path("tests/fixtures")
        if "itemlist" in url.lower() or "itemname=" in url.lower():
            return (fixtures_dir / "nfra_listing.html").read_text(encoding="utf-8")
        if "113469" in url:
            return (fixtures_dir / "pbc_listing.html").read_text(encoding="utf-8")
        if "nfra-detail-1" in url:
            return (fixtures_dir / "nfra_sample.html").read_text(encoding="utf-8")
        if "nfra-detail-2" in url:
            return (fixtures_dir / "nfra_detail_2.html").read_text(encoding="utf-8")
        if "pbc-detail-1" in url:
            return (fixtures_dir / "pbc_sample.html").read_text(encoding="utf-8")
        if "pbc-detail-2" in url:
            return (fixtures_dir / "pbc_detail_2.html").read_text(encoding="utf-8")
        if "beijing" in url or "sh.gov.cn" in url or "jrj.sh.gov.cn" in url:
            return (fixtures_dir / "nfra_listing.html").read_text(encoding="utf-8")
        raise AssertionError(f"Unexpected URL: {url}")

    def _seed_runtime_event(self, event_id: str = "manual-edit-event") -> dict:
        self.client.get("/api/dashboard")
        state_path = Path(self.tempdir.name) / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        event = {
            "event_id": event_id,
            "title": "远东融资租赁有限公司行政处罚公告",
            "regulator": "国家金融监督管理总局",
            "region": "全国",
            "category": "Business Compliance",
            "institution_type": "融资租赁",
            "institution_name": "远东融资租赁有限公司",
            "institution_name_original": "远东融资租赁有限公司",
            "severity": "major",
            "published_at": "2026-07-10T09:00:00",
            "summary": "融资租赁公司相关处罚。",
            "risk_hint": "Review financing lease controls.",
            "english_brief": "Manual edit fixture.",
            "analysis_summary": "Manual edit fixture.",
            "penalty_focus": "Asset authenticity",
            "compliance_warning": "Review asset authenticity controls.",
            "is_penalty_event": True,
            "review_status": "pending",
            "reviewer": "",
            "review_notes": "",
            "source_link_verified": True,
            "article_opened": True,
            "original_subject_extracted": True,
            "llm_analysis_completed": False,
            "extraction_confidence": "high",
            "sources": [
                {
                    "source_id": "src-nfra",
                    "title": "远东融资租赁有限公司行政处罚公告",
                    "url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/manual-edit-event.pdf",
                    "published_at": "2026-07-10T09:00:00",
                }
            ],
            "evidence": [],
        }
        state["events"].append(event)
        state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return event

    def test_dashboard_endpoint_returns_summary(self) -> None:
        response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["summary"]["total_events"], 0)
        self.assertEqual(payload["summary"]["major_events"], 0)
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["models"]["current_model"], "Minimax China")
        self.assertIn("management_dashboard", payload)
        self.assertIn("top_penalty_reasons", payload["management_dashboard"])
        self.assertIn("early_warning", payload["management_dashboard"])
        self.assertIn(
            "control_domains",
            payload["management_dashboard"]["early_warning"],
        )
        self.assertIn(
            "management_actions",
            payload["management_dashboard"]["early_warning"],
        )

    def test_health_endpoint_supports_local_api_discovery(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_agent_config_endpoint_returns_runtime_folder(self) -> None:
        response = self.client.get("/api/agent-config")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["folder"].endswith("agent_configs"))
        self.assertGreaterEqual(payload["file_count"], 1)
        self.assertTrue(any(item["name"].endswith(".md") for item in payload["files"]))

    def test_bootstrap_seeds_minimax_model_into_runtime(self) -> None:
        response = self.client.get("/api/models")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        names = [item["name"] for item in payload["profiles"]]
        self.assertIn("Minimax China", names)

    def test_agent_config_is_included_in_ai_context(self) -> None:
        agent_dir = Path(self.tempdir.name) / "agent_configs"
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "board_policy.md").write_text(
            "Escalate high-severity China leasing enforcement items to board review within 24 hours.",
            encoding="utf-8",
        )
        response = self.client.post(
            "/api/ai/chat",
            json={"prompt": "Give compliance advice", "context": "gui-console"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreaterEqual(payload["agent_file_count"], 2)
        self.assertIn("Board Policy", payload["context_digest"])
        self.assertIn("China Management Brief", payload["context_digest"])
        self.assertIn("Global Compliance Brief", payload["context_digest"])

    def test_ai_chat_uses_split_agent_config_in_prompt(self) -> None:
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "Executive Summary: Short.\n"
                            "China Management Brief: 控制点应优先复核。\n"
                            "Global Compliance Brief: China pattern may require a global watchpoint.\n"
                            "Key Signals: one; two; three.\n"
                            "Risk to Siemens Financial Leasing: concise risk.\n"
                            "Recommended Actions: one; two; three.\n"
                            "Evidence: evt-1"
                        )
                    }
                }
            ]
        }

        with patch("app.services.ai.requests.post", return_value=fake_response) as mock_post:
            response = self.client.post(
                "/api/ai/chat",
                json={"prompt": "Give compliance advice", "context": "gui-console"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("China Management Brief", payload["answer"])
        self.assertIn("Global Compliance Brief", payload["answer"])

        system_content = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertIn("Return a concise management-ready answer", system_content)
        self.assertIn("China Management Brief", system_content)
        self.assertIn("Global Compliance Brief", system_content)
        self.assertIn("Emphasize what changed", user_content)

    def test_frozen_runtime_root_is_portable_next_to_executable(self) -> None:
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys,
            "executable",
            str(Path("C:/PortableApps/ComplianceRadar/ComplianceRadar.exe")),
            create=True,
        ):
            runtime_root = resolve_runtime_root(Path("C:/ignored"))

        self.assertEqual(
            runtime_root,
            Path("C:/PortableApps/ComplianceRadar/runtime"),
        )

    def test_api_responses_allow_local_cross_origin_requests(self) -> None:
        response = self.client.get(
            "/api/dashboard",
            headers={"Origin": "http://127.0.0.1:8765"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Access-Control-Allow-Origin"),
            "http://127.0.0.1:8765",
        )

    def test_ai_chat_endpoint_uses_current_model(self) -> None:
        response = self.client.post(
            "/api/ai/chat",
            json={"prompt": "Summarize this week's trend", "context": "dashboard"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["model"], "Minimax China")
        self.assertTrue(payload["answer"])
        ledger_path = Path(self.tempdir.name) / "ai_opinions" / "llm_runs.jsonl"
        self.assertTrue(ledger_path.exists())
        self.assertIn("Summarize this week's trend", ledger_path.read_text(encoding="utf-8"))

    def test_ai_chat_endpoint_includes_business_lens_and_event_context(self) -> None:
        with patch("app.main.DemoIngestionService.sync_sources") as mock_sync:
            mock_sync.side_effect = None
        response = self.client.post(
            "/api/ai/chat",
            json={
                "prompt": "Assess the latest risks for Siemens Financial Leasing.",
                "context": "gui-console",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("Siemens Financial Leasing", payload["answer"])
        self.assertIn("Siemens Financial Leasing", payload.get("business_lens", ""))
        self.assertGreaterEqual(payload.get("context_event_count", 0), 0)
        self.assertIn("Siemens Financial Leasing", payload.get("context_digest", ""))

    def test_add_model_and_switch_current_model(self) -> None:
        created = self.client.post(
            "/api/models",
            json={
                "name": "cloud-qwen",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        self.assertEqual(created.status_code, 200)

        switched = self.client.post("/api/models/current/cloud-qwen")
        self.assertEqual(switched.status_code, 200)
        self.assertEqual(switched.get_json()["current_model"], "cloud-qwen")

    def test_added_model_persists_across_app_restart(self) -> None:
        created = self.client.post(
            "/api/models",
            json={
                "name": "persistent-cloud",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        self.assertEqual(created.status_code, 200)

        restarted_client = create_app(data_dir=Path(self.tempdir.name)).test_client()
        response = restarted_client.get("/api/models")

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.get_json()["profiles"]]
        self.assertIn("persistent-cloud", names)

    def test_reset_demo_preserves_user_added_models(self) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "persistent-cloud",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )

        response = self.client.post("/api/demo/reset")

        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.get_json()["models"]["profiles"]]
        self.assertIn("persistent-cloud", names)

    def test_edit_model_endpoint(self) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "cloud-edit",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        updated = self.client.put(
            "/api/models/cloud-edit",
            json={"model_id": "qwen-plus", "base_url": "https://api.example.com/v1/responses"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["model_id"], "qwen-plus")

    @patch("app.services.ai.requests.post")
    def test_ai_chat_uses_real_configured_cloud_model(self, mock_post) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "cloud-qwen",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        self.client.post("/api/models/current/cloud-qwen")

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Cloud model summary output"
                    }
                }
            ]
        }

        response = self.client.post(
            "/api/ai/chat",
            json={"prompt": "Summarize this week's trend", "context": "dashboard"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["model"], "cloud-qwen")
        self.assertIn("Executive Summary", payload["answer"])
        self.assertIn("China Management Brief", payload["answer"])
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer secret",
        )

    @patch("app.services.ai.requests.post")
    def test_sync_uses_current_cloud_model_for_event_enrichment(self, mock_post) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "cloud-qwen",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        self.client.post("/api/models/current/cloud-qwen")
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary":"LLM enriched summary",'
                            '"risk_hint":"LLM risk hint",'
                            '"english_brief":"LLM english brief"}'
                        )
                    }
                }
            ]
        }

        response = self.client.post(
            "/api/sources/sync",
            json={"source_ids": ["src-pbc"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["llm_model"], None)
        self.assertEqual(payload["llm_enriched_count"], 0)
        self.assertEqual(payload["synced_count"], 0)
        self.assertEqual(payload["errors"][0]["source_id"], "src-pbc")

    @patch("app.services.ingestion.DemoIngestionService.run_live_workflow")
    def test_live_workflow_endpoint_returns_article_matches(self, mock_workflow) -> None:
        mock_workflow.return_value = {
            "source_id": "src-nfra",
            "source_name": "国家金融监督管理总局",
            "keywords": ["融资租赁"],
            "article_count": 1,
            "llm_enriched_count": 1,
            "llm_model": "cloud-qwen",
            "articles": [
                {
                    "title": "真实处罚公告",
                    "published_at": "2026-07-07",
                    "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1263776.pdf",
                    "institution_name": "某融资租赁有限公司",
                    "matched_keywords": ["融资租赁"],
                    "extractor": "nfra_pdf",
                    "summary": "LLM enriched summary",
                    "risk_hint": "LLM risk hint",
                    "english_brief": "LLM english brief",
                }
            ],
        }

        response = self.client.post(
            "/api/sources/src-nfra/live-workflow",
            json={"keywords": ["融资租赁"], "limit": 3},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(payload["articles"][0]["source_url"], "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1263776.pdf")

    @patch("app.services.ingestion.DemoIngestionService.run_direct_article_workflow")
    def test_direct_article_workflow_endpoint_returns_article(self, mock_workflow) -> None:
        mock_workflow.return_value = {
            "source_id": "src-sh-finance",
            "source_name": "上海市地方金融管理局",
            "article_count": 1,
            "llm_enriched_count": 1,
            "llm_model": "cloud-qwen",
            "articles": [
                {
                    "title": "关于开展融资租赁公司和商业保理公司现场检查的通知",
                    "published_at": "2026-07-01",
                    "source_url": "https://jrj.sh.gov.cn/example.html",
                    "institution_name": "Not disclosed in source article",
                    "matched_keywords": ["融资租赁", "商业保理"],
                    "extractor": "direct_article",
                    "summary": "LLM summary",
                    "risk_hint": "LLM risk hint",
                    "english_brief": "LLM brief",
                }
            ],
        }

        response = self.client.post(
            "/api/sources/src-sh-finance/direct-article-workflow",
            json={
                "article_url": "https://jrj.sh.gov.cn/example.html",
                "keywords": ["融资租赁", "商业保理"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(payload["articles"][0]["source_url"], "https://jrj.sh.gov.cn/example.html")

    @patch("app.services.ingestion.DemoIngestionService.run_url_workflow")
    def test_url_workflow_endpoint_returns_article_matches(self, mock_workflow) -> None:
        mock_workflow.return_value = {
            "source_id": "src-adhoc-test",
            "source_name": "国家金融监督管理总局",
            "source_url": "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411",
            "keywords": ["融资租赁"],
            "article_count": 1,
            "llm_enriched_count": 1,
            "llm_model": "Minimax China",
            "articles": [
                {
                    "title": "银行保险机构数据安全管理办法",
                    "published_at": "2024-12-27",
                    "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
                    "institution_name": "Not disclosed in source article",
                    "matched_keywords": ["金融租赁", "金融租赁公司"],
                    "extractor": "direct_pdf",
                    "summary": "LLM enriched summary",
                    "risk_hint": "LLM risk hint",
                    "english_brief": "LLM english brief",
                }
            ],
        }

        response = self.client.post(
            "/api/url-workflow",
            json={
                "url": "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411",
                "keywords": ["融资租赁"],
                "limit": 3,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(
            payload["articles"][0]["source_url"],
            "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
        )

    @patch("app.services.ai.requests.post")
    def test_ai_chat_endpoint_reports_upstream_model_error(self, mock_post) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "cloud-qwen",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        self.client.post("/api/models/current/cloud-qwen")
        mock_post.side_effect = RuntimeError("upstream model failed")

        response = self.client.post(
            "/api/ai/chat",
            json={"prompt": "Summarize this week's trend", "context": "gui-console"},
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("upstream model failed", response.get_json()["error"])

    @patch("app.services.ai.requests.post")
    def test_model_connection_test_endpoint(self, mock_post) -> None:
        self.client.post(
            "/api/models",
            json={
                "name": "cloud-test",
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
                "model_id": "qwen-max",
                "enabled": True,
            },
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "choices": [{"message": {"content": "pong"}}]
        }

        response = self.client.post("/api/models/cloud-test/test")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ok"], True)

    @patch("app.services.ai.requests.get")
    def test_model_catalog_endpoint_returns_available_models(self, mock_get) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": [
                {"id": "qwen-max"},
                {"id": "qwen-plus"},
            ]
        }

        response = self.client.post(
            "/api/models/catalog",
            json={
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1",
                "api_key": "secret",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["models"], ["qwen-max", "qwen-plus"])

    @patch("app.services.ai.requests.get")
    def test_model_catalog_endpoint_normalizes_base_url(self, mock_get) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"data": [{"id": "qwen-max"}]}

        response = self.client.post(
            "/api/models/catalog",
            json={
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1/chat/completions",
                "api_key": "secret",
            },
        )

        self.assertEqual(response.status_code, 200)
        args, _ = mock_get.call_args
        self.assertEqual(args[0], "https://api.example.com/v1/models")

    @patch("app.services.ai.requests.get")
    def test_model_catalog_endpoint_reports_error(self, mock_get) -> None:
        mock_get.side_effect = RuntimeError("catalog failed")

        response = self.client.post(
            "/api/models/catalog",
            json={
                "provider": "openai-compatible",
                "base_url": "https://api.example.com/v1",
                "api_key": "secret",
            },
        )

        self.assertEqual(response.status_code, 502)
        self.assertIn("catalog failed", response.get_json()["error"])

    def test_source_crud_endpoints(self) -> None:
        with patch("app.services.ingestion.DemoIngestionService.validate_source_url") as mock_validate:
            mock_validate.return_value = {
                "url": "https://jrj.beijing.gov.cn/custom",
                "title": "北京市地方金融管理局公告",
                "status_code": 200,
                "region": "北京",
            }
            created = self.client.post(
                "/api/sources",
                json={
                    "source_id": "src-custom-api",
                    "name": "API新增数据源",
                    "kind": "official-site",
                    "url": "https://jrj.beijing.gov.cn/custom",
                    "sync_url": "https://jrj.beijing.gov.cn/custom",
                    "parser": "generic_portal",
                    "region": "北京",
                    "status": "active",
                    "last_checked": "2026-07-07T09:00:00+08:00",
                    "note": "custom",
                },
            )
        self.assertEqual(created.status_code, 200)

        updated = self.client.post("/api/sources/src-custom-api/status/disabled")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["status"], "disabled")

        deleted = self.client.delete("/api/sources/src-custom-api")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json()["deleted"], "src-custom-api")

    def test_edit_source_endpoint(self) -> None:
        updated = self.client.put(
            "/api/sources/src-pbc",
            json={"region": "全国总部", "note": "preview enabled"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["region"], "全国总部")

    def test_sync_endpoint_accepts_source_ids(self) -> None:
        with patch("app.main.DemoIngestionService.sync_sources") as mock_sync:
            mock_sync.return_value = {
                "synced_count": 0,
                "event_count": 4,
                "errors": [],
                "processed_sources": ["src-pbc"],
                "period": "30d",
                "per_source_daily_limit": 3,
                "run_receipt_path": "C:/tmp/update_runs/sync-1.json",
            }
            response = self.client.post(
                "/api/sources/sync",
                json={"source_ids": ["src-pbc"], "period": "30d"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["processed_sources"], ["src-pbc"])
            self.assertEqual(payload["period"], "30d")
            self.assertIn("run_receipt_path", payload)

    def test_sources_endpoint_exposes_health_fields(self) -> None:
        response = self.client.get("/api/sources")

        self.assertEqual(response.status_code, 200)
        source = response.get_json()[0]
        self.assertIn("health_status", source)
        self.assertIn("last_sync_result", source)

    def test_sync_selected_source_reports_unsupported_source(self) -> None:
        response = self.client.post(
            "/api/sources/sync",
            json={"source_ids": ["src-bj-finance"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["processed_sources"], ["src-bj-finance"])
        self.assertEqual(payload["synced_count"], 0)
        self.assertEqual(payload["errors"][0]["source_id"], "src-bj-finance")

    def test_source_preview_endpoint(self) -> None:
        with patch("app.main.DemoIngestionService.preview_source") as mock_preview:
            mock_preview.return_value = {
                "source_id": "src-pbc",
                "event": {"title": "Preview Title"},
            }
            response = self.client.post("/api/sources/src-pbc/preview")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["source_id"], "src-pbc")

    def test_source_preview_endpoint_reports_fetch_error(self) -> None:
        with patch("app.main.DemoIngestionService.preview_source") as mock_preview:
            mock_preview.side_effect = RuntimeError("live fetch failed")

            response = self.client.post("/api/sources/src-pbc/preview")

            self.assertEqual(response.status_code, 502)
            self.assertIn("live fetch failed", response.get_json()["error"])

    def test_source_diagnostics_endpoint(self) -> None:
        with patch("app.main.DemoIngestionService.diagnose_source") as mock_diagnose:
            mock_diagnose.return_value = {
                "source_id": "src-nfra",
                "recommended_adapter": "nfra_docinfo",
                "fetch_mode": "dynamic_shell",
                "notes": ["Detected NFRA list API signature: /DocInfo/SelectDocByItemIdAndChild"],
            }

            response = self.client.get("/api/sources/src-nfra/diagnostics")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["recommended_adapter"], "nfra_docinfo")

    def test_events_endpoint_supports_period_filter(self) -> None:
        with patch("app.main.DemoIngestionService.list_events") as mock_list_events:
            mock_list_events.return_value = [
                {"event_id": "evt-b"},
                {"event_id": "evt-a"},
            ]
            response = self.client.get(
                "/api/events?from=2026-07-01&to=2026-07-03"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([item["event_id"] for item in payload], ["evt-b", "evt-a"])

    def test_delete_event_endpoint_removes_event_and_writes_ledger(self) -> None:
        self._seed_runtime_event()

        response = self.client.delete(
            "/api/events/manual-edit-event",
            json={"deleted_by": "analyst@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted"], "manual-edit-event")
        events = self.client.get("/api/events").get_json()
        self.assertNotIn("manual-edit-event", [item["event_id"] for item in events])
        deletion_ledger = Path(self.tempdir.name) / "intelligence" / "deleted_events.jsonl"
        self.assertTrue(deletion_ledger.exists())
        ledger_text = deletion_ledger.read_text(encoding="utf-8")
        self.assertIn("manual-edit-event", ledger_text)
        self.assertIn("analyst@example.com", ledger_text)

    def test_review_endpoint_supports_editing_human_opinion(self) -> None:
        self._seed_runtime_event()

        response = self.client.post(
            "/api/events/manual-edit-event/review",
            json={
                "reviewer": "compliance@example.com",
                "status": "reviewed",
                "note": "Adjusted after human review.",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["review_status"], "reviewed")
        self.assertEqual(payload["reviewer"], "compliance@example.com")
        self.assertEqual(payload["review_notes"], "Adjusted after human review.")
        review_ledger = Path(self.tempdir.name) / "user_reviews" / "review_decisions.jsonl"
        self.assertTrue(review_ledger.exists())
        self.assertIn("Adjusted after human review.", review_ledger.read_text(encoding="utf-8"))

    def test_ai_opinion_edit_endpoint_writes_append_only_record(self) -> None:
        response = self.client.put(
            "/api/ai/opinions/ai-manual-edit",
            json={
                "answer": "Edited management-facing compliance opinion.",
                "edited_by": "analyst@example.com",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["opinion_id"], "ai-manual-edit")
        self.assertEqual(payload["action"], "edited")
        self.assertEqual(payload["edited_by"], "analyst@example.com")
        ai_ledger = Path(self.tempdir.name) / "ai_opinions" / "llm_runs.jsonl"
        self.assertTrue(ai_ledger.exists())
        self.assertIn("Edited management-facing compliance opinion.", ai_ledger.read_text(encoding="utf-8"))

    def test_source_discovery_endpoint_accepts_url_or_name(self) -> None:
        response = self.client.post(
            "/api/sources/discover",
            json={"query": "中国人民银行"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["source"]["name"], "中国人民银行")
        self.assertEqual(payload["source"]["source_id"], "src-pbc")
