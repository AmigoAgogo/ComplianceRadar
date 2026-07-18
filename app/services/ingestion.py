from __future__ import annotations

import csv
import json
import re
import time
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from app.models import seed_state
from app.services.analytics import (
    build_charts,
    build_management_dashboard,
    build_summary,
    localize_category,
)
from app.services.article_crawler import ArticleCrawlerService
from app.services.event_quality import build_event_quality
from app.services.nfra_adapter import NFRAAdapter
from app.services.run_receipts import RunReceiptWriter
from app.services.source_diagnostics import SourceDiagnosticsService
from app.store import JsonStateStore, append_jsonl
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


class DemoIngestionService:
    MAX_RELEVANT_EVENTS = 10
    MAX_DAILY_ITEMS_PER_SOURCE = 3
    LEGACY_AGENT_CONFIG_NAME = "COF_China_Compliance_Review_Agent_v2.3_Architecture_Draft.md"
    CANONICAL_AGENT_CONFIG_ORDER = [
        "00_role_and_boundaries.md",
        "10_signal_intake.md",
        "20_control_taxonomy.md",
        "30_china_management_brief.md",
        "40_global_compliance_brief.md",
        "50_output_schema.json",
        "60_style_and_length.md",
        "70_escalation_triggers.md",
    ]

    def __init__(
        self,
        store: JsonStateStore,
        seeds_path: Path,
        sources_path: Path,
    ) -> None:
        self.store = store
        self.seeds_path = seeds_path
        self.sources_path = sources_path
        self.runtime_root = store.path.parent
        self.agent_config_root = self.runtime_root / "agent_configs"
        self.source_diagnostics = SourceDiagnosticsService()
        self.nfra_adapter = NFRAAdapter(timeout=6)
        self.article_crawler = ArticleCrawlerService(self.nfra_adapter, timeout=8)
        self.run_receipts = RunReceiptWriter(self.runtime_root)

    def bootstrap(self) -> dict:
        if self.store.exists():
            state = self._refresh_sources(self.store.load())
            state = self._migrate_events(state)
            state = self._reconcile_models(state)
            self._ensure_agent_config_defaults()
            self.store.save(state)
        else:
            state = self._migrate_events(self._load_seed_state())
            self._ensure_agent_config_defaults()
            state = self.store.save(state)
        return self._snapshot_from_state(state)

    def reset(self) -> dict:
        preserved_models = None
        preserved_events = None
        if self.store.exists():
            existing_state = self.store.load()
            preserved_models = deepcopy(existing_state.get("models"))
            preserved_events = deepcopy(existing_state.get("events", []))
        state = self._load_seed_state()
        if preserved_models:
            state["models"] = preserved_models
        if preserved_events:
            state["events"] = self._merge_events_by_id(preserved_events, state.get("events", []))
        state = self._migrate_events(state)
        state = self._reconcile_models(state)
        self._ensure_agent_config_defaults()
        state = self.store.save(state)
        return self._snapshot_from_state(state)

    def apply_review(
        self,
        event_id: str,
        reviewer: str,
        status: str,
        note: str,
    ) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        updated_event = None
        for event in state["events"]:
            if event["event_id"] == event_id:
                event["review_status"] = status
                event["reviewer"] = reviewer
                event["review_notes"] = note
                updated_event = deepcopy(event)
                break

        if updated_event is None:
            raise KeyError(f"Unknown event: {event_id}")

        self.store.save(state)
        append_jsonl(
            self.runtime_root / "user_reviews" / "review_decisions.jsonl",
            {
                "event_id": event_id,
                "reviewer": reviewer,
                "status": status,
                "note": note,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        return updated_event

    def delete_event(self, event_id: str, deleted_by: str = "local-user") -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        kept_events: list[dict] = []
        deleted_event = None
        for event in state.get("events", []):
            if event.get("event_id") == event_id:
                deleted_event = deepcopy(event)
                continue
            kept_events.append(event)

        if deleted_event is None:
            raise KeyError(f"Unknown event: {event_id}")

        state["events"] = kept_events
        self.store.save(state)
        append_jsonl(
            self.runtime_root / "intelligence" / "deleted_events.jsonl",
            {
                "event_id": event_id,
                "deleted_by": deleted_by,
                "deleted_at": datetime.now(UTC).isoformat(),
                "title": deleted_event.get("title", ""),
                "source_url": ((deleted_event.get("sources") or [{}])[0]).get("url", ""),
            },
        )
        return {"deleted": event_id}

    def _merge_events_by_id(self, primary_events: list[dict], secondary_events: list[dict]) -> list[dict]:
        merged: list[dict] = []
        seen: set[str] = set()
        for event in [*primary_events, *secondary_events]:
            event_id = event.get("event_id")
            if not event_id or event_id in seen:
                continue
            merged.append(deepcopy(event))
            seen.add(event_id)
        return merged

    def list_events(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        events = self.bootstrap()["events"]
        filtered = self._filter_events_by_period(events, date_from, date_to)
        return filtered[: self.MAX_RELEVANT_EVENTS]

    def list_sources(self) -> list[dict]:
        sources = self.bootstrap()["sources"]
        for source in sources:
            source.setdefault("health_status", self._derive_source_health(source))
            source.setdefault("last_sync_result", source.get("last_sync_result", "not-run"))
        return sources

    def diagnose_source(self, source_id: str) -> dict:
        snapshot = self.bootstrap()
        source = next((item for item in snapshot["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        return self.source_diagnostics.diagnose(source)

    def discover_source(self, query: str) -> dict:
        normalized = query.strip()
        if not normalized:
            raise KeyError("Source query is required")

        snapshot = self.bootstrap()
        for source in snapshot["sources"]:
            if normalized == source["name"] or normalized == source["url"]:
                return deepcopy(source)
            if normalized in source["name"] or normalized in source["url"]:
                return deepcopy(source)

        official_registry = self._official_source_registry()
        if normalized in official_registry:
            return deepcopy(official_registry[normalized])

        if normalized.startswith("http"):
            metadata = self.validate_source_url(normalized)
            return {
                "source_id": self._slugify_source_id(normalized),
                "name": metadata["title"],
                "kind": "official-site",
                "url": normalized,
                "sync_url": normalized,
                "parser": "generic_portal",
                "region": metadata["region"],
                "status": "active",
                "last_checked": "",
                "note": f"Validated live source ({metadata['status_code']})",
            }

        raise KeyError(
            "Source query must be a reachable official URL or one of the supported regulator names."
        )

    def get_models(self) -> dict:
        return self.bootstrap()["models"]

    def get_agent_context(self) -> dict:
        self._ensure_agent_config_defaults()
        self.agent_config_root.mkdir(parents=True, exist_ok=True)
        supported_suffixes = {".json", ".txt", ".md", ".yaml", ".yml"}
        source_files = [
            path
            for path in sorted(self.agent_config_root.iterdir())
            if path.is_file() and path.suffix.lower() in supported_suffixes
        ]
        files: list[dict] = []
        loaded_sections: dict[str, str] = {}
        combined_sections: list[str] = []
        canonical_present = any(path.name in self.CANONICAL_AGENT_CONFIG_ORDER for path in source_files)

        ordered_paths: list[Path] = []
        by_name = {path.name: path for path in source_files}
        for name in self.CANONICAL_AGENT_CONFIG_ORDER:
            path = by_name.pop(name, None)
            if path is not None:
                ordered_paths.append(path)

        extra_paths = sorted(by_name.values(), key=lambda path: path.name.lower())
        if canonical_present:
            extra_paths = [path for path in extra_paths if path.name != self.LEGACY_AGENT_CONFIG_NAME]
        ordered_paths.extend(extra_paths)

        for path in ordered_paths:
            content = path.read_text(encoding="utf-8").strip()
            section_name = self._agent_config_section_name(path.name)
            files.append(
                {
                    "name": path.name,
                    "section": section_name,
                    "path": str(path),
                    "size": path.stat().st_size,
                    "priority": self._agent_config_priority(path.name),
                }
            )
            loaded_sections[section_name] = content
            if content:
                label = self._agent_config_section_label(section_name)
                combined_sections.append(f"[{label}]\n{content}")
        combined_text = "\n\n".join(combined_sections).strip()
        agent_name = "COF China Compliance Review Agent" if ordered_paths else ""
        return {
            "folder": str(self.agent_config_root),
            "agent_name": agent_name,
            "file_count": len(source_files),
            "files": files,
            "sections": loaded_sections,
            "briefs": {
                "china_management": loaded_sections.get("china_management_brief", ""),
                "global_compliance": loaded_sections.get("global_compliance_brief", ""),
            },
            "combined_text": combined_text,
        }

    def validate_source_url(self, url: str) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise KeyError("Source URL must be a valid http or https address.")

        import requests

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        html = response.text
        title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        title = self._strip_tags(unescape(title_match.group(1))).strip() if title_match else parsed.netloc
        page_signal = " ".join([title, parsed.netloc, parsed.path, html[:2000]])
        official_host_markers = [
            "nfra.gov.cn",
            "pbc.gov.cn",
            "jrj.beijing.gov.cn",
            "jrj.sh.gov.cn",
        ]
        regulatory_markers = [
            "金融",
            "监管",
            "人民银行",
            "国家金融监督管理总局",
            "地方金融",
            "北京",
            "上海",
            "/DocInfo/",
            "ItemList",
        ]
        if not (
            any(marker in parsed.netloc for marker in official_host_markers)
            or any(marker in page_signal for marker in regulatory_markers)
        ):
            raise KeyError("Source URL is reachable but does not look like a supported regulatory source.")
        return {
            "url": url,
            "title": title,
            "status_code": response.status_code,
            "region": self._infer_region_from_text(title),
        }

    def fetch_latest_source_signal(self, source_id: str) -> dict:
        snapshot = self.bootstrap()
        source = next((item for item in snapshot["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")
        sync_url = source.get("sync_url") or source.get("url")
        if not sync_url:
            raise KeyError(f"Source has no URL: {source_id}")
        html = self._default_fetch_html(sync_url, timeout=20)
        articles = self._extract_source_articles(source, html, sync_url)
        if not articles:
            raise ValueError(f"No article-level records parsed from {source['name']}")
        article = articles[0]
        detail_html = self._load_article_html(article, self._default_fetch_html)
        event = self._event_from_article(source, article, detail_html)
        event["fetched_live"] = True
        return {
            "source_id": source_id,
            "source_name": source["name"],
            "event": event,
        }

    def run_live_workflow(
        self,
        source_id: str,
        keywords: list[str],
        limit: int = 5,
    ) -> dict:
        snapshot = self.bootstrap()
        source = next((item for item in snapshot["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        articles = self.article_crawler.fetch_relevant_articles(source, keywords=keywords, limit=limit)
        analyzed_articles: list[dict] = []
        llm_model = None
        llm_count = 0

        for article in articles:
            analysis_event = {
                "title": article.get("title", ""),
                "regulator": article.get("regulator_name") or source["name"],
                "region": source.get("region", "全国"),
                "category": "监管处罚" if article.get("penalty_text") else "监管动态",
                "institution_name": article.get("institution_name", "Not disclosed in source article"),
                "institution_name_original": article.get("institution_name", "Not disclosed in source article"),
                "summary": article.get("summary") or article.get("penalty_text") or article.get("body_text", "")[:800],
                "risk_hint": "Pending LLM analysis from real source content.",
                "english_brief": f"Live article from {source['name']}",
            }
            enrichment = self._enrich_event_if_possible(analysis_event, self.store.load() if self.store.exists() else self._load_seed_state())
            if enrichment["used_llm"]:
                llm_model = enrichment["model"]
                llm_count += 1
            enriched_event = enrichment["event"]
            analyzed_articles.append(
                {
                    "title": article.get("title", ""),
                    "published_at": article.get("published_at", ""),
                    "source_url": article.get("source_url", ""),
                    "institution_name": article.get("institution_name", ""),
                    "matched_keywords": article.get("matched_keywords", []),
                    "extractor": article.get("extractor", ""),
                    "summary": enriched_event.get("summary", analysis_event["summary"]),
                    "risk_hint": enriched_event.get("risk_hint", analysis_event["risk_hint"]),
                    "english_brief": enriched_event.get("english_brief", analysis_event["english_brief"]),
                }
            )

        return {
            "source_id": source_id,
            "source_name": source["name"],
            "keywords": keywords,
            "article_count": len(analyzed_articles),
            "llm_enriched_count": llm_count,
            "llm_model": llm_model,
            "articles": analyzed_articles,
        }

    def run_url_workflow(
        self,
        url: str,
        keywords: list[str],
        limit: int = 5,
    ) -> dict:
        metadata = self.validate_source_url(url)
        parser = "generic_portal"
        if "nfra.gov.cn" in urlparse(url).netloc:
            parser = "nfra_docinfo"
        source = {
            "source_id": self._slugify_source_id(url),
            "name": metadata["title"],
            "kind": "official-site",
            "url": url,
            "sync_url": url,
            "parser": parser,
            "region": metadata["region"],
            "status": "adhoc",
            "last_checked": "",
            "note": f"Ad hoc workflow source validated from {url}",
        }

        articles = self.article_crawler.fetch_relevant_articles(source, keywords=keywords, limit=limit)
        analyzed_articles: list[dict] = []
        llm_model = None
        llm_count = 0

        for article in articles:
            analysis_event = {
                "title": article.get("title", ""),
                "regulator": article.get("regulator_name") or source["name"],
                "region": source.get("region", "全国"),
                "category": "监管处罚" if article.get("penalty_text") else "监管动态",
                "institution_name": article.get("institution_name", "Not disclosed in source article"),
                "institution_name_original": article.get("institution_name", "Not disclosed in source article"),
                "summary": article.get("summary") or article.get("penalty_text") or article.get("body_text", "")[:800],
                "risk_hint": "Pending LLM analysis from real source content.",
                "english_brief": f"Live article from {source['name']}",
            }
            enrichment = self._enrich_event_if_possible(
                analysis_event,
                self.store.load() if self.store.exists() else self._load_seed_state(),
            )
            if enrichment["used_llm"]:
                llm_model = enrichment["model"]
                llm_count += 1
            enriched_event = enrichment["event"]
            analyzed_articles.append(
                {
                    "title": article.get("title", ""),
                    "published_at": article.get("published_at", ""),
                    "source_url": article.get("source_url", ""),
                    "institution_name": article.get("institution_name", ""),
                    "matched_keywords": article.get("matched_keywords", []),
                    "extractor": article.get("extractor", ""),
                    "summary": enriched_event.get("summary", analysis_event["summary"]),
                    "risk_hint": enriched_event.get("risk_hint", analysis_event["risk_hint"]),
                    "english_brief": enriched_event.get("english_brief", analysis_event["english_brief"]),
                }
            )

        return {
            "source_id": source["source_id"],
            "source_name": source["name"],
            "source_url": url,
            "keywords": keywords,
            "article_count": len(analyzed_articles),
            "llm_enriched_count": llm_count,
            "llm_model": llm_model,
            "articles": analyzed_articles,
        }

    def run_direct_article_workflow(
        self,
        source_id: str,
        article_url: str,
        keywords: list[str],
    ) -> dict:
        snapshot = self.bootstrap()
        source = next((item for item in snapshot["sources"] if item["source_id"] == source_id), None)
        if source is None:
            raise KeyError(f"Unknown source: {source_id}")

        article = self.article_crawler.analyze_direct_article(source, article_url, keywords)
        analysis_event = {
            "title": article.get("title", ""),
            "regulator": source["name"],
            "region": source.get("region", "全国"),
            "category": "监管动态",
            "institution_name": article.get("institution_name", "Not disclosed in source article"),
            "institution_name_original": article.get("institution_name", "Not disclosed in source article"),
            "summary": article.get("body_text", "")[:800],
            "risk_hint": "Pending LLM analysis from real source content.",
            "english_brief": f"Live article from {source['name']}",
        }
        enrichment = self._enrich_event_if_possible(
            analysis_event,
            self.store.load() if self.store.exists() else self._load_seed_state(),
        )
        enriched_event = enrichment["event"]
        return {
            "source_id": source_id,
            "source_name": source["name"],
            "article_count": 1,
            "llm_enriched_count": 1 if enrichment["used_llm"] else 0,
            "llm_model": enrichment["model"],
            "articles": [
                {
                    "title": article.get("title", ""),
                    "published_at": article.get("published_at", ""),
                    "source_url": article_url,
                    "institution_name": article.get("institution_name", ""),
                    "matched_keywords": article.get("matched_keywords", []),
                    "extractor": article.get("extractor", ""),
                    "summary": enriched_event.get("summary", analysis_event["summary"]),
                    "risk_hint": enriched_event.get("risk_hint", analysis_event["risk_hint"]),
                    "english_brief": enriched_event.get("english_brief", analysis_event["english_brief"]),
                }
            ],
        }

    def _ensure_agent_config_defaults(self) -> None:
        self.agent_config_root.mkdir(parents=True, exist_ok=True)
        default_dir = self.seeds_path.parents[1] / "agent_configs"
        if not default_dir.exists():
            return
        for default_file in default_dir.iterdir():
            if not default_file.is_file():
                continue
            target = self.agent_config_root / default_file.name
            if target.exists():
                continue
            target.write_text(default_file.read_text(encoding="utf-8"), encoding="utf-8")

    def _agent_config_section_name(self, filename: str) -> str:
        stem = Path(filename).stem
        if stem[:2].isdigit() and len(stem) > 3 and stem[2] == "_":
            return stem[3:]
        if filename == self.LEGACY_AGENT_CONFIG_NAME:
            return "legacy_baseline"
        return stem

    def _agent_config_section_label(self, section_name: str) -> str:
        label_map = {
            "role_and_boundaries": "Role And Boundaries",
            "signal_intake": "Signal Intake",
            "control_taxonomy": "Control Taxonomy",
            "china_management_brief": "China Management Brief",
            "global_compliance_brief": "Global Compliance Brief",
            "output_schema": "Output Schema",
            "style_and_length": "Style And Length",
            "escalation_triggers": "Escalation Triggers",
            "legacy_baseline": "Legacy Baseline",
        }
        return label_map.get(section_name, section_name.replace("_", " ").title())

    def _agent_config_priority(self, filename: str) -> int:
        if filename in self.CANONICAL_AGENT_CONFIG_ORDER:
            return self.CANONICAL_AGENT_CONFIG_ORDER.index(filename)
        if filename == self.LEGACY_AGENT_CONFIG_NAME:
            return 100
        return 50

    def _reconcile_models(self, state: dict) -> dict:
        seeded_models = self._load_seed_state()["models"]
        seed_profiles = {profile["name"]: deepcopy(profile) for profile in seeded_models["profiles"]}
        existing_profiles = state.get("models", {}).get("profiles", []) or []
        reconciled_profiles: list[dict] = []

        for profile in existing_profiles:
            if profile.get("name") in seed_profiles:
                merged = seed_profiles.pop(profile["name"])
                merged.update(profile)
                reconciled_profiles.append(merged)
            elif self._is_user_cloud_model(profile):
                reconciled_profiles.append(deepcopy(profile))

        for remaining in seed_profiles.values():
            reconciled_profiles.append(remaining)

        state["models"]["profiles"] = reconciled_profiles
        valid_names = {profile["name"] for profile in reconciled_profiles}
        if state["models"].get("current_model") not in valid_names:
            state["models"]["current_model"] = seeded_models.get("current_model", "Minimax China")
        return state

    def set_current_model(self, name: str) -> dict:
        state = self._refresh_sources(
            self.store.load() if self.store.exists() else self._load_seed_state()
        )
        profile_names = {profile["name"] for profile in state["models"]["profiles"]}
        if name not in profile_names:
            raise KeyError(f"Unknown model: {name}")
        state["models"]["current_model"] = name
        self.store.save(state)
        return deepcopy(state["models"])

    def add_model(self, profile: dict) -> dict:
        state = self._refresh_sources(
            self.store.load() if self.store.exists() else self._load_seed_state()
        )
        names = {item["name"] for item in state["models"]["profiles"]}
        if profile["name"] in names:
            raise KeyError(f"Model already exists: {profile['name']}")
        profile.setdefault("enabled", True)
        profile.setdefault("timeout", 30)
        state["models"]["profiles"].append(deepcopy(profile))
        self.store.save(state)
        return deepcopy(profile)

    def update_model(self, name: str, updates: dict) -> dict:
        state = self._refresh_sources(
            self.store.load() if self.store.exists() else self._load_seed_state()
        )
        for profile in state["models"]["profiles"]:
            if profile["name"] == name:
                profile.update(updates)
                self.store.save(state)
                return deepcopy(profile)
        raise KeyError(f"Unknown model: {name}")

    def delete_model(self, name: str) -> dict:
        state = self._refresh_sources(
            self.store.load() if self.store.exists() else self._load_seed_state()
        )
        state["models"]["profiles"] = [
            item for item in state["models"]["profiles"] if item["name"] != name
        ]
        if state["models"]["current_model"] == name and state["models"]["profiles"]:
            state["models"]["current_model"] = state["models"]["profiles"][0]["name"]
        self.store.save(state)
        return {"deleted": name}

    def add_source(self, source: dict) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        ids = {item["source_id"] for item in state["sources"]}
        if source["source_id"] in ids:
            raise KeyError(f"Source already exists: {source['source_id']}")
        if source.get("url"):
            self.validate_source_url(source["url"])
        state["sources"].append(deepcopy(source))
        self.store.save(state)
        return deepcopy(source)

    def update_source(self, source_id: str, updates: dict) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        for source in state["sources"]:
            if source["source_id"] == source_id:
                source.update(updates)
                self.store.save(state)
                return deepcopy(source)
        raise KeyError(f"Unknown source: {source_id}")

    def update_source_status(self, source_id: str, status: str) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        for source in state["sources"]:
            if source["source_id"] == source_id:
                source["status"] = status
                self.store.save(state)
                return deepcopy(source)
        raise KeyError(f"Unknown source: {source_id}")

    def delete_source(self, source_id: str) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        state["sources"] = [
            item for item in state["sources"] if item["source_id"] != source_id
        ]
        self.store.save(state)
        return {"deleted": source_id}

    def preview_source(self, source_id: str, fetch_html=None) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        fetch_html = fetch_html or self._default_fetch_html
        for source in state["sources"]:
            if source["source_id"] == source_id:
                sync_url = source.get("sync_url")
                if not sync_url:
                    raise KeyError(f"Source has no sync URL: {source_id}")
                html = fetch_html(sync_url, timeout=15)
                base_reference = sync_url
                articles = self._extract_source_articles(source, html, base_reference)
                if not articles:
                    raise ValueError(f"No article-level records parsed from {source['name']}")
                article = articles[0]
                detail_html = self._load_article_html(article, fetch_html)
                event = self._event_from_article(source, article, detail_html)
                preview_event = deepcopy(event)
                preview_event["evidence"] = []
                return {"source_id": source_id, "event": preview_event}
        raise KeyError(f"Unknown source: {source_id}")

    def sync_sources(
        self,
        source_ids: list[str] | None = None,
        period: str | None = None,
        fetch_html=None,
    ) -> dict:
        state = self.store.load() if self.store.exists() else self._load_seed_state()
        fetch_html = fetch_html or self._default_fetch_html
        synced_count = 0
        llm_enriched_count = 0
        llm_model = None
        errors: list[dict] = []
        processed_sources: list[str] = []
        source_results: list[dict] = []
        rejected_articles: list[dict] = []
        normalized_period = self._normalize_sync_period(period)
        article_limit = self._period_day_limit(normalized_period) * self.MAX_DAILY_ITEMS_PER_SOURCE
        started_at = datetime.now(UTC).isoformat()

        for source in state["sources"]:
            if source_ids and source["source_id"] not in source_ids:
                continue
            sync_url = source.get("sync_url")
            parser = source.get("parser")
            source_start_count = synced_count
            source_result = {
                "source_id": source["source_id"],
                "source_name": source.get("name", source["source_id"]),
                "status": "started",
                "method": "primary",
                "events_added": 0,
                "checked_url": sync_url or source.get("url", ""),
                "elapsed_seconds": 0,
                "message": "",
            }
            if not sync_url and not source.get("url"):
                processed_sources.append(source["source_id"])
                source["last_sync_result"] = "unsupported"
                source_result.update(
                    {
                        "status": "unsupported",
                        "method": "none",
                        "message": "source is not configured for sync",
                    }
                )
                source_results.append(source_result)
                errors.append(
                    {
                        "source_id": source["source_id"],
                        "error": "source is not configured for sync",
                    }
                )
                continue
            processed_sources.append(source["source_id"])
            source_started_at = time.perf_counter()
            primary_list_opened = False
            try:
                if source["source_id"] == "src-nfra":
                    synced_count, llm_enriched_count, llm_model, latest_published_at = self._ingest_nfra_penalty_articles(
                        state=state,
                        source=source,
                        synced_count=synced_count,
                        llm_enriched_count=llm_enriched_count,
                        llm_model=llm_model,
                        period=normalized_period,
                        article_limit=article_limit,
                    )
                else:
                    html = fetch_html(sync_url, timeout=15)
                    primary_list_opened = True
                    synced_count, llm_enriched_count, llm_model, latest_published_at = self._ingest_source_articles(
                        state=state,
                        source=source,
                        list_html=html,
                        base_reference=sync_url,
                        fetch_html=fetch_html,
                        synced_count=synced_count,
                        llm_enriched_count=llm_enriched_count,
                        llm_model=llm_model,
                        period=normalized_period,
                        article_limit=article_limit,
                        rejected_articles=rejected_articles,
                    )
                source["last_checked"] = latest_published_at
                source["status"] = "active"
                source["last_sync_result"] = "ok"
                source["health_status"] = self._derive_source_health(source)
                source_result.update(
                    {
                        "status": "ok",
                        "method": "primary",
                        "events_added": synced_count - source_start_count,
                        "elapsed_seconds": round(time.perf_counter() - source_started_at, 2),
                        "message": "primary source crawler completed",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                fallback_used = False
                fallback_error: Exception | None = None
                if source.get("url") and source.get("source_id") != "src-nfra" and primary_list_opened:
                    try:
                        synced_count, llm_enriched_count, llm_model, latest_published_at = self._ingest_source_with_article_crawler(
                            state=state,
                            source=source,
                            synced_count=synced_count,
                            llm_enriched_count=llm_enriched_count,
                            llm_model=llm_model,
                            period=normalized_period,
                            article_limit=article_limit,
                        )
                        source["last_checked"] = latest_published_at
                        source["status"] = "active"
                        source["last_sync_result"] = "ok_fallback"
                        source["health_status"] = self._derive_source_health(source)
                        source_result.update(
                            {
                                "status": "ok",
                                "method": "article_crawler_fallback",
                                "events_added": synced_count - source_start_count,
                                "elapsed_seconds": round(time.perf_counter() - source_started_at, 2),
                                "message": f"primary failed: {exc}",
                            }
                        )
                        fallback_used = True
                    except Exception as fallback_exc:  # noqa: BLE001
                        fallback_error = fallback_exc
                if not fallback_used:
                    final_error = fallback_error or exc
                    source["last_sync_result"] = f"error: {final_error}"
                    source["health_status"] = "error"
                    source_result.update(
                        {
                            "status": "error",
                            "method": "primary+fallback" if fallback_error else "primary",
                            "events_added": synced_count - source_start_count,
                            "elapsed_seconds": round(time.perf_counter() - source_started_at, 2),
                            "message": str(final_error),
                        }
                    )
                    errors.append({"source_id": source["source_id"], "error": str(final_error)})
            source_results.append(source_result)

        self.store.save(state)
        run_id = f"sync-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        receipt_path = self.run_receipts.write(
            {
                "run_id": run_id,
                "period": normalized_period,
                "sources_checked": processed_sources,
                "accepted_events": synced_count,
                "source_results": source_results,
                "rejected_articles": rejected_articles,
                "llm_model_used": llm_model,
                "llm_enriched_count": llm_enriched_count,
                "errors": errors,
                "started_at": started_at,
                "ended_at": datetime.now(UTC).isoformat(),
            }
        )
        return {
            "synced_count": synced_count,
            "llm_enriched_count": llm_enriched_count,
            "llm_model": llm_model,
            "event_count": len(state["events"]),
            "errors": errors,
            "processed_sources": processed_sources,
            "source_results": source_results,
            "period": normalized_period,
            "per_source_daily_limit": self.MAX_DAILY_ITEMS_PER_SOURCE,
            "run_receipt_path": str(receipt_path),
        }

    def _ingest_source_with_article_crawler(
        self,
        state: dict,
        source: dict,
        synced_count: int,
        llm_enriched_count: int,
        llm_model: str | None,
        period: str,
        article_limit: int,
    ) -> tuple[int, int, str | None, str]:
        keywords = ["融资租赁", "金融租赁", "商业保理", "保理公司"]
        fallback_limit = min(article_limit, self.MAX_RELEVANT_EVENTS)
        articles = self.article_crawler.fetch_relevant_articles(source, keywords=keywords, limit=fallback_limit)
        articles = self._filter_articles_for_period(articles, period)[:article_limit]
        if not articles:
            raise ValueError(f"No article-level records parsed from {source['name']}")

        latest_published_at = source.get("last_checked", "")
        for article in articles:
            event = self._event_from_crawled_article(source, article)
            enrichment = self._enrich_event_if_possible(event, state)
            event = enrichment["event"]
            if enrichment["used_llm"]:
                llm_enriched_count += 1
                llm_model = enrichment["model"]
            if not self._event_exists(state["events"], event["title"], event["published_at"]):
                state["events"].insert(0, event)
                synced_count += 1
            if event["published_at"] > latest_published_at:
                latest_published_at = event["published_at"]

        return synced_count, llm_enriched_count, llm_model, latest_published_at

    def export_reports(self, module: str = "dashboard", output_dir: Path | None = None) -> dict:
        snapshot = self.bootstrap()
        output_dir = output_dir or (self.runtime_root / "exports")
        output_dir.mkdir(parents=True, exist_ok=True)
        normalized_module = self._normalize_export_module(module)
        module_payload = self._module_export_payload(snapshot, normalized_module)

        csv_path = output_dir / f"{normalized_module}_report.csv"
        html_path = output_dir / f"{normalized_module}_report.html"
        pdf_path = output_dir / f"{normalized_module}_report.pdf"

        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            if normalized_module == "sources":
                fieldnames = [
                    "source_id",
                    "name",
                    "region",
                    "url",
                    "status",
                    "last_checked",
                    "last_sync_result",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for source in module_payload["sources"]:
                    writer.writerow({key: source.get(key, "") for key in fieldnames})
            else:
                fieldnames = [
                    "event_id",
                    "published_at",
                    "title",
                    "regulator",
                    "region",
                    "category",
                    "institution_name",
                    "severity",
                    "review_status",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for event in module_payload["events"]:
                    writer.writerow({key: event.get(key, "") for key in fieldnames})

        html_content = self._render_html_report(module_payload)
        html_path.write_text(html_content, encoding="utf-8")
        self._render_pdf_report(module_payload, pdf_path)

        return {
            "csv": str(csv_path),
            "html": str(html_path),
            "pdf": str(pdf_path),
            "module": normalized_module,
        }

    def build_risk_outlook(self, events: list[dict]) -> dict:
        major_events = [event for event in events if event.get("severity") == "major"]
        sorted_events = sorted(events, key=lambda item: item["published_at"], reverse=True)
        latest_events = sorted_events[:4]
        categories: dict[str, int] = {}
        for event in events:
            categories[event["category"]] = categories.get(event["category"], 0) + 1
        top_categories = sorted(
            categories.items(),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        latest_window = "No events available"
        if sorted_events:
            latest_date = sorted_events[0]["published_at"][:10]
            oldest_date = sorted_events[min(len(sorted_events), 9) - 1]["published_at"][:10]
            latest_window = f"{oldest_date} to {latest_date}"
        return {
            "trend_summary": (
                f"Recent signals show {len(major_events)} major enforcement events across "
                f"{len(categories)} category themes, with the latest focus on "
                f"{', '.join(localize_category(category) for category, _ in top_categories) or 'general compliance'}."
            ),
            "major_signal_count": len(major_events),
            "top_theme": localize_category(top_categories[0][0]) if top_categories else "general compliance",
            "latest_window": latest_window,
            "management_message": (
                "The outlook should help Siemens Financial Leasing move from event collection "
                "to management interpretation: what changed, why it matters now, and where controls "
                "or portfolio exposure may need immediate attention."
            ),
            "priority_risks": [
                {
                    "title": event["title"],
                    "category": localize_category(event["category"]),
                    "institution": event.get("institution_name_original") or event.get("institution_name"),
                    "risk_hint": event["risk_hint"],
                    "published_at": event["published_at"],
                }
                for event in latest_events
            ],
            "management_actions": [
                "Check whether similar themes appear in Siemens Financial Leasing controls and reporting routines.",
                "Use the latest major cases to brief management on enforcement direction and immediate attention points.",
                "Track whether the same regulator themes repeat across multiple regions or entity types.",
            ],
        }

    def _load_seed_state(self) -> dict:
        seeds_payload = json.loads(self.seeds_path.read_text(encoding="utf-8"))
        sources_payload = json.loads(self.sources_path.read_text(encoding="utf-8"))
        return seed_state(
            events=seeds_payload["events"],
            sources=sources_payload["sources"],
            models=seeds_payload["models"],
        )

    def _snapshot_from_state(self, state: dict) -> dict:
        events = self._select_relevant_events(state)
        sources = deepcopy(state["sources"])
        for source in sources:
            source.setdefault("health_status", self._derive_source_health(source))
            source.setdefault("last_sync_result", source.get("last_sync_result", "not-run"))
        models = deepcopy(state["models"])
        trend_window = self._compute_trend_window(events)
        return {
            "summary": build_summary(events, sources),
            "charts": build_charts(events),
            "management_dashboard": build_management_dashboard(events, trend_window=trend_window),
            "events": events,
            "risk_outlook": self.build_risk_outlook(events),
            "sources": sources,
            "models": models,
            "agent_context": self.get_agent_context(),
            "trend_window": trend_window,
        }

    def _select_relevant_events(self, state: dict) -> list[dict]:
        configured_source_ids = {
            source["source_id"]
            for source in state.get("sources", [])
            if source.get("status", "active") == "active"
        }
        relevant_events = [
            deepcopy(event)
            for event in state.get("events", [])
            if self._event_matches_configured_sources(event, configured_source_ids)
            and self._event_matches_business_scope(event)
            and self._event_is_displayable(event)
        ]
        relevant_events.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        return relevant_events[: self.MAX_RELEVANT_EVENTS]

    def _event_matches_configured_sources(self, event: dict, configured_source_ids: set[str]) -> bool:
        sources = event.get("sources") or []
        return any(item.get("source_id") in configured_source_ids for item in sources)

    def _event_matches_business_scope(self, event: dict) -> bool:
        text = " ".join(
            [
                event.get("title", ""),
                event.get("summary", ""),
                event.get("institution_name_original", ""),
                event.get("institution_name", ""),
            ]
        )
        if event.get("title") in {"首页", "Home"}:
            return False
        return self._business_scope_matches_text(text)

    def _event_is_displayable(self, event: dict) -> bool:
        institution_name = (
            event.get("institution_name_original")
            or event.get("institution_name")
            or ""
        )
        if self._is_placeholder_institution_name(institution_name):
            return False
        if not event.get("source_link_verified"):
            return False
        if not event.get("article_opened"):
            return False
        if not event.get("original_subject_extracted"):
            return False
        return self._find_verified_source_url(event) is not None

    def _find_verified_source_url(self, event: dict) -> str | None:
        for source in event.get("sources") or []:
            url = source.get("url", "")
            if self._is_verified_source_url(url):
                return url
        return None

    def _is_verified_source_url(self, url: str) -> bool:
        normalized = (url or "").strip().lower()
        if not normalized:
            return False
        if not normalized.startswith(("http://", "https://")):
            return False
        blocked_patterns = [
            "example.com",
            "/index.html",
            "/index/index.html",
            "javascript:",
            "{{",
            "}}",
        ]
        if any(pattern in normalized for pattern in blocked_patterns):
            return False
        return self._looks_like_article_url(normalized)

    def _is_placeholder_institution_name(self, name: str) -> bool:
        normalized = (name or "").strip()
        if not normalized:
            return True
        blocked_markers = ["某", "示例", "样本", "测试", "待识别", "Not disclosed"]
        return any(marker in normalized for marker in blocked_markers)

    def _business_scope_matches_text(self, text: str) -> bool:
        keywords = [
            "融资租赁",
            "融资租赁公司",
            "金融租赁",
            "商业保理",
            "保理公司",
        ]
        return any(keyword in text for keyword in keywords)

    def _refresh_sources(self, state: dict) -> dict:
        sources_payload = json.loads(self.sources_path.read_text(encoding="utf-8"))
        latest_sources = {source["source_id"]: source for source in sources_payload["sources"]}
        refreshed_sources: list[dict] = []

        for current in state.get("sources", []):
            latest = deepcopy(latest_sources.pop(current["source_id"], {}))
            merged = latest | current
            refreshed_sources.append(merged)

        for remaining in latest_sources.values():
            refreshed_sources.append(deepcopy(remaining))

        state["sources"] = refreshed_sources
        return state

    def _migrate_events(self, state: dict) -> dict:
        migrated_events: list[dict] = []
        for event in state.get("events", []):
            migrated = deepcopy(event)
            original_name = (
                migrated.get("institution_name_original")
                or migrated.get("institution_name", "")
            ).strip()
            original_name = self._normalize_institution_subject(original_name)
            migrated["institution_name"] = original_name
            migrated["institution_name_original"] = original_name
            migrated_events.append(migrated)
        state["events"] = migrated_events
        return state

    def _filter_events_by_period(
        self,
        events: list[dict],
        date_from: str | None,
        date_to: str | None,
    ) -> list[dict]:
        from_boundary = self._parse_boundary(date_from)
        to_boundary = self._parse_boundary(date_to)
        if from_boundary is None and to_boundary is None:
            return events

        filtered: list[dict] = []
        for event in events:
            event_date = date.fromisoformat(event["published_at"][:10])
            if from_boundary and event_date < from_boundary:
                continue
            if to_boundary and event_date > to_boundary:
                continue
            filtered.append(event)
        return filtered

    def _parse_boundary(self, raw: str | None) -> date | None:
        if not raw:
            return None
        return date.fromisoformat(raw)

    def _normalize_sync_period(self, period: str | None) -> str:
        normalized = (period or "7d").strip().lower()
        return normalized if normalized in {"today", "7d", "30d"} else "7d"

    def _period_day_limit(self, period: str) -> int:
        if period == "today":
            return 1
        if period == "30d":
            return 30
        return 7

    def _period_start_date(self, period: str) -> date:
        today = date.today()
        if period == "today":
            return today
        if period == "30d":
            return today - timedelta(days=29)
        return today - timedelta(days=6)

    def _safe_article_date(self, raw: str) -> date | None:
        token = (raw or "")[:10]
        try:
            return date.fromisoformat(token)
        except ValueError:
            return None

    def _filter_articles_for_period(self, articles: list[dict], period: str) -> list[dict]:
        start_date = self._period_start_date(period)
        day_counts: dict[str, int] = {}
        filtered: list[dict] = []

        for article in sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True):
            published_date = self._safe_article_date(article.get("published_at", ""))
            if published_date is None or published_date < start_date:
                continue
            bucket = published_date.isoformat()
            count = day_counts.get(bucket, 0)
            if count >= self.MAX_DAILY_ITEMS_PER_SOURCE:
                continue
            day_counts[bucket] = count + 1
            filtered.append(article)

        return filtered

    def _compute_trend_window(self, events: list[dict]) -> dict:
        if not events:
            return {"label": "No source-backed trend window available yet", "from": "", "to": ""}
        published_dates = sorted(event["published_at"][:10] for event in events if event.get("published_at"))
        return {
            "label": f"Trend window based on sourced events: {published_dates[0]} to {published_dates[-1]}",
            "from": published_dates[0],
            "to": published_dates[-1],
        }

    def _normalize_export_module(self, module: str | None) -> str:
        normalized = (module or "dashboard").strip().lower()
        return normalized if normalized in {"dashboard", "events", "review", "sources", "models"} else "dashboard"

    def _module_export_payload(self, snapshot: dict, module: str) -> dict:
        payload = {
            "module": module,
            "summary": snapshot.get("summary", {}),
            "management_dashboard": snapshot.get("management_dashboard", {}),
            "risk_outlook": snapshot.get("risk_outlook", {}),
            "trend_window": snapshot.get("trend_window", {}),
            "events": [],
            "sources": [],
            "models": {},
        }
        if module == "sources":
            payload["sources"] = snapshot.get("sources", [])
        elif module == "models":
            payload["models"] = snapshot.get("models", {})
        elif module == "review":
            payload["events"] = snapshot.get("risk_outlook", {}).get("priority_risks", [])
        else:
            payload["events"] = snapshot.get("events", [])
        return payload

    def _is_user_cloud_model(self, profile: dict) -> bool:
        return bool(profile.get("provider") == "openai-compatible" and profile.get("name"))

    def _slugify_source_id(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
        return f"src-{slug or 'custom'}"

    def _official_source_registry(self) -> dict[str, dict]:
        return {
            "北京市地方金融管理局": {
                "source_id": "src-bj-finance",
                "name": "北京市地方金融管理局",
                "kind": "official-site",
                "url": "https://jrj.beijing.gov.cn/",
                "sync_url": "https://jrj.beijing.gov.cn/jrgzdt/",
                "parser": "generic_portal",
                "region": "北京",
                "status": "active",
                "last_checked": "",
                "note": "Official Beijing local financial regulator",
            },
            "上海市地方金融管理局": {
                "source_id": "src-sh-finance",
                "name": "上海市地方金融管理局",
                "kind": "official-site",
                "url": "https://jrj.sh.gov.cn/",
                "sync_url": "https://jrj.sh.gov.cn/zwdt-gg/index.html",
                "parser": "generic_portal",
                "region": "上海",
                "status": "active",
                "last_checked": "",
                "note": "Official Shanghai local financial regulator",
            },
            "国家金融监督管理总局": {
                "source_id": "src-nfra",
                "name": "国家金融监督管理总局",
                "kind": "official-site",
                "url": "https://www.nfra.gov.cn/",
                "sync_url": "https://www.nfra.gov.cn/cn/view/pages/ItemList.html?itemId=411&itemName=%E7%9B%91%E7%AE%A1%E5%8A%A8%E6%80%81&itemPId=1&itemUrl=index.html",
                "parser": "generic_portal",
                "region": "全国",
                "status": "active",
                "last_checked": "",
                "note": "National Financial Regulatory Administration official site",
            },
            "中国人民银行": {
                "source_id": "src-pbc",
                "name": "中国人民银行",
                "kind": "official-site",
                "url": "https://www.pbc.gov.cn/",
                "sync_url": "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html",
                "parser": "generic_portal",
                "region": "全国",
                "status": "active",
                "last_checked": "",
                "note": "People's Bank of China official site",
            },
        }

    def _enrich_event_if_possible(self, event: dict, state: dict) -> dict:
        if not hasattr(self, "ai_service") or self.ai_service is None:
            return {"model": None, "used_llm": False, "event": event}
        try:
            return self.ai_service.enrich_event(event, state["models"])
        except Exception:
            return {"model": None, "used_llm": False, "event": event}

    def _default_fetch_html(self, url: str, timeout: int = 15) -> str:
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",
        }
        response = requests.get(url, headers=headers, timeout=(4, min(timeout, 8)), verify=False)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def _ingest_source_articles(
        self,
        state: dict,
        source: dict,
        list_html: str,
        base_reference: str,
        fetch_html,
        synced_count: int,
        llm_enriched_count: int,
        llm_model: str | None,
        period: str,
        article_limit: int,
        rejected_articles: list[dict] | None = None,
    ) -> tuple[int, int, str | None, str]:
        articles = self._extract_source_articles(source, list_html, base_reference)
        articles = self._filter_articles_for_period(articles, period)[:article_limit]
        if not articles:
            raise ValueError(f"No article-level records parsed from {source['name']}")
        latest_published_at = source.get("last_checked", "")

        for article in articles:
            try:
                detail_html = self._load_article_html(article, fetch_html)
                event = self._event_from_article(source, article, detail_html)
            except Exception as exc:  # noqa: BLE001
                if rejected_articles is not None:
                    rejected_articles.append(
                        {
                            "source_id": source["source_id"],
                            "article_url": article.get("source_url", ""),
                            "reason": str(exc),
                        }
                    )
                continue
            enrichment = self._enrich_event_if_possible(event, state)
            event = enrichment["event"]
            if enrichment["used_llm"]:
                llm_enriched_count += 1
                llm_model = enrichment["model"]
            if not self._event_exists(state["events"], event["title"], event["published_at"]):
                state["events"].insert(0, event)
                synced_count += 1
            if event["published_at"] > latest_published_at:
                latest_published_at = event["published_at"]

        return synced_count, llm_enriched_count, llm_model, latest_published_at

    def _ingest_nfra_penalty_articles(
        self,
        state: dict,
        source: dict,
        synced_count: int,
        llm_enriched_count: int,
        llm_model: str | None,
        period: str,
        article_limit: int,
    ) -> tuple[int, int, str | None, str]:
        articles = self.nfra_adapter.fetch_penalty_articles(
            keyword_filter=lambda title: self._business_scope_matches_text(title)
        )
        articles = self._filter_articles_for_period(articles, period)[:article_limit]
        if not articles:
            if period == "today":
                raise ValueError("No NFRA penalty articles matched the configured business scope keywords in the selected period.")
            return self._ingest_nfra_policy_announcements(
                state=state,
                source=source,
                synced_count=synced_count,
                llm_enriched_count=llm_enriched_count,
                llm_model=llm_model,
                period=period,
                article_limit=article_limit,
            )
        latest_published_at = source.get("last_checked", "")

        for article in articles:
            event = self._event_from_nfra_article(source, article)
            enrichment = self._enrich_event_if_possible(event, state)
            event = enrichment["event"]
            if enrichment["used_llm"]:
                llm_enriched_count += 1
                llm_model = enrichment["model"]
            if not self._event_exists(state["events"], event["title"], event["published_at"]):
                state["events"].insert(0, event)
                synced_count += 1
            if event["published_at"] > latest_published_at:
                latest_published_at = event["published_at"]

        return synced_count, llm_enriched_count, llm_model, latest_published_at

    def _ingest_nfra_policy_announcements(
        self,
        state: dict,
        source: dict,
        synced_count: int,
        llm_enriched_count: int,
        llm_model: str | None,
        period: str,
        article_limit: int,
    ) -> tuple[int, int, str | None, str]:
        articles = self._fetch_nfra_policy_metadata_articles(article_limit=article_limit)
        period_articles = self._filter_articles_for_period(articles, period)[:article_limit]
        selected_articles = period_articles[:article_limit]
        if not selected_articles:
            raise ValueError("No NFRA official policy announcements matched the configured business scope keywords in the selected period.")

        latest_published_at = source.get("last_checked", "")
        for article in selected_articles:
            event = self._event_from_nfra_policy_metadata(source, article)
            enrichment = self._enrich_event_if_possible(event, state)
            event = enrichment["event"]
            if enrichment["used_llm"]:
                llm_enriched_count += 1
                llm_model = enrichment["model"]
            if not self._event_exists(state["events"], event["title"], event["published_at"]):
                state["events"].insert(0, event)
                synced_count += 1
            if event["published_at"] > latest_published_at:
                latest_published_at = event["published_at"]

        return synced_count, llm_enriched_count, llm_model, latest_published_at

    def _fetch_nfra_policy_metadata_articles(self, article_limit: int) -> list[dict]:
        import requests

        item_ids = [4215, 916, 4214, 859, 861, 860, 4216, 926]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        keywords = ["融资租赁", "金融租赁", "商业保理", "保理公司"]
        articles: list[dict] = []
        seen_urls: set[str] = set()

        for item_id in item_ids:
            for page_index in range(1, 4):
                url = (
                    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
                    f"?itemId={item_id}&pageSize=20&pageIndex={page_index}"
                )
                try:
                    response = requests.get(url, headers=headers, timeout=(3, 6), verify=False)
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    continue

                rows = ((payload or {}).get("data") or {}).get("rows") or []
                if not rows:
                    break
                for row in rows:
                    title = self._strip_tags(row.get("docTitle", "") or row.get("docSubtitle", "")).strip()
                    summary = self._strip_tags(row.get("docSummary", "") or row.get("docSubtitle", "") or "").strip()
                    scope_text = " ".join([title, summary])
                    if not any(keyword in scope_text for keyword in keywords):
                        continue
                    pdf_path = row.get("pdfFileUrl", "") or row.get("docFileUrl", "")
                    source_url = (
                        self._absolute_nfra_url(pdf_path)
                        if pdf_path
                        else self._build_nfra_item_detail_url(row.get("docId"), item_id)
                    )
                    if not source_url or source_url in seen_urls:
                        continue
                    seen_urls.add(source_url)
                    articles.append(
                        {
                            "doc_id": str(row.get("docId", "")),
                            "title": title,
                            "summary": summary or title,
                            "published_at": (row.get("publishDate") or "")[:10],
                            "source_url": source_url,
                        }
                    )
                    if len(articles) >= max(article_limit, self.MAX_RELEVANT_EVENTS):
                        return sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)

        return sorted(articles, key=lambda item: item.get("published_at", ""), reverse=True)

    def _absolute_nfra_url(self, path: str) -> str:
        if not path:
            return ""
        if path.startswith("http"):
            return path
        return f"https://www.nfra.gov.cn{path}"

    def _build_nfra_item_detail_url(self, doc_id: str | int | None, item_id: str | int | None) -> str:
        if not doc_id:
            return ""
        if item_id:
            return f"https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={doc_id}&itemId={item_id}"
        return f"https://www.nfra.gov.cn/cn/view/pages/ItemDetail.html?docId={doc_id}"

    def _event_from_nfra_policy_metadata(self, source: dict, article: dict) -> dict:
        title = article.get("title", "")
        published_at = article.get("published_at", "") or date.today().isoformat()
        source_url = article.get("source_url", "")
        summary = article.get("summary", "") or title
        institution_name = "No sanctioned institution in source rule"
        penalty_analysis = self._analyze_article(
            title=title,
            summary=summary,
            category_line="监管规则公告",
        )
        event_id = f"sync-{source['source_id']}-{published_at}-{article.get('doc_id') or abs(hash(source_url))}"
        evidence_path = self._write_evidence_html(event_id, summary)
        event = {
            "event_id": event_id,
            "title": title,
            "regulator": source["name"],
            "region": source.get("region", "全国"),
            "category": "监管动态",
            "institution_type": "监管规则",
            "institution_name": institution_name,
            "institution_name_original": title,
            "severity": "normal",
            "published_at": f"{published_at}T09:00:00",
            "summary": summary,
            "risk_hint": penalty_analysis["compliance_warning"],
            "english_brief": f"Official NFRA announcement relevant to leasing or factoring: {title}",
            "analysis_summary": penalty_analysis["analysis_summary"],
            "penalty_focus": penalty_analysis["penalty_focus"],
            "compliance_warning": penalty_analysis["compliance_warning"],
            "is_penalty_event": False,
            "source_capture_mode": "nfra_policy_metadata",
            "review_status": "pending",
            "reviewer": None,
            "review_notes": "",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "title": title,
                    "url": source_url,
                    "published_at": f"{published_at}T09:00:00",
                }
            ],
            "evidence": [
                {
                    "title": "NFRA official metadata extract",
                    "kind": "text",
                    "path": str(evidence_path),
                }
            ],
        }
        event.update(
            build_event_quality(
                article_url=source_url,
                title=title,
                institution_name=institution_name,
                llm_completed=False,
            )
        )
        return event

    def _extract_source_articles(self, source: dict, html: str, base_reference: str) -> list[dict]:
        articles: list[dict] = []
        for block in re.findall(r"<li[^>]*>(.*?)</li>", html, re.I | re.S):
            anchor = re.search(r'(<a[^>]*>)(.*?)</a>', block, re.I | re.S)
            if not anchor:
                continue
            anchor_tag, title = anchor.groups()
            href = self._extract_first(anchor_tag, r'href="([^"]+)"')
            explicit_source_url = self._extract_first(anchor_tag, r'data-source-url="([^"]+)"')
            if not href:
                continue
            clean_title = self._strip_tags(title)
            if not self._looks_like_article_title(clean_title):
                continue
            published_at = self._extract_first(block, r"([0-9]{4}-[0-9]{2}-[0-9]{2})")
            if not published_at:
                continue
            summary = self._extract_first(
                block,
                r'<p[^>]*class="summary"[^>]*>(.*?)</p>',
                default=self._extract_first(block, r"<p[^>]*>(.*?)</p>"),
            )
            fetch_url = self._resolve_article_fetch_url(href, base_reference)
            source_url = explicit_source_url or (href if href.startswith("http") else urljoin(source.get("url", ""), href))
            if not self._looks_like_article_url(source_url):
                continue
            articles.append(
                {
                    "title": clean_title,
                    "published_at": published_at,
                    "summary": self._strip_tags(summary),
                    "fetch_url": fetch_url,
                    "source_url": source_url,
                }
            )
        return articles

    def _build_single_article(self, source: dict, html: str, base_reference: str) -> dict:
        return {
            "title": self._extract_first(html, r"<h1[^>]*>(.*?)</h1>", default=f"{source['name']} latest update"),
            "published_at": self._extract_first(html, r"发布日期[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", default="2026-07-07"),
            "summary": self._extract_first(html, r'<div class="summary">(.*?)</div>', default=""),
            "fetch_url": base_reference,
            "source_url": source.get("sync_url") or source.get("url") or base_reference,
        }

    def _resolve_article_fetch_url(self, href: str, base_reference: str) -> str:
        if href.startswith("http"):
            return href
        if base_reference.startswith("http"):
            return urljoin(base_reference, href)
        return str((Path(base_reference).parent / href).resolve())

    def _load_article_html(self, article: dict, fetch_html) -> str:
        fetch_url = article.get("fetch_url", "")
        if fetch_url and Path(fetch_url).exists():
            return Path(fetch_url).read_text(encoding="utf-8")
        return fetch_html(fetch_url, timeout=15)

    def _event_from_article(self, source: dict, article: dict, html: str) -> dict:
        title = self._extract_first(html, r"<h1[^>]*>(.*?)</h1>")
        if not title:
            title = article.get("title") or self._extract_first(html, r"<title>(.*?)</title>", default=f"{source['name']} latest update")
        published_at = self._extract_first(
            html,
            r"发布日期[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            default=article.get("published_at", "2026-07-07"),
        )
        institution = self._extract_first(
            html,
            r"机构名称[:：]\s*(.*?)</div>",
            default="待识别机构",
        )
        category_line = self._extract_first(
            html,
            r"(?:主要违法违规事实|违法行为类型)[:：]\s*(.*?)</div>",
            default="监管处罚",
        )
        summary = self._extract_first(
            html,
            r'<div class="summary">(.*?)</div>',
            default=article.get("summary") or category_line,
        )
        if not summary:
            summary = self._extract_first(
                html,
                r"<p[^>]*>(.*?)</p>",
                default=article.get("summary") or category_line or f"{source['name']} latest public update.",
            )

        region = source.get("region", "全国")
        institution_type = "商业保理" if "保理" in institution else "融资租赁"
        category = self._infer_category(category_line or summary or title)
        penalty_analysis = self._analyze_article(title=title, summary=self._strip_tags(summary), category_line=self._strip_tags(category_line))
        severity = "major" if penalty_analysis["is_penalty_event"] else "normal"
        event_id = f"sync-{source['source_id']}-{published_at}-{abs(hash(article.get('source_url', title))) % 100000}"
        evidence_path = self._write_evidence_html(event_id, html)
        institution_name = self._normalize_institution_subject(self._strip_tags(institution))
        event = {
            "event_id": event_id,
            "title": title,
            "regulator": source["name"],
            "region": region,
            "category": category,
            "institution_type": institution_type,
            "institution_name": institution_name,
            "institution_name_original": institution_name,
            "severity": severity,
            "published_at": f"{published_at}T09:00:00",
            "summary": self._strip_tags(summary),
            "risk_hint": penalty_analysis["compliance_warning"],
            "english_brief": f"Latest signal from {source['name']} highlights {self._strip_tags(category_line or summary or title)}.",
            "analysis_summary": penalty_analysis["analysis_summary"],
            "penalty_focus": penalty_analysis["penalty_focus"],
            "compliance_warning": penalty_analysis["compliance_warning"],
            "is_penalty_event": penalty_analysis["is_penalty_event"],
            "source_capture_mode": "live",
            "review_status": "pending",
            "reviewer": None,
            "review_notes": "",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "title": title,
                    "url": article.get("source_url") or source["sync_url"],
                    "published_at": f"{published_at}T09:00:00",
                }
            ],
            "evidence": [
                {
                    "title": "同步原文快照",
                    "kind": "html",
                    "path": str(evidence_path),
                }
            ],
        }
        event.update(
            build_event_quality(
                article_url=article.get("source_url") or source["sync_url"],
                title=title,
                institution_name=institution_name,
                llm_completed=False,
            )
        )
        return event

    def _event_from_crawled_article(self, source: dict, article: dict) -> dict:
        title = article.get("title", "") or f"{source['name']} article"
        published_at = article.get("published_at", "") or date.today().isoformat()
        body_text = self._strip_tags(article.get("body_text", "") or "")
        summary = self._strip_tags(article.get("summary", "") or body_text[:800])
        institution = self._normalize_institution_subject(article.get("institution_name", ""))
        category = self._infer_category(" ".join([title, summary, body_text]))
        penalty_analysis = self._analyze_article(title=title, summary=summary, category_line=body_text[:200])
        severity = "major" if penalty_analysis["is_penalty_event"] else "normal"
        source_url = article.get("source_url") or source.get("sync_url") or source.get("url") or ""
        event_id = f"sync-{source['source_id']}-{published_at}-{abs(hash(source_url or title)) % 100000}"
        evidence_path = self._write_evidence_html(event_id, body_text or summary)
        event = {
            "event_id": event_id,
            "title": title,
            "regulator": article.get("source_name") or source["name"],
            "region": source.get("region", "全国"),
            "category": category,
            "institution_type": "商业保理" if "保理" in institution else "融资租赁",
            "institution_name": institution,
            "institution_name_original": institution,
            "severity": severity,
            "published_at": f"{published_at}T09:00:00",
            "summary": summary,
            "risk_hint": penalty_analysis["compliance_warning"],
            "english_brief": f"Article-level crawl from {source['name']} highlights {title}.",
            "analysis_summary": penalty_analysis["analysis_summary"],
            "penalty_focus": penalty_analysis["penalty_focus"],
            "compliance_warning": penalty_analysis["compliance_warning"],
            "is_penalty_event": penalty_analysis["is_penalty_event"],
            "source_capture_mode": "article_crawler",
            "review_status": "pending",
            "reviewer": None,
            "review_notes": "",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "title": title,
                    "url": source_url,
                    "published_at": f"{published_at}T09:00:00",
                }
            ],
            "evidence": [
                {
                    "title": "同步原文快照",
                    "kind": "text",
                    "path": str(evidence_path),
                }
            ],
        }
        event.update(
            build_event_quality(
                article_url=source_url,
                title=title,
                institution_name=institution,
                llm_completed=False,
            )
        )
        return event

    def _event_from_nfra_article(self, source: dict, article: dict) -> dict:
        title = article.get("title", "")
        published_at = article.get("published_at", "2026-07-07")
        institution = article.get("institution_name", "")
        category_line = article.get("violation_summary", "") or "监管处罚"
        summary = article.get("penalty_text", "") or article.get("violation_summary", "") or title
        penalty_analysis = self._analyze_article(
            title=title,
            summary=self._strip_tags(summary),
            category_line=self._strip_tags(category_line),
        )
        severity = "major" if penalty_analysis["is_penalty_event"] else "normal"
        event_id = f"sync-{source['source_id']}-{published_at}-{article.get('doc_id', abs(hash(title)))}"
        evidence_path = self._write_evidence_html(event_id, article.get("raw_text", summary))
        institution_name = self._normalize_institution_subject(institution)
        event = {
            "event_id": event_id,
            "title": title,
            "regulator": article.get("regulator_name") or source["name"],
            "region": source.get("region", "全国"),
            "category": "监管处罚",
            "institution_type": "商业保理" if "保理" in institution else "融资租赁",
            "institution_name": institution_name,
            "institution_name_original": institution_name,
            "severity": severity,
            "published_at": f"{published_at}T09:00:00",
            "summary": self._strip_tags(summary),
            "risk_hint": penalty_analysis["compliance_warning"],
            "english_brief": f"NFRA penalty signal: {title}",
            "analysis_summary": penalty_analysis["analysis_summary"],
            "penalty_focus": penalty_analysis["penalty_focus"],
            "compliance_warning": penalty_analysis["compliance_warning"],
            "is_penalty_event": True,
            "source_capture_mode": "nfra_pdf",
            "review_status": "pending",
            "reviewer": None,
            "review_notes": "",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "title": title,
                    "url": article.get("source_url") or source["sync_url"],
                    "published_at": f"{published_at}T09:00:00",
                }
            ],
            "evidence": [
                {
                    "title": "NFRA penalty extract",
                    "kind": "text",
                    "path": str(evidence_path),
                }
            ],
        }
        event.update(
            build_event_quality(
                article_url=article.get("source_url") or source["sync_url"],
                title=title,
                institution_name=institution_name,
                llm_completed=False,
            )
        )
        return event

    def _derive_source_health(self, source: dict) -> str:
        last_result = (source.get("last_sync_result") or "").lower()
        if not last_result:
            return "not-run"
        if last_result == "ok":
            return "healthy"
        if last_result.startswith("error"):
            return "error"
        if last_result == "unsupported":
            return "attention"
        return "unknown"

    def _analyze_article(self, title: str, summary: str, category_line: str) -> dict:
        text = " ".join([title, summary, category_line])
        if any(keyword in text for keyword in ["客户资金", "异常交易"]):
            return {
                "penalty_focus": "Customer funds monitoring and suspicious activity controls",
                "analysis_summary": "The article highlights control expectations around customer funds, transaction purpose checks, and suspicious activity reporting.",
                "compliance_warning": "Early warning: review customer funds controls, transaction monitoring rules, and unusual activity escalation standards.",
                "is_penalty_event": True,
            }
        if any(keyword in text for keyword in ["关联交易", "关联方"]):
            return {
                "penalty_focus": "Related-party governance and approval controls",
                "analysis_summary": "The article points to insufficient related-party identification, approval, and disclosure controls.",
                "compliance_warning": "Early warning: review related-party identification, approval routing, and management reporting for connected transactions.",
                "is_penalty_event": True,
            }
        if any(keyword in text for keyword in ["报送", "披露", "公告", "迟报"]):
            return {
                "penalty_focus": "Disclosure and reporting discipline",
                "analysis_summary": "The article focuses on delayed or incomplete regulatory reporting, suggesting increasing sensitivity to submission timeliness and disclosure accuracy.",
                "compliance_warning": "Early warning: recheck reporting timeliness, disclosure completeness, and governance over regulatory submissions.",
                "is_penalty_event": True,
            }
        if any(keyword in text for keyword in ["真实性", "租赁物", "穿透", "核验"]):
            return {
                "penalty_focus": "Asset authenticity and penetration review",
                "analysis_summary": "The article indicates regulators are testing whether the institution can prove the authenticity of underlying leased or financed assets.",
                "compliance_warning": "Early warning: verify asset authenticity checks, penetration review evidence, and exception escalation for leasing or factoring transactions.",
                "is_penalty_event": True,
            }
        return {
            "penalty_focus": "General regulatory compliance signal",
            "analysis_summary": "The article signals a compliance theme that may affect local control execution or regulatory engagement expectations.",
            "compliance_warning": f"Early warning: assess whether the control theme in this article could expose Siemens Financial Leasing or Commercial Factoring to avoidable regulatory findings.",
            "is_penalty_event": any(keyword in text for keyword in ["处罚", "罚", "整改", "监管措施"]),
        }

    def _write_evidence_html(self, event_id: str, html: str) -> Path:
        evidence_dir = self.runtime_root / "evidence" / event_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / "source.html"
        evidence_path.write_text(html, encoding="utf-8")
        return evidence_path

    def _load_fallback_html(self, source: dict, include_reference: bool = False):
        fallback_path = source.get("fallback_html")
        if not fallback_path:
            raise FileNotFoundError("fallback snapshot not configured")
        path = (
            Path(fallback_path)
            if Path(fallback_path).is_absolute()
            else self.seeds_path.parents[2] / fallback_path
        )
        html = path.read_text(encoding="utf-8")
        if include_reference:
            return html, str(path)
        return html

    def _event_exists(self, events: list[dict], title: str, published_at: str) -> bool:
        target = f"{published_at}T09:00:00"
        return any(
            event["title"] == title and event["published_at"] == target
            for event in events
        )

    def _extract_first(self, html: str, pattern: str, default: str = "") -> str:
        match = re.search(pattern, html, re.S)
        return match.group(1).strip() if match else default

    def _strip_tags(self, text: str) -> str:
        return re.sub(r"<.*?>", "", text).strip()

    def _infer_category(self, text: str) -> str:
        normalized = self._strip_tags(text)
        if any(keyword in normalized for keyword in ["处罚", "罚", "罚款", "整改"]):
            return "监管处罚"
        if any(keyword in normalized for keyword in ["披露", "报送", "公告"]):
            return "信息披露"
        if any(keyword in normalized for keyword in ["监管", "政策", "动态", "通知"]):
            return "监管动态"
        if any(keyword in normalized for keyword in ["关联交易", "关联方"]):
            return "关联交易"
        if any(keyword in normalized for keyword in ["信用", "执行", "异常"]):
            return "信用风险"
        return "业务合规"

    def _infer_region_from_text(self, text: str) -> str:
        if "北京" in text:
            return "北京"
        if "上海" in text:
            return "上海"
        return "全国"

    def _normalize_institution_subject(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            return "Not disclosed in source article"
        return normalized

    def _looks_like_article_title(self, title: str) -> bool:
        normalized = title.strip()
        if not normalized:
            return False
        if normalized in {"首页", "Home"}:
            return False
        if "{{" in normalized or "}}" in normalized:
            return False
        return True

    def _looks_like_article_url(self, url: str) -> bool:
        normalized = (url or "").strip().lower()
        if not normalized:
            return False
        bad_patterns = [
            "/index.html",
            "/index/index.html",
            "javascript:",
            "{{",
            "}}",
        ]
        return not any(pattern in normalized for pattern in bad_patterns)

    def _render_html_report(self, snapshot: dict) -> str:
        module = snapshot.get("module", "dashboard")
        if module == "sources":
            rows = "".join(
                "<tr>"
                f"<td>{source.get('name', '')}</td>"
                f"<td>{source.get('region', '')}</td>"
                f"<td>{source.get('status', '')}</td>"
                f"<td>{source.get('last_sync_result', '')}</td>"
                "</tr>"
                for source in snapshot.get("sources", [])
            )
            table = (
                "<tr><th>Name</th><th>Region</th><th>Status</th><th>Last Sync Result</th></tr>"
                f"{rows}"
            )
        elif module == "models":
            models = snapshot.get("models", {}).get("profiles", [])
            rows = "".join(
                "<tr>"
                f"<td>{profile.get('name', '')}</td>"
                f"<td>{profile.get('provider', '')}</td>"
                f"<td>{profile.get('model_id', '')}</td>"
                f"<td>{profile.get('base_url', '')}</td>"
                "</tr>"
                for profile in models
            )
            table = (
                "<tr><th>Name</th><th>Provider</th><th>Model ID</th><th>Base URL</th></tr>"
                f"{rows}"
            )
        else:
            rows = "".join(
                "<tr>"
                f"<td>{event.get('published_at', '')[:10]}</td>"
                f"<td>{event.get('title', event.get('institution', ''))}</td>"
                f"<td>{event.get('regulator', '')}</td>"
                f"<td>{event.get('region', '')}</td>"
                f"<td>{event.get('category', '')}</td>"
                f"<td>{event.get('severity', '')}</td>"
                "</tr>"
                for event in snapshot.get("events", [])
            )
            table = (
                "<tr><th>Date</th><th>Title</th><th>Regulator</th><th>Region</th><th>Category</th><th>Severity</th></tr>"
                f"{rows}"
            )
        return (
            "<html><head><meta charset='utf-8'><title>ComplianceRadar Module Report</title></head>"
            "<body>"
            f"<h1>ComplianceRadar {module.title()} Report</h1>"
            f"<p>{snapshot.get('trend_window', {}).get('label', '')}</p>"
            f"<p>Total events: {snapshot.get('summary', {}).get('total_events', 0)}</p>"
            f"<p>Major events: {snapshot.get('summary', {}).get('major_events', 0)}</p>"
            "<table border='1' cellspacing='0' cellpadding='6'>"
            f"{table}</table></body></html>"
        )

    def _render_pdf_report(self, snapshot: dict, pdf_path: Path) -> None:
        module = snapshot.get("module", "dashboard")
        report = canvas.Canvas(str(pdf_path), pagesize=A4)
        report.setFont("Helvetica-Bold", 16)
        report.drawString(40, 800, f"ComplianceRadar {module.title()} Report")
        report.setFont("Helvetica", 10)
        report.drawString(40, 780, snapshot.get("trend_window", {}).get("label", ""))
        report.drawString(40, 760, f"Total events: {snapshot.get('summary', {}).get('total_events', 0)}")
        report.drawString(200, 760, f"Major events: {snapshot.get('summary', {}).get('major_events', 0)}")
        y = 750
        lines = []
        if module == "sources":
            lines = [
                f"{source.get('name', '')} | {source.get('region', '')} | {source.get('last_sync_result', '')[:60]}"
                for source in snapshot.get("sources", [])[:12]
            ]
        elif module == "models":
            lines = [
                f"{profile.get('name', '')} | {profile.get('model_id', '')} | {profile.get('base_url', '')[:60]}"
                for profile in snapshot.get("models", {}).get("profiles", [])[:12]
            ]
        else:
            lines = [
                f"{event.get('published_at', '')[:10]} | {event.get('region', '')} | {event.get('title', event.get('institution', ''))[:60]}"
                for event in snapshot.get("events", [])[:12]
            ]
        for line in lines:
            report.drawString(40, y, line)
            y -= 18
            if y < 60:
                report.showPage()
                report.setFont("Helvetica", 10)
                y = 800
        report.save()
