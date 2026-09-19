import tempfile
import unittest
import io
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.services.ingestion import DemoIngestionService
from app.store import JsonStateStore


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = JsonStateStore(Path(self.tempdir.name) / "state.json")
        self.service = DemoIngestionService(
            store=self.store,
            seeds_path=Path("data/seeds/sample_events.json"),
            sources_path=Path("data/sources/demo_sources.json"),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _sync_sources_in_fixture_window(self, **kwargs) -> dict:
        with patch.object(
            self.service,
            "_period_start_date",
            return_value=date(2026, 6, 8),
        ):
            return self.service.sync_sources(**kwargs)

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

    def test_bootstrap_loads_seed_data(self) -> None:
        snapshot = self.service.bootstrap()

        self.assertEqual(snapshot["summary"]["total_events"], 0)
        self.assertEqual(snapshot["summary"]["major_events"], 0)
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["models"]["current_model"], "Minimax China")
        self.assertIn("management_dashboard", snapshot)
        self.assertEqual(
            snapshot["management_dashboard"]["penalty_intelligence"],
            [],
        )

    def test_review_decision_updates_event_status(self) -> None:
        seed_state = self.service._migrate_events(self.service._load_seed_state())
        self.store.save(seed_state)
        event_id = seed_state["events"][0]["event_id"]

        updated = self.service.apply_review(
            event_id=event_id,
            reviewer="analyst@example.com",
            status="approved",
            note="Reviewed for demo",
        )

        self.assertEqual(updated["review_status"], "approved")
        self.assertEqual(updated["reviewer"], "analyst@example.com")
        self.assertIn("Reviewed for demo", updated["review_notes"])
        review_ledger = Path(self.tempdir.name) / "user_reviews" / "review_decisions.jsonl"
        self.assertTrue(review_ledger.exists())
        self.assertIn(event_id, review_ledger.read_text(encoding="utf-8"))

    def test_reset_preserves_existing_events_and_reviews(self) -> None:
        seed_state = self.service._load_seed_state()
        source_id = seed_state["sources"][0]["source_id"]
        existing_event_id = "preserved-real-event"
        seed_state["events"] = [
            {
                "event_id": existing_event_id,
                "title": "远东融资租赁有限公司行政处罚公告",
                "regulator": "国家金融监督管理总局",
                "region": "全国",
                "category": "监管处罚",
                "institution_type": "融资租赁",
                "institution_name": "远东融资租赁有限公司",
                "institution_name_original": "远东融资租赁有限公司",
                "severity": "major",
                "published_at": "2026-07-10T09:00:00",
                "summary": "融资租赁公司相关处罚。",
                "risk_hint": "Review financing lease controls.",
                "english_brief": "Preserved event.",
                "analysis_summary": "Preserved analysis.",
                "penalty_focus": "Asset authenticity",
                "compliance_warning": "Preserved warning.",
                "is_penalty_event": True,
                "review_status": "approved",
                "reviewer": "analyst@example.com",
                "review_notes": "Keep this review",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [
                    {
                        "source_id": source_id,
                        "title": "远东融资租赁有限公司行政处罚公告",
                        "url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/preserved.pdf",
                        "published_at": "2026-07-10T09:00:00",
                    }
                ],
                "evidence": [],
            }
        ]
        self.store.save(seed_state)

        reset_snapshot = self.service.reset()

        preserved = next(
            event for event in reset_snapshot["events"] if event["event_id"] == existing_event_id
        )
        self.assertEqual(preserved["review_status"], "approved")
        self.assertEqual(preserved["reviewer"], "analyst@example.com")
        self.assertEqual(preserved["review_notes"], "Keep this review")

    def test_sync_sources_adds_fetched_event_and_evidence(self) -> None:
        result = self._sync_sources_in_fixture_window(
            fetch_html=self._seed_fetch,
            period="30d",
        )

        self.assertGreaterEqual(result["synced_count"], 6)
        self.assertGreaterEqual(result["event_count"], 10)
        evidence_dir = Path(self.tempdir.name) / "evidence"
        self.assertTrue(any(evidence_dir.rglob("*.html")))
        state = self.store.load()
        synced_events = [event for event in state["events"] if event["event_id"].startswith("sync-")]
        self.assertTrue(synced_events)
        self.assertTrue(all(event["sources"][0]["url"] for event in synced_events[:2]))
        self.assertTrue(all(event.get("analysis_summary") for event in synced_events[:2]))
        self.assertTrue(any(event.get("penalty_focus") for event in synced_events))

    def test_export_reports_writes_csv_html_and_pdf(self) -> None:
        self.service.bootstrap()

        exports = self.service.export_reports(
            output_dir=Path(self.tempdir.name) / "exports",
        )

        self.assertTrue(Path(exports["csv"]).exists())
        self.assertTrue(Path(exports["html"]).exists())
        self.assertTrue(Path(exports["pdf"]).exists())

    def test_export_reports_can_scope_to_sources_module(self) -> None:
        self.service.bootstrap()

        exports = self.service.export_reports(
            module="sources",
            output_dir=Path(self.tempdir.name) / "exports_sources",
        )

        self.assertEqual(exports["module"], "sources")
        self.assertTrue(Path(exports["csv"]).exists())

    def test_sync_sources_reports_errors_when_live_fetch_fails(self) -> None:
        with patch.object(
            self.service,
            "_fetch_nfra_policy_metadata_articles",
            return_value=[
                {
                    "doc_id": "policy-offline-fixture",
                    "title": "金融租赁公司融资租赁业务管理办法",
                    "summary": "监管强调金融租赁公司融资租赁业务报送与披露要求。",
                    "published_at": "2026-07-15",
                    "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/policy-offline-fixture.pdf",
                }
            ],
        ):
            result = self._sync_sources_in_fixture_window(
                period="30d",
                fetch_html=lambda url, timeout=15: (_ for _ in ()).throw(RuntimeError("offline"))
            )

        self.assertGreater(result["synced_count"], 0)
        self.assertEqual(len(result["errors"]), 3)

    def test_sync_sources_reports_period_and_daily_limit(self) -> None:
        result = self.service.sync_sources(
            period="today",
            fetch_html=lambda url, timeout=15: (_ for _ in ()).throw(RuntimeError("offline"))
        )

        self.assertEqual(result["period"], "today")
        self.assertEqual(result["per_source_daily_limit"], 3)

    def test_bootstrap_refreshes_source_metadata_from_latest_registry(self) -> None:
        snapshot = self.service.bootstrap()
        del snapshot["sources"][0]["fallback_html"]
        self.store.save(
            {
                "initialized_at": "2026-07-07T00:00:00+00:00",
                "events": snapshot["events"],
                "sources": snapshot["sources"],
                "models": snapshot["models"],
            }
        )

        refreshed = self.service.bootstrap()

        self.assertIn("fallback_html", refreshed["sources"][0])

    def test_bootstrap_preserves_original_institution_names(self) -> None:
        snapshot = self.service._migrate_events(self.service._load_seed_state())
        legacy_events = snapshot["events"]
        legacy_events[0]["institution_name"] = "测试保理"
        legacy_events[0].pop("institution_name_original", None)
        legacy_events[1]["institution_name"] = "示例融资租赁有限公司"
        legacy_events[1].pop("institution_name_original", None)
        self.store.save(
            {
                "initialized_at": "2026-07-07T00:00:00+00:00",
                "events": legacy_events,
                "sources": snapshot["sources"],
                "models": snapshot["models"],
            }
        )

        refreshed = self.service._migrate_events(self.store.load())

        self.assertEqual(
            refreshed["events"][0]["institution_name_original"],
            "测试保理",
        )
        self.assertEqual(
            refreshed["events"][1]["institution_name_original"],
            "示例融资租赁有限公司",
        )

    def test_add_delete_and_disable_source(self) -> None:
        self.service.bootstrap()

        self.service.validate_source_url = lambda url: {
            "url": url,
            "title": "北京市地方金融管理局公告",
            "status_code": 200,
            "region": "北京",
        }
        created = self.service.add_source(
            {
                "source_id": "src-custom-demo",
                "name": "自定义测试源",
                "kind": "official-site",
                "url": "https://jrj.beijing.gov.cn/custom",
                "sync_url": "https://jrj.beijing.gov.cn/custom",
                "parser": "generic_portal",
                "region": "北京",
                "status": "active",
                "last_checked": "2026-07-07T09:00:00+08:00",
                "note": "custom",
            }
        )
        self.assertEqual(created["source_id"], "src-custom-demo")

        disabled = self.service.update_source_status("src-custom-demo", "disabled")
        self.assertEqual(disabled["status"], "disabled")

        removed = self.service.delete_source("src-custom-demo")
        self.assertEqual(removed["deleted"], "src-custom-demo")

    def test_sync_single_source_only_updates_selected_source(self) -> None:
        fixtures_dir = Path("tests/fixtures")

        def fake_fetch(url: str, timeout: int = 15) -> str:
            if "pbc" in url:
                return (fixtures_dir / "pbc_sample.html").read_text(encoding="utf-8")
            raise RuntimeError("offline")

        result = self.service.sync_sources(
            source_ids=["src-pbc"],
            fetch_html=fake_fetch,
        )

        self.assertEqual(result["synced_count"], 0)
        self.assertEqual(result["processed_sources"], ["src-pbc"])
        self.assertEqual(result["errors"][0]["source_id"], "src-pbc")

    def test_update_source_changes_fields(self) -> None:
        self.service.bootstrap()

        updated = self.service.update_source(
            "src-pbc",
            {
                "name": "中国人民银行江西分支",
                "region": "江西南昌",
                "note": "updated",
            },
        )

        self.assertEqual(updated["name"], "中国人民银行江西分支")
        self.assertEqual(updated["region"], "江西南昌")

    def test_preview_source_returns_parsed_event_without_persisting(self) -> None:
        fixtures_dir = Path("tests/fixtures")

        def preview_fetch(url: str, timeout: int = 15) -> str:
            if "113469" in url:
                return (fixtures_dir / "pbc_listing.html").read_text(encoding="utf-8")
            if "pbc-detail-1" in url:
                return (fixtures_dir / "pbc_sample.html").read_text(encoding="utf-8")
            if "pbc-detail-2" in url:
                return (fixtures_dir / "pbc_detail_2.html").read_text(encoding="utf-8")
            raise AssertionError(f"Unexpected URL: {url}")

        preview = self.service.preview_source(
            "src-pbc",
            fetch_html=preview_fetch,
        )

        self.assertEqual(preview["source_id"], "src-pbc")
        self.assertIn("event", preview)
        self.assertEqual(preview["event"]["institution_name_original"], "江西示例商业保理有限公司")
        snapshot = self.service.bootstrap()
        self.assertEqual(snapshot["summary"]["total_events"], 0)

    def test_bootstrap_keeps_source_subject_names_as_stored(self) -> None:
        snapshot = self.service._migrate_events(self.service._load_seed_state())

        names = {event["institution_name_original"] for event in snapshot["events"]}

        self.assertIn("示例融资租赁有限公司", names)
        self.assertIn("示例商业保理有限公司", names)

    def test_preview_source_reports_error_when_live_fetch_fails(self) -> None:
        with self.assertRaises(RuntimeError):
            self.service.preview_source(
                "src-pbc",
                fetch_html=lambda url, timeout=15: (_ for _ in ()).throw(RuntimeError("offline")),
            )

    def test_missing_institution_is_not_invented_from_title(self) -> None:
        event = self.service._event_from_article(
            source={
                "source_id": "src-test",
                "name": "测试监管机构",
                "region": "测试",
                "sync_url": "https://example.com/source",
            },
            article={
                "title": "某融资租赁公司行政处罚公告",
                "published_at": "2026-07-07",
                "summary": "监管处罚",
                "source_url": "https://example.com/article-1",
            },
            html=(
                "<html><body>"
                "<h1>某融资租赁公司行政处罚公告</h1>"
                "<div class='meta'>发布日期：2026-07-07</div>"
                "<div class='institution'>机构名称：</div>"
                "<div class='category'>违法行为类型：信息报送不及时</div>"
                "<div class='summary'>相关机构因报送不及时被公开处罚。</div>"
                "</body></html>"
            ),
        )

        self.assertEqual(event["institution_name_original"], "Not disclosed in source article")

    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    def test_nfra_adapter_articles_can_be_ingested(self, mock_fetch_penalty_articles) -> None:
        mock_fetch_penalty_articles.return_value = [
            {
                "doc_id": "1263776",
                "title": "国家金融监督管理总局融资租赁公司行政处罚信息公开表",
                "published_at": "2026-07-07",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1263776.pdf",
                "summary": "内部控制管理不到位",
                "institution_name": "某融资租赁有限公司",
                "penalty_text": "罚款35万元",
                "regulator_name": "国家金融监督管理总局赣州监管分局",
                "raw_text": "某融资租赁有限公司 内部控制管理不到位 罚款35万元",
            }
        ]

        result = self._sync_sources_in_fixture_window(
            source_ids=["src-nfra"],
            period="30d",
        )

        self.assertEqual(result["synced_count"], 1)

    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    def test_live_workflow_returns_real_article_level_matches(self, mock_fetch_penalty_articles) -> None:
        mock_fetch_penalty_articles.return_value = [
            {
                "doc_id": "1263776",
                "title": "国家金融监督管理总局赣州监管分局行政处罚信息公开表",
                "published_at": "2026-07-07",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1263776.pdf",
                "summary": "内部控制管理不到位",
                "institution_name": "某融资租赁有限公司",
                "penalty_text": "罚款35万元",
                "regulator_name": "国家金融监督管理总局赣州监管分局",
                "raw_text": "某融资租赁有限公司 内部控制管理不到位 罚款35万元",
            }
        ]

        payload = self.service.run_live_workflow(
            source_id="src-nfra",
            keywords=["融资租赁"],
            limit=5,
        )

        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(
            payload["articles"][0]["source_url"],
            "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1263776.pdf",
        )
        self.assertEqual(payload["articles"][0]["institution_name"], "某融资租赁有限公司")
        self.assertEqual(payload["articles"][0]["matched_keywords"], ["融资租赁"])

    @patch("app.services.article_crawler.ArticleCrawlerService.analyze_direct_article")
    def test_direct_article_workflow_returns_llm_ready_article(self, mock_analyze_direct_article) -> None:
        mock_analyze_direct_article.return_value = {
            "source_id": "src-sh-finance",
            "source_name": "上海市地方金融管理局",
            "title": "关于开展融资租赁公司和商业保理公司现场检查的通知",
            "published_at": "2026-07-01",
            "source_url": "https://jrj.sh.gov.cn/example.html",
            "institution_name": "Not disclosed in source article",
            "body_text": "融资租赁公司 商业保理公司 现场检查",
            "matched_keywords": ["融资租赁", "商业保理"],
            "extractor": "direct_article",
        }

        payload = self.service.run_direct_article_workflow(
            source_id="src-sh-finance",
            article_url="https://jrj.sh.gov.cn/example.html",
            keywords=["融资租赁", "商业保理"],
        )

        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(payload["articles"][0]["source_url"], "https://jrj.sh.gov.cn/example.html")
        self.assertEqual(payload["articles"][0]["matched_keywords"], ["融资租赁", "商业保理"])

    @patch("app.services.article_crawler.ArticleCrawlerService._fetch_html")
    def test_direct_article_extracts_company_name_and_page_date(self, mock_fetch_html) -> None:
        mock_fetch_html.return_value = """
        <html>
          <head>
            <title>上海市地方金融管理局&lt;br/&gt;行政处罚信息公开表_站点名称</title>
            <meta name="ArticleTitle" content="上海市地方金融管理局&lt;br/&gt;行政处罚信息公开表（沪金管罚决字〔2025〕2号）">
          </head>
          <body>
            <div>信息来源：上海市地方金融管理局 发布时间：2025-08-18</div>
            <table>
              <tr><td>被处罚人信息</td><td>公司名称</td><td>裕华融资租赁（上海）有限公司</td></tr>
              <tr><td>案件信息</td><td>处罚事由</td><td>未按规定报送经营信息</td></tr>
              <tr><td>行政处罚决定</td><td>罚款人民币五万元</td></tr>
            </table>
          </body>
        </html>
        """

        article = self.service.article_crawler.analyze_direct_article(
            source={"source_id": "src-sh-finance", "name": "上海市地方金融管理局"},
            article_url="https://jrj.sh.gov.cn/XZCF233/example.html",
            keywords=["融资租赁", "行政处罚"],
        )

        self.assertEqual(
            article["title"],
            "上海市地方金融管理局 行政处罚信息公开表（沪金管罚决字〔2025〕2号）",
        )
        self.assertEqual(article["published_at"], "2025-08-18")
        self.assertEqual(article["institution_name"], "裕华融资租赁（上海）有限公司")

    @patch("app.services.article_crawler.ArticleCrawlerService.analyze_direct_article")
    def test_direct_article_workflow_persists_event_and_source_evidence(self, mock_analyze_direct_article) -> None:
        article_url = "https://jrj.sh.gov.cn/XZCF233/20250818/verified.html"
        mock_analyze_direct_article.return_value = {
            "source_id": "src-sh-finance",
            "source_name": "上海市地方金融管理局",
            "title": "上海市地方金融管理局行政处罚信息公开表（沪金管罚决字〔2025〕2号）",
            "published_at": "2025-08-18",
            "source_url": article_url,
            "institution_name": "裕华融资租赁（上海）有限公司",
            "body_text": "裕华融资租赁（上海）有限公司未按规定报送经营信息，罚款人民币五万元。",
            "raw_html": "<html><body>裕华融资租赁（上海）有限公司 罚款人民币五万元</body></html>",
            "matched_keywords": ["融资租赁", "行政处罚"],
            "extractor": "direct_article",
        }

        payload = self.service.run_direct_article_workflow(
            source_id="src-sh-finance",
            article_url=article_url,
            keywords=["融资租赁", "行政处罚"],
        )

        self.assertTrue(payload["event_added"])
        persisted = payload["persisted_event"]
        self.assertEqual(persisted["institution_name_original"], "裕华融资租赁（上海）有限公司")
        self.assertEqual(persisted["sources"][0]["url"], article_url)
        evidence_path = Path(persisted["evidence"][0]["path"])
        self.assertTrue(evidence_path.exists())
        self.assertIn("裕华融资租赁（上海）有限公司", evidence_path.read_text(encoding="utf-8"))
        self.assertIn(persisted["event_id"], [event["event_id"] for event in self.store.load()["events"]])

    @patch("app.services.article_crawler.requests.get")
    @patch("app.services.article_crawler.pdfplumber.open")
    def test_direct_pdf_article_can_be_analyzed(self, mock_pdf_open, mock_get) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = b"%PDF-demo"

        class FakePage:
            def extract_text(self):
                return "融资租赁公司监管通知 当事人名称：某融资租赁有限公司 主要违法违规行为：信息报送不及时"

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        mock_pdf_open.return_value = FakePdf()

        article = self.service.article_crawler.analyze_direct_article(
            source={"source_id": "src-nfra", "name": "国家金融监督管理总局"},
            article_url="https://www.nfra.gov.cn/chinese/OFFICE/PDF/demo.pdf",
            keywords=["融资租赁"],
        )

        self.assertEqual(article["extractor"], "direct_pdf")
        self.assertIn("融资租赁", article["matched_keywords"])

    @patch("app.services.ingestion.DemoIngestionService.validate_source_url")
    @patch("app.services.article_crawler.ArticleCrawlerService.fetch_relevant_articles")
    def test_url_workflow_can_run_against_user_supplied_source_url(
        self,
        mock_fetch_relevant_articles,
        mock_validate_source_url,
    ) -> None:
        mock_validate_source_url.return_value = {
            "url": "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411",
            "title": "国家金融监督管理总局",
            "status_code": 200,
            "region": "全国",
        }
        mock_fetch_relevant_articles.return_value = [
            {
                "title": "银行保险机构数据安全管理办法",
                "published_at": "2024-12-27",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
                "institution_name": "Not disclosed in source article",
                "matched_keywords": ["金融租赁", "金融租赁公司"],
                "extractor": "direct_pdf",
                "summary": "适用于金融租赁公司等机构的数据安全办法。",
                "body_text": "适用于金融租赁公司等机构的数据安全办法。",
                "regulator_name": "国家金融监督管理总局",
            }
        ]

        payload = self.service.run_url_workflow(
            url="https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411",
            keywords=["融资租赁"],
            limit=3,
        )

        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(payload["source_name"], "国家金融监督管理总局")
        self.assertEqual(
            payload["articles"][0]["source_url"],
            "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
        )

    def test_keyword_expansion_supports_financial_leasing_aliases(self) -> None:
        expanded = self.service.article_crawler._expand_keywords(["融资租赁", "商业保理"])

        self.assertIn("金融租赁", expanded)
        self.assertIn("金融租赁公司", expanded)
        self.assertIn("保理公司", expanded)

    def test_duckduckgo_wrapped_result_url_is_unwrapped(self) -> None:
        wrapped = (
            "//duckduckgo.com/l/?uddg="
            "https%3A%2F%2Fwww.nfra.gov.cn%2Fcn%2Fview%2Fpages%2FItemDetail.html%3FdocId%3D1236230%26itemId%3D928"
            "&rut=dummy"
        )

        unwrapped = self.service.article_crawler._unwrap_search_result_url(wrapped)

        self.assertEqual(
            unwrapped,
            "https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId=1236230&itemId=928",
        )

    @patch("app.services.article_crawler.ArticleCrawlerService._discover_official_articles_via_search")
    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    def test_nfra_workflow_can_fall_back_to_official_deeper_policy_results(
        self,
        mock_fetch_penalty_articles,
        mock_discover_official_articles,
    ) -> None:
        mock_fetch_penalty_articles.return_value = []
        mock_discover_official_articles.return_value = [
            {
                "title": "银行保险机构数据安全管理办法",
                "summary": "",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
            }
        ]

        with patch.object(
            self.service.article_crawler,
            "_analyze_direct_pdf",
            return_value={
                "source_id": "src-nfra",
                "source_name": "国家金融监督管理总局",
                "title": "银行保险机构数据安全管理办法",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
                "institution_name": "Not disclosed in source article",
                "body_text": "金融租赁公司 数据安全管理办法",
                "matched_keywords": ["金融租赁", "金融租赁公司"],
                "extractor": "direct_pdf",
            },
        ):
            payload = self.service.run_live_workflow(
                source_id="src-nfra",
                keywords=["融资租赁"],
                limit=3,
            )

        self.assertGreaterEqual(payload["article_count"], 1)
        self.assertTrue(
            all(
                article["source_url"].startswith("https://www.nfra.gov.cn/chinese/OFFICE/PDF/")
                for article in payload["articles"]
            )
        )
        self.assertTrue(
            any("金融租赁" in article["title"] or "金融租赁" in " ".join(article["matched_keywords"]) for article in payload["articles"])
        )

    @patch("app.services.article_crawler.requests.get")
    def test_nfra_policy_articles_use_official_docinfo_feeds(self, mock_get) -> None:
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, headers=None, timeout=None, verify=None):
            if "data_itemId=931,pageSize=10.json" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})
            if "data_itemId=916,pageSize=10.json" in url:
                return FakeResponse(
                    {
                        "rptCode": 200,
                        "msg": "成功",
                        "data": [
                            {
                                "itemId": 917,
                                "itemName": "政策解读",
                                "docInfoVOList": [
                                    {
                                        "docId": 1192308,
                                        "docTitle": "银行保险机构数据安全管理办法",
                                        "docSubtitle": "金融租赁公司数据安全要求",
                                        "publishDate": "2024-12-27 10:00:00",
                                        "docSummary": "",
                                        "pdfFileUrl": "/chinese/OFFICE/PDF/1192308.pdf",
                                    }
                                ],
                            }
                        ],
                    }
                )
            if "data_itemId=926,pageSize=10.json" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})
            raise AssertionError(f"Unexpected URL: {url}")

        mock_get.side_effect = fake_get

        with patch.object(
            self.service.article_crawler,
            "_analyze_direct_pdf",
            return_value={
                "source_id": "src-nfra",
                "source_name": "国家金融监督管理总局",
                "title": "银行保险机构数据安全管理办法",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
                "institution_name": "Not disclosed in source article",
                "body_text": "金融租赁公司 数据安全管理办法",
                "matched_keywords": ["金融租赁", "金融租赁公司"],
                "extractor": "direct_pdf",
            },
        ):
            payload = self.service.run_live_workflow(
                source_id="src-nfra",
                keywords=["融资租赁"],
                limit=3,
            )

        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(
            payload["articles"][0]["source_url"],
            "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
        )
        self.assertIn("金融租赁公司", payload["articles"][0]["matched_keywords"])

    @patch("app.services.article_crawler.requests.get")
    def test_nfra_policy_articles_can_match_keywords_from_pdf_body_not_metadata(self, mock_get) -> None:
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, headers=None, timeout=None, verify=None):
            if "data_itemId=931,pageSize=10.json" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})
            if "data_itemId=916,pageSize=10.json" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})
            if "data_itemId=926,pageSize=10.json" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})
            if "data_itemId=4213,pageSize=10.json" in url:
                return FakeResponse(
                    {
                        "rptCode": 200,
                        "msg": "成功",
                        "data": [
                            {
                                "itemId": 4214,
                                "itemName": "规章",
                                "docInfoVOList": [
                                    {
                                        "docId": 1192308,
                                        "docTitle": "银行保险机构数据安全管理办法",
                                        "docSubtitle": "",
                                        "publishDate": "2024-12-27 10:00:00",
                                        "docSummary": "规范银行保险机构数据治理。",
                                        "pdfFileUrl": "/chinese/OFFICE/PDF/1192308.pdf",
                                    }
                                ],
                            }
                        ],
                    }
                )
            return FakeResponse({"rptCode": 200, "msg": "成功", "data": []})

        mock_get.side_effect = fake_get

        with patch.object(
            self.service.article_crawler,
            "_analyze_direct_pdf",
            return_value={
                "source_id": "src-nfra",
                "source_name": "国家金融监督管理总局",
                "title": "银行保险机构数据安全管理办法",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
                "institution_name": "Not disclosed in source article",
                "body_text": "本办法适用于金融租赁公司、汽车金融公司、消费金融公司等机构。",
                "matched_keywords": ["金融租赁", "金融租赁公司"],
                "extractor": "direct_pdf",
            },
        ):
            payload = self.service.run_live_workflow(
                source_id="src-nfra",
                keywords=["融资租赁"],
                limit=3,
            )

        self.assertEqual(payload["article_count"], 1)
        self.assertEqual(
            payload["articles"][0]["source_url"],
            "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1192308.pdf",
        )
        self.assertIn("金融租赁公司", payload["articles"][0]["matched_keywords"])

    def test_list_events_supports_period_filter(self) -> None:
        snapshot = self.service.bootstrap()
        state = self.store.load()
        configured_source_id = snapshot["sources"][0]["source_id"]
        state["events"] = [
            {
                "event_id": "evt-a",
                "title": "华融融资租赁有限公司监管公告A",
                "regulator": "国家金融监督管理总局测试监管局",
                "region": "测试",
                "category": "监管处罚",
                "institution_type": "融资租赁",
                "institution_name": "华融融资租赁有限公司",
                "institution_name_original": "华融融资租赁有限公司",
                "severity": "major",
                "published_at": "2026-07-01T09:00:00",
                "summary": "融资租赁相关处罚A。",
                "risk_hint": "A",
                "english_brief": "A",
                "analysis_summary": "A",
                "penalty_focus": "A",
                "compliance_warning": "A",
                "is_penalty_event": True,
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": configured_source_id, "title": "A", "url": "https://www.pbc.gov.cn/detail/a.html", "published_at": "2026-07-01T09:00:00"}],
                "evidence": [],
            },
            {
                "event_id": "evt-b",
                "title": "盛业商业保理有限公司监管公告B",
                "regulator": "国家金融监督管理总局测试监管局",
                "region": "测试",
                "category": "监管处罚",
                "institution_type": "商业保理",
                "institution_name": "盛业商业保理有限公司",
                "institution_name_original": "盛业商业保理有限公司",
                "severity": "major",
                "published_at": "2026-07-03T09:00:00",
                "summary": "商业保理相关处罚B。",
                "risk_hint": "B",
                "english_brief": "B",
                "analysis_summary": "B",
                "penalty_focus": "B",
                "compliance_warning": "B",
                "is_penalty_event": True,
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": configured_source_id, "title": "B", "url": "https://www.pbc.gov.cn/detail/b.html", "published_at": "2026-07-03T09:00:00"}],
                "evidence": [],
            },
            {
                "event_id": "evt-c",
                "title": "远东融资租赁有限公司监管公告C",
                "regulator": "国家金融监督管理总局测试监管局",
                "region": "测试",
                "category": "监管处罚",
                "institution_type": "融资租赁",
                "institution_name": "远东融资租赁有限公司",
                "institution_name_original": "远东融资租赁有限公司",
                "severity": "major",
                "published_at": "2026-07-05T09:00:00",
                "summary": "融资租赁相关处罚C。",
                "risk_hint": "C",
                "english_brief": "C",
                "analysis_summary": "C",
                "penalty_focus": "C",
                "compliance_warning": "C",
                "is_penalty_event": True,
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": configured_source_id, "title": "C", "url": "https://www.pbc.gov.cn/detail/c.html", "published_at": "2026-07-05T09:00:00"}],
                "evidence": [],
            },
        ]
        self.store.save(state)

        events = self.service.list_events(date_from="2026-07-01", date_to="2026-07-03")

        self.assertEqual([item["event_id"] for item in events], ["evt-b", "evt-a"])

    def test_snapshot_is_limited_to_recent_10_relevant_events(self) -> None:
        snapshot = self.service.bootstrap()
        state = self.store.load()
        extra_events = []
        for index in range(12):
            extra_events.append(
                {
                    "event_id": f"extra-{index}",
                    "title": f"远东融资租赁有限公司监管公告 {index}",
                    "regulator": "国家金融监督管理总局测试监管局",
                    "region": "测试",
                    "category": "监管处罚",
                    "institution_type": "融资租赁",
                    "institution_name": "远东融资租赁有限公司",
                    "institution_name_original": "远东融资租赁有限公司",
                    "severity": "major",
                    "published_at": f"2026-07-{10 + index:02d}T09:00:00",
                    "summary": "融资租赁公司相关处罚。",
                    "risk_hint": "处罚关注融资租赁控制问题。",
                    "english_brief": "Test event.",
                    "analysis_summary": "Test analysis.",
                    "penalty_focus": "Test focus.",
                    "compliance_warning": "Test warning.",
                    "is_penalty_event": True,
                    "review_status": "pending",
                    "reviewer": None,
                    "review_notes": "",
                    "source_link_verified": True,
                    "article_opened": True,
                    "original_subject_extracted": True,
                    "llm_analysis_completed": False,
                    "extraction_confidence": "high",
                    "sources": [
                        {
                            "source_id": snapshot["sources"][0]["source_id"],
                            "title": f"测试公告 {index}",
                            "url": f"https://www.pbc.gov.cn/detail/article-{index}.html",
                            "published_at": f"2026-07-{10 + index:02d}T09:00:00",
                        }
                    ],
                    "evidence": [],
                }
            )
        state["events"] = extra_events + state["events"]
        self.store.save(state)

        refreshed = self.service.bootstrap()

        self.assertEqual(len(refreshed["events"]), 10)
        self.assertEqual(refreshed["events"][0]["event_id"], "extra-11")

    def test_build_risk_outlook_summarizes_recent_signals(self) -> None:
        snapshot = self.service.bootstrap()
        state = self.store.load()
        source_id = snapshot["sources"][0]["source_id"]
        state["events"] = [
            {
                "event_id": "risk-1",
                "title": "盛业商业保理有限公司关于客户资金管理的处罚公告",
                "regulator": "中国人民银行",
                "region": "全国",
                "category": "信用风险",
                "institution_type": "商业保理",
                "institution_name": "盛业商业保理有限公司",
                "institution_name_original": "盛业商业保理有限公司",
                "severity": "major",
                "published_at": "2026-07-08T09:00:00",
                "summary": "客户资金管理不到位。",
                "risk_hint": "Early warning: review customer funds controls.",
                "english_brief": "risk",
                "analysis_summary": "summary",
                "penalty_focus": "Customer funds monitoring",
                "compliance_warning": "warning",
                "is_penalty_event": True,
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": source_id, "title": "x", "url": "https://www.pbc.gov.cn/detail/risk-1.html", "published_at": "2026-07-08T09:00:00"}],
                "evidence": [],
            }
        ]
        self.store.save(state)
        snapshot = self.service.bootstrap()

        outlook = self.service.build_risk_outlook(snapshot["events"])

        self.assertIn("trend_summary", outlook)
        self.assertIn("priority_risks", outlook)
        self.assertGreaterEqual(len(outlook["priority_risks"]), 1)

    def test_management_dashboard_builds_management_warning(self) -> None:
        snapshot = self.service.bootstrap()
        state = self.store.load()
        source_id = snapshot["sources"][0]["source_id"]
        state["events"] = [
            {
                "event_id": "mgmt-1",
                "title": "远东融资租赁有限公司信息披露处罚公告",
                "regulator": "国家金融监督管理总局",
                "region": "全国",
                "category": "信息披露",
                "institution_type": "融资租赁",
                "institution_name": "远东融资租赁有限公司",
                "institution_name_original": "远东融资租赁有限公司",
                "severity": "major",
                "published_at": "2026-07-08T09:00:00",
                "summary": "信息披露不及时。",
                "risk_hint": "warning",
                "english_brief": "brief",
                "analysis_summary": "analysis",
                "penalty_focus": "Disclosure and reporting discipline",
                "compliance_warning": "warning",
                "is_penalty_event": True,
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": source_id, "title": "x", "url": "https://www.nfra.gov.cn/detail/mgmt-1.html", "published_at": "2026-07-08T09:00:00"}],
                "evidence": [],
            }
        ]
        self.store.save(state)
        snapshot = self.service.bootstrap()

        management_dashboard = snapshot["management_dashboard"]

        self.assertIn("headline", management_dashboard)
        self.assertGreaterEqual(len(management_dashboard["top_penalty_reasons"]), 1)
        self.assertIn(
            "Siemens Financial Leasing",
            management_dashboard["early_warning"]["summary"],
        )
        self.assertNotIn("highest_penalty_region", management_dashboard)
        self.assertIn("control_domains", management_dashboard["early_warning"])
        self.assertIn("management_actions", management_dashboard["early_warning"])

    def test_discover_source_by_name_returns_registry_match(self) -> None:
        match = self.service.discover_source("中国人民银行")

        self.assertEqual(match["source_id"], "src-pbc")
        self.assertEqual(match["name"], "中国人民银行")

    def test_validate_source_url_rejects_non_regulatory_pages(self) -> None:
        with self.assertRaises(KeyError):
            self.service.validate_source_url("https://example.com")

    @patch("requests.get")
    def test_validate_source_url_accepts_official_nfra_item_list_page(self, mock_get) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.apparent_encoding = "utf-8"
        mock_get.return_value.encoding = "ISO-8859-1"
        mock_get.return_value.text = "<html><head><title>监管动态</title></head><body>ItemList</body></html>"

        result = self.service.validate_source_url(
            "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411"
        )

        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["region"], "全国")

    def test_material_relevance_requires_more_than_single_body_mention(self) -> None:
        loosely_related = self.service.article_crawler._is_materially_relevant(
            title="银行保险机构许可证管理办法",
            summary="规范许可证管理。",
            body_text="本办法适用于商业银行、保险公司、金融租赁公司等机构。",
            keywords=["融资租赁", "金融租赁", "金融租赁公司"],
        )
        strongly_related = self.service.article_crawler._is_materially_relevant(
            title="关于加强融资租赁公司监管的通知",
            summary="融资租赁公司监管要求",
            body_text="融资租赁公司应当加强融资租赁业务真实性审查。",
            keywords=["融资租赁", "金融租赁", "金融租赁公司"],
        )

        self.assertFalse(loosely_related)
        self.assertTrue(strongly_related)

    def test_scope_ranking_prefers_direct_keyword_in_title_over_body_only_mentions(self) -> None:
        ranked = self.service.article_crawler._rank_articles_by_scope_relevance(
            [
                {
                    "title": "银行保险机构许可证管理办法",
                    "summary": "规范许可证管理。",
                    "body_text": "本办法适用于金融租赁公司、汽车金融公司等机构。",
                    "published_at": "2026-02-06",
                    "extractor": "direct_pdf",
                },
                {
                    "title": "关于加强融资租赁公司监管的通知",
                    "summary": "融资租赁公司监管要求",
                    "body_text": "融资租赁公司应当加强融资租赁业务真实性审查。",
                    "published_at": "2026-01-08",
                    "extractor": "direct_pdf",
                },
            ],
            ["融资租赁", "金融租赁", "金融租赁公司"],
        )

        self.assertEqual(ranked[0]["title"], "关于加强融资租赁公司监管的通知")

    @patch("app.services.article_crawler.ArticleCrawlerService._discover_official_articles_via_search")
    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    def test_nfra_workflow_does_not_use_search_engine_fallback(
        self,
        mock_fetch_penalty_articles,
        mock_discover_official_articles,
    ) -> None:
        mock_fetch_penalty_articles.return_value = []
        mock_discover_official_articles.return_value = [
            {
                "title": "搜索引擎结果",
                "summary": "",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/search.pdf",
            }
        ]

        with patch.object(
            self.service.article_crawler,
            "_fetch_nfra_policy_articles",
            return_value=[
                {
                    "source_id": "src-nfra",
                    "source_name": "国家金融监督管理总局",
                    "title": "金融租赁公司监管评级办法",
                    "published_at": "2025-01-23",
                    "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1196832.pdf",
                    "institution_name": "Not disclosed in source article",
                    "body_text": "金融租赁公司监管评级办法",
                    "matched_keywords": ["金融租赁", "金融租赁公司"],
                    "extractor": "direct_pdf",
                    "summary": "金融租赁公司监管评级办法",
                    "regulator_name": "国家金融监督管理总局",
                }
            ],
        ):
            payload = self.service.run_live_workflow(
                source_id="src-nfra",
                keywords=["融资租赁"],
                limit=3,
            )

        self.assertEqual(payload["article_count"], 1)
        mock_discover_official_articles.assert_not_called()

    def test_scope_ranking_penalizes_broad_foundational_documents(self) -> None:
        ranked = self.service.article_crawler._rank_articles_by_scope_relevance(
            [
                {
                    "title": "（2003 年 12 月 27 日...《中华人民共和国银行业监督管理法》）目 录",
                    "summary": "该法是规范银行业监督管理活动的基础性法律。",
                    "body_text": "金融租赁公司",
                    "published_at": "2019-12-29",
                    "extractor": "direct_pdf",
                },
                {
                    "title": "金融租赁公司融资租赁业务管理办法",
                    "summary": "规范金融租赁公司融资租赁业务经营行为。",
                    "body_text": "金融租赁公司融资租赁业务管理办法",
                    "published_at": "2025-12-04",
                    "extractor": "direct_pdf",
                },
            ],
            ["融资租赁", "金融租赁", "金融租赁公司"],
        )

        self.assertEqual(ranked[0]["title"], "金融租赁公司融资租赁业务管理办法")

    def test_article_url_gate_rejects_index_page_and_accepts_detail_page(self) -> None:
        self.assertFalse(
            self.service.article_crawler._looks_like_article_url(
                "https://example.gov.cn/index.html"
            )
        )
        self.assertTrue(
            self.service.article_crawler._looks_like_article_url(
                "https://example.gov.cn/art/2026/07/09/art_12345.html"
            )
        )

    def test_synced_event_contains_credibility_fields(self) -> None:
        result = self._sync_sources_in_fixture_window(
            fetch_html=self._seed_fetch,
            period="30d",
        )

        self.assertGreater(result["synced_count"], 0)
        event = next(event for event in self.store.load()["events"] if event["event_id"].startswith("sync-"))
        self.assertIn("source_link_verified", event)
        self.assertIn("article_opened", event)
        self.assertIn("original_subject_extracted", event)
        self.assertIn("llm_analysis_completed", event)
        self.assertIn("extraction_confidence", event)

    def test_sync_sources_writes_run_receipt(self) -> None:
        result = self.service.sync_sources(fetch_html=self._seed_fetch)

        self.assertIn("run_receipt_path", result)
        receipt_path = Path(result["run_receipt_path"])
        self.assertTrue(receipt_path.exists())
        self.assertEqual(receipt_path.suffix, ".json")

    @patch("requests.get")
    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    def test_nfra_sync_skips_out_of_window_policy_announcements(
        self,
        mock_fetch_penalty_articles,
        mock_get,
    ) -> None:
        mock_fetch_penalty_articles.return_value = []

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": {
                        "rows": [
                            {
                                "docId": 1236230,
                                "docTitle": "国家金融监督管理总局关于印发《金融租赁公司融资租赁业务管理办法》的通知",
                                "docSummary": "金融租赁公司融资租赁业务管理办法",
                                "publishDate": "2025-12-05 09:00:00",
                                "pdfFileUrl": "/chinese/OFFICE/PDF/1236230.pdf",
                            }
                        ]
                    }
                }

        mock_get.return_value = FakeResponse()

        result = self.service.sync_sources(source_ids=["src-nfra"], period="30d")

        self.assertEqual(result["synced_count"], 0)
        self.assertEqual(result["errors"][0]["source_id"], "src-nfra")
        self.assertIn("selected period", result["errors"][0]["error"])

    def test_snapshot_filters_placeholder_institutions_and_invalid_source_links(self) -> None:
        state = self.service._load_seed_state()
        state["events"] = [
            {
                "event_id": "fake-1",
                "title": "假事件",
                "regulator": "测试监管机构",
                "region": "测试",
                "category": "监管处罚",
                "institution_type": "融资租赁",
                "institution_name": "某融资租赁公司",
                "institution_name_original": "某融资租赁公司",
                "severity": "major",
                "published_at": "2026-07-09T09:00:00",
                "summary": "测试",
                "risk_hint": "测试",
                "english_brief": "test",
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": True,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": "src-pbc", "title": "x", "url": "https://www.pbc.gov.cn/detail/1.html", "published_at": "2026-07-09T09:00:00"}],
                "evidence": [],
            },
            {
                "event_id": "fake-2",
                "title": "假链接事件",
                "regulator": "测试监管机构",
                "region": "测试",
                "category": "监管处罚",
                "institution_type": "融资租赁",
                "institution_name": "真实机构有限公司",
                "institution_name_original": "真实机构有限公司",
                "severity": "major",
                "published_at": "2026-07-09T10:00:00",
                "summary": "测试",
                "risk_hint": "测试",
                "english_brief": "test",
                "review_status": "pending",
                "reviewer": None,
                "review_notes": "",
                "source_link_verified": False,
                "article_opened": True,
                "original_subject_extracted": True,
                "llm_analysis_completed": False,
                "extraction_confidence": "high",
                "sources": [{"source_id": "src-pbc", "title": "x", "url": "https://example.com/invalid", "published_at": "2026-07-09T10:00:00"}],
                "evidence": [],
            },
        ]
        self.store.save(state)

        snapshot = self.service.bootstrap()

        self.assertEqual(snapshot["events"], [])

    @patch("app.services.nfra_adapter.NFRAAdapter.fetch_penalty_articles")
    @patch("app.services.article_crawler.requests.get")
    def test_nfra_dynamic_policy_articles_prefer_official_deeper_pages(self, mock_get, mock_fetch_penalty_articles) -> None:
        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        def fake_get(url, headers=None, timeout=None, verify=None):
            if "SelectDocByItemIdAndChild?itemId=4215" in url:
                return FakeResponse(
                    {
                        "rptCode": 200,
                        "msg": "成功",
                        "data": {
                            "total": 1,
                            "rows": [
                                {
                                    "docId": 1236230,
                                    "docTitle": "国家金融监督管理总局关于印发《金融租赁公司融资租赁业务管理办法》的通知",
                                    "docSubtitle": "",
                                    "publishDate": "2025-12-04 18:00:00",
                                    "docSummary": None,
                                    "pdfFileUrl": "/chinese/OFFICE/PDF/1236230.pdf",
                                }
                            ],
                        },
                    }
                )
            if "SelectDocByItemIdAndChild?itemId=916" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": {"total": 0, "rows": []}})
            if "SelectDocByItemIdAndChild?itemId=4214" in url:
                return FakeResponse({"rptCode": 200, "msg": "成功", "data": {"total": 0, "rows": []}})
            return FakeResponse({"rptCode": 200, "msg": "成功", "data": {"total": 0, "rows": []}})

        mock_get.side_effect = fake_get

        with patch.object(
            self.service.article_crawler,
            "_analyze_direct_pdf",
            return_value={
                "source_id": "src-nfra",
                "source_name": "国家金融监督管理总局",
                "title": "金融租赁公司融资租赁业务管理办法",
                "published_at": "",
                "source_url": "https://www.nfra.gov.cn/chinese/OFFICE/PDF/1236230.pdf",
                "institution_name": "Not disclosed in source article",
                "body_text": "金融租赁公司融资租赁业务管理办法 金融租赁公司",
                "matched_keywords": ["融资租赁", "金融租赁", "金融租赁公司"],
                "extractor": "direct_pdf",
            },
        ), patch.object(self.service.nfra_adapter, "fetch_penalty_articles", return_value=[]):
            payload = self.service.run_live_workflow(
                source_id="src-nfra",
                keywords=["融资租赁"],
                limit=3,
            )

        self.assertEqual(payload["article_count"], 1)
        self.assertIn("融资租赁业务管理办法", payload["articles"][0]["title"])
