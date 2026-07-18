from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


@dataclass
class SourceDiagnosticResult:
    source_id: str
    source_name: str
    sync_url: str
    http_status: int | None
    final_url: str | None
    fetch_mode: str
    evidence: dict
    recommended_adapter: str
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "sync_url": self.sync_url,
            "http_status": self.http_status,
            "final_url": self.final_url,
            "fetch_mode": self.fetch_mode,
            "evidence": self.evidence,
            "recommended_adapter": self.recommended_adapter,
            "notes": self.notes,
        }


class SourceDiagnosticsService:
    def __init__(self, timeout: int = 40) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def diagnose(self, source: dict) -> dict:
        sync_url = source.get("sync_url") or source.get("url") or ""
        notes: list[str] = []
        if not sync_url:
            return SourceDiagnosticResult(
                source_id=source["source_id"],
                source_name=source["name"],
                sync_url=sync_url,
                http_status=None,
                final_url=None,
                fetch_mode="invalid",
                evidence={},
                recommended_adapter="unsupported",
                notes=["Source has no sync URL."],
            ).to_dict()

        try:
            response = requests.get(
                sync_url,
                headers=self.headers,
                timeout=self.timeout,
                verify=False,
            )
            response.encoding = response.apparent_encoding or response.encoding
            html = response.text
        except Exception as exc:  # noqa: BLE001
            return SourceDiagnosticResult(
                source_id=source["source_id"],
                source_name=source["name"],
                sync_url=sync_url,
                http_status=None,
                final_url=None,
                fetch_mode="network_error",
                evidence={},
                recommended_adapter="browser_required",
                notes=[f"Network fetch failed: {exc}"],
            ).to_dict()

        evidence = {
            "contains_li_links": bool(re.search(r"<li[^>]*>.*?<a[^>]+href=", html, re.I | re.S)),
            "contains_docinfo_api": "/DocInfo/" in html,
            "contains_angular": "ng-controller" in html or "angular" in html.lower(),
            "contains_tpl": "<tpl" in html.lower(),
            "contains_index_href": "/index.html" in html.lower(),
            "script_count": len(re.findall(r"<script[^>]+src=", html, re.I)),
            "html_length": len(html),
        }

        recommended_adapter = "generic_portal"
        fetch_mode = "static_html"
        if evidence["contains_docinfo_api"] or evidence["contains_angular"] or evidence["contains_tpl"]:
            recommended_adapter = "nfra_docinfo"
            fetch_mode = "dynamic_shell"
            notes.append("Page shell is dynamic and likely populated through DocInfo/item APIs.")
        elif not evidence["contains_li_links"]:
            recommended_adapter = "browser_required"
            fetch_mode = "non_article_shell"
            notes.append("No article list found in the initial HTML.")
        else:
            notes.append("Initial HTML contains article-like list items.")

        notes.extend(self._source_specific_hints(source, html))

        return SourceDiagnosticResult(
            source_id=source["source_id"],
            source_name=source["name"],
            sync_url=sync_url,
            http_status=response.status_code,
            final_url=response.url,
            fetch_mode=fetch_mode,
            evidence=evidence,
            recommended_adapter=recommended_adapter,
            notes=notes,
        ).to_dict()

    def _source_specific_hints(self, source: dict, html: str) -> list[str]:
        hints: list[str] = []
        source_id = source.get("source_id", "")
        if source_id == "src-nfra":
            script_url = "https://www.nfra.gov.cn/cn/js/common/Script.js?v=20200108"
            try:
                response = requests.get(
                    script_url,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=False,
                )
                response.encoding = response.apparent_encoding or response.encoding
                script = response.text
                api_url_dev = self._extract_first(script, r"var apiUrl_dev = originUrl \+ \"([^\"]+)\"")
                api_url_cdn = self._extract_first(script, r"var apiUrl_cdn =\s+originUrl \+ \"([^\"]+)\"")
                if api_url_dev:
                    hints.append(f"Detected NFRA dynamic API root: {api_url_dev}")
                if api_url_cdn:
                    hints.append(f"Detected NFRA CDN data root: {api_url_cdn}")
                if "/DocInfo/SelectDocByItemIdAndChild" in script:
                    hints.append("Detected NFRA list API signature: /DocInfo/SelectDocByItemIdAndChild")
                if "/DocInfo/SelectByDocId" in script:
                    hints.append("Detected NFRA detail API signature: /DocInfo/SelectByDocId")
            except Exception as exc:  # noqa: BLE001
                hints.append(f"Unable to inspect NFRA Script.js: {exc}")
        if source_id == "src-pbc":
            hints.append("Current PBC list page often times out in this environment; a browser-assisted adapter is likely required.")
        if source_id in {"src-bj-finance", "src-sh-finance"}:
            hints.append("Local finance bureau pages may require browser rendering or alternative list endpoints under slower network conditions.")
        return hints

    def _extract_first(self, text: str, pattern: str) -> str:
        match = re.search(pattern, text, re.S)
        return match.group(1).strip() if match else ""
