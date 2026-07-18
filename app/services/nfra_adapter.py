from __future__ import annotations

import io
import re
from typing import Callable

import pdfplumber
import requests


class NFRAAdapter:
    PENALTY_LIST_URL = (
        "https://www.nfra.gov.cn/cn/static/data/DocInfo/"
        "SelectItemAndDocByItemPId/data_itemId=931,pageSize=10.json"
    )

    def __init__(self, headers: dict | None = None, timeout: int = 40) -> None:
        self.timeout = timeout
        self.headers = headers or {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def fetch_penalty_articles(
        self,
        keyword_filter: Callable[[str], bool] | None = None,
    ) -> list[dict]:
        response = requests.get(
            self.PENALTY_LIST_URL,
            headers=self.headers,
            timeout=self.timeout,
            verify=False,
        )
        response.raise_for_status()
        payload = response.json()
        groups = payload.get("data") or []
        articles: list[dict] = []

        for group in groups:
            for doc in group.get("docInfoVOList") or []:
                title = self._clean_text(doc.get("docTitle", ""))
                if keyword_filter and not keyword_filter(title):
                    continue
                pdf_path = doc.get("pdfFileUrl")
                if not pdf_path:
                    continue
                pdf_url = self._absolute_url(pdf_path)
                pdf_bytes = self._download_binary(pdf_url)
                extracted = self._extract_penalty_fields_from_pdf(pdf_bytes)
                scope_text = " ".join(
                    [
                        title,
                        extracted.get("institution_name", ""),
                        extracted.get("violation_summary", ""),
                        extracted.get("penalty_text", ""),
                        extracted.get("raw_text", "")[:500],
                    ]
                )
                if keyword_filter and not keyword_filter(scope_text):
                    continue
                articles.append(
                    {
                        "doc_id": str(doc.get("docId")),
                        "title": title,
                        "published_at": (doc.get("publishDate") or "")[:10],
                        "source_url": pdf_url,
                        "fetch_url": pdf_url,
                        "summary": extracted.get("violation_summary", ""),
                        "institution_name": extracted.get("institution_name", ""),
                        "penalty_text": extracted.get("penalty_text", ""),
                        "regulator_name": extracted.get("regulator_name", ""),
                        "raw_text": extracted.get("raw_text", ""),
                    }
                )

        articles.sort(key=lambda item: item.get("published_at", ""), reverse=True)
        return articles

    def _download_binary(self, url: str) -> bytes:
        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout,
            verify=False,
        )
        response.raise_for_status()
        return response.content

    def _extract_penalty_fields_from_pdf(self, data: bytes) -> dict:
        raw_text = ""
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            raw_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        compact = self._clean_text(raw_text)
        institution_name = self._extract_between(compact, "当事人名称", "主要违法违规行为")
        violation_summary = self._extract_between(compact, "主要违法违规行为", "行政处罚内容")
        penalty_text = self._extract_between(compact, "行政处罚内容", "作出决定机关")
        regulator_name = self._extract_after(compact, "作出决定机关")
        return {
            "institution_name": institution_name or "Not disclosed in source article",
            "violation_summary": violation_summary,
            "penalty_text": penalty_text,
            "regulator_name": regulator_name,
            "raw_text": compact,
        }

    def _extract_between(self, text: str, start: str, end: str) -> str:
        pattern = re.escape(start) + r"(.*?)" + re.escape(end)
        match = re.search(pattern, text, re.S)
        return self._clean_text(match.group(1)) if match else ""

    def _extract_after(self, text: str, start: str) -> str:
        pattern = re.escape(start) + r"(.*)$"
        match = re.search(pattern, text, re.S)
        return self._clean_text(match.group(1)) if match else ""

    def _absolute_url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"https://www.nfra.gov.cn{path}"

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()
