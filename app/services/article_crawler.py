from __future__ import annotations

import io
import re
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse, unquote

import pdfplumber
import requests
from bs4 import BeautifulSoup

from app.services.nfra_adapter import NFRAAdapter


class ArticleCrawlerService:
    KEYWORD_EQUIVALENTS = {
        "融资租赁": ["融资租赁", "融资租赁公司", "金融租赁", "金融租赁公司", "融资性租赁"],
        "商业保理": ["商业保理", "商业保理公司", "保理", "保理公司"],
    }
    CORE_SCOPE_KEYWORDS = {
        "融资租赁",
        "融资租赁公司",
        "金融租赁",
        "金融租赁公司",
        "融资性租赁",
        "商业保理",
        "商业保理公司",
        "保理公司",
    }
    NFRA_POLICY_ITEM_IDS = [916, 926, 4213, 859, 862, 877, 889, 4221, 4214, 4215, 4216, 860, 861]
    NFRA_POLICY_METADATA_SCAN_LIMIT = 6
    NFRA_DYNAMIC_ITEM_IDS = [4215, 916, 4214, 859, 861, 860, 4216, 926]
    NFRA_DYNAMIC_PAGE_SIZE = 18
    NFRA_DYNAMIC_PAGE_LIMIT = 3
    NFRA_DYNAMIC_ROW_SCAN_LIMIT = 8

    def __init__(self, nfra_adapter: NFRAAdapter, timeout: int = 40) -> None:
        self.nfra_adapter = nfra_adapter
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def fetch_relevant_articles(
        self,
        source: dict,
        keywords: list[str],
        limit: int = 10,
    ) -> list[dict]:
        normalized_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
        if not normalized_keywords:
            raise ValueError("At least one keyword is required.")
        expanded_keywords = self._expand_keywords(normalized_keywords)

        source_id = source.get("source_id", "")
        parser = source.get("parser", "")
        source_url = source.get("url", "")
        sync_url = source.get("sync_url", "")
        if (
            source_id == "src-nfra"
            or parser == "nfra_docinfo"
            or "nfra.gov.cn" in source_url
            or "nfra.gov.cn" in sync_url
        ):
            return self._fetch_nfra_relevant_articles(source, expanded_keywords, limit)

        list_url = source.get("sync_url") or source.get("url") or ""
        if not list_url:
            raise ValueError(f"Source {source_id} has no sync URL.")

        article_links: list[dict] = []
        try:
            html = self._fetch_html(list_url)
            article_links = self._extract_article_links(html, list_url)
        except Exception:
            article_links = []

        if not article_links and source.get("allow_search_fallback"):
            article_links = self._discover_official_articles_via_search(source, expanded_keywords, limit * 3)

        matches: list[dict] = []

        for article in article_links:
            combined = " ".join([article.get("title", ""), article.get("summary", "")])
            if not self._contains_keyword(combined, expanded_keywords):
                continue
            try:
                detail_html = self._fetch_html(article["source_url"])
            except Exception:
                continue
            body_text = self._extract_main_text(detail_html)
            scope_text = " ".join([article.get("title", ""), body_text])
            if not self._contains_keyword(scope_text, expanded_keywords):
                continue
            if not self._is_materially_relevant(
                article.get("title", ""),
                article.get("summary", ""),
                body_text,
                expanded_keywords,
            ):
                continue
            matches.append(
                {
                    "source_id": source_id,
                    "source_name": source.get("name", ""),
                    "title": article.get("title", ""),
                    "published_at": article.get("published_at", ""),
                    "source_url": article["source_url"],
                    "institution_name": self._extract_institution_name(body_text),
                    "body_text": body_text,
                    "matched_keywords": self._matched_keywords(scope_text, expanded_keywords),
                    "extractor": "requests_html",
                }
            )
            if len(matches) >= limit:
                break

        return matches

    def analyze_direct_article(
        self,
        source: dict,
        article_url: str,
        keywords: list[str],
    ) -> dict:
        expanded_keywords = self._expand_keywords(keywords)
        if article_url.lower().endswith(".pdf"):
            return self._analyze_direct_pdf(source, article_url, expanded_keywords)
        html = self._fetch_html(article_url)
        body_text = self._extract_main_text(html)
        title = self._extract_title(html) or article_url
        scope_text = " ".join([title, body_text])
        return {
            "source_id": source.get("source_id", ""),
            "source_name": source.get("name", ""),
            "title": title,
            "published_at": self._extract_document_date(html),
            "source_url": article_url,
            "institution_name": self._extract_institution_name(body_text),
            "body_text": body_text,
            "raw_html": html,
            "matched_keywords": self._matched_keywords(scope_text, expanded_keywords),
            "extractor": "direct_article",
        }

    def _analyze_direct_pdf(self, source: dict, article_url: str, keywords: list[str]) -> dict:
        response = requests.get(
            article_url,
            headers=self.headers,
            timeout=self.timeout,
            verify=False,
        )
        response.raise_for_status()
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            body_text = " ".join((page.extract_text() or "") for page in pdf.pages)
        body_text = self._clean_text(body_text)
        title = self._extract_title_from_pdf_text(body_text) or article_url.rsplit("/", 1)[-1]
        scope_text = " ".join([title, body_text])
        return {
            "source_id": source.get("source_id", ""),
            "source_name": source.get("name", ""),
            "title": title,
            "published_at": "",
            "source_url": article_url,
            "institution_name": self._extract_institution_name(body_text),
            "body_text": body_text,
            "matched_keywords": self._matched_keywords(scope_text, keywords),
            "extractor": "direct_pdf",
        }

    def _discover_official_articles_via_search(
        self,
        source: dict,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        domain = urlparse(source.get("url") or source.get("sync_url") or "").netloc
        if not domain:
            return []
        search_terms = [
            term
            for term in ["融资租赁", "商业保理"]
            if term in keywords
        ] or keywords[:2]
        queries = [f"site:{domain} {keyword}" for keyword in search_terms]
        queries.append(f"site:{domain} " + " ".join(search_terms[:2]))
        discovered: list[dict] = []
        seen: set[str] = set()
        for builder, query_set in (
            (self._bing_search_url, queries),
            (self._duckduckgo_search_url, queries[:1]),
        ):
            for query in query_set:
                try:
                    html = self._fetch_html(builder(query))
                    links = self._extract_search_result_links(html, domain)
                except Exception:
                    continue
                for link in links:
                    url = link.get("source_url", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    discovered.append(link)
                    if len(discovered) >= limit:
                        return discovered
                if discovered and builder == self._bing_search_url:
                    break
            if discovered:
                break
        return discovered

    def _extract_search_result_links(self, html: str, domain: str) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            raw_href = anchor.get("href", "")
            href = self._unwrap_search_result_url(raw_href)
            if href.startswith("/"):
                continue
            if domain not in href:
                continue
            if href in seen:
                continue
            title = self._clean_text(anchor.get_text(" ", strip=True)) or self._clean_text(href)
            if not title:
                continue
            seen.add(href)
            results.append(
                {
                    "title": title,
                    "summary": "",
                    "published_at": "",
                    "source_url": href,
                }
            )
        return results

    def _unwrap_search_result_url(self, href: str) -> str:
        normalized = unescape(href or "").strip()
        if normalized.startswith("//"):
            normalized = f"https:{normalized}"
        if normalized.startswith("/"):
            return normalized
        parsed = urlparse(normalized)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            params = parse_qs(parsed.query)
            uddg = params.get("uddg", [""])[0]
            return unquote(uddg) if uddg else normalized
        return normalized

    def _fetch_nfra_relevant_articles(
        self,
        source: dict,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        combined: list[dict] = []
        seen_urls: set[str] = set()

        for article in self._fetch_nfra_articles(source, keywords, limit):
            url = article.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(article)
                if len(combined) >= limit:
                    return combined

        if combined:
            ranked = self._rank_articles_by_scope_relevance(combined, keywords)
            return ranked[:limit]

        for article in self._fetch_nfra_policy_articles(source, keywords, limit * 4):
            url = article.get("source_url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                combined.append(article)
                if len(combined) >= limit * 4:
                    break

        ranked = self._rank_articles_by_scope_relevance(combined, keywords)
        return ranked[:limit]

    def _fetch_nfra_policy_articles(
        self,
        source: dict,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        dynamic_articles = self._fetch_nfra_dynamic_policy_articles(source, keywords, limit)
        if dynamic_articles:
            return dynamic_articles[:limit]

        articles: list[dict] = []
        seen_urls: set[str] = set()

        for item_id in self.NFRA_POLICY_ITEM_IDS:
            url = (
                "https://www.nfra.gov.cn/cn/static/data/DocInfo/"
                f"SelectItemAndDocByItemPId/data_itemId={item_id},pageSize=10.json"
            )
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=self.timeout,
                    verify=False,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue

            item_candidates: list[dict] = []
            for group in payload.get("data") or []:
                for doc in group.get("docInfoVOList") or []:
                    title = self._clean_text(doc.get("docTitle", "") or doc.get("docSubtitle", ""))
                    summary = self._clean_text(doc.get("docSummary", "") or doc.get("docSubtitle", ""))
                    scope_text = " ".join([title, summary])

                    pdf_url = self._absolute_nfra_url(doc.get("pdfFileUrl", ""))
                    source_url = pdf_url or self._build_nfra_item_detail_url(doc.get("docId"), group.get("itemId") or item_id)
                    if not source_url or source_url in seen_urls:
                        continue

                    candidate = {
                        "source_id": source.get("source_id", ""),
                        "source_name": source.get("name", ""),
                        "title": title,
                        "published_at": (doc.get("publishDate") or "")[:10],
                        "source_url": source_url,
                        "institution_name": "Not disclosed in source article",
                        "body_text": scope_text,
                        "matched_keywords": self._matched_keywords(scope_text, keywords),
                        "extractor": "nfra_policy_meta",
                        "summary": summary,
                        "regulator_name": source.get("name", ""),
                        "pdf_url": pdf_url,
                    }

                    if candidate["matched_keywords"]:
                        articles.append(self._finalize_nfra_policy_candidate(source, candidate, keywords))
                        seen_urls.add(source_url)
                        if len(articles) >= limit:
                            return articles
                        continue

                    item_candidates.append(candidate)

            for candidate in item_candidates[: self.NFRA_POLICY_METADATA_SCAN_LIMIT]:
                try:
                    enriched = self._finalize_nfra_policy_candidate(source, candidate, keywords)
                except Exception:
                    continue
                if not enriched.get("matched_keywords"):
                    continue
                if enriched["source_url"] in seen_urls:
                    continue
                articles.append(enriched)
                seen_urls.add(enriched["source_url"])
                if len(articles) >= limit:
                    return articles

        return self._rank_articles_by_scope_relevance(articles, keywords)[:limit]

    def _fetch_nfra_dynamic_policy_articles(
        self,
        source: dict,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        articles: list[dict] = []
        seen_urls: set[str] = set()

        for item_id in self.NFRA_DYNAMIC_ITEM_IDS:
            for page_index in range(1, self.NFRA_DYNAMIC_PAGE_LIMIT + 1):
                url = (
                    "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
                    f"?itemId={item_id}&pageSize={self.NFRA_DYNAMIC_PAGE_SIZE}&pageIndex={page_index}"
                )
                try:
                    response = requests.get(
                        url,
                        headers=self.headers,
                        timeout=self.timeout,
                        verify=False,
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    continue

                rows = ((payload or {}).get("data") or {}).get("rows") or []
                if not rows:
                    break

                strong_candidates: list[dict] = []
                fallback_candidates: list[dict] = []
                for row in rows[: self.NFRA_DYNAMIC_ROW_SCAN_LIMIT]:
                    title = self._clean_text(row.get("docTitle", "") or row.get("docSubtitle", ""))
                    summary = self._clean_text(row.get("docSummary", "") or row.get("docSubtitle", ""))
                    pdf_url = self._absolute_nfra_url(row.get("pdfFileUrl", "") or row.get("docFileUrl", ""))
                    source_url = pdf_url or self._build_nfra_item_detail_url(row.get("docId"), item_id)
                    if not source_url or source_url in seen_urls:
                        continue

                    candidate = {
                        "source_id": source.get("source_id", ""),
                        "source_name": source.get("name", ""),
                        "title": title,
                        "published_at": (row.get("publishDate") or "")[:10],
                        "source_url": source_url,
                        "institution_name": "Not disclosed in source article",
                        "body_text": " ".join([title, summary]),
                        "matched_keywords": self._matched_keywords(" ".join([title, summary]), keywords),
                        "extractor": "nfra_policy_dynamic_meta",
                        "summary": summary,
                        "regulator_name": source.get("name", ""),
                        "pdf_url": pdf_url,
                    }

                    pre_score = self._scope_relevance_score(candidate, keywords)
                    if pre_score >= 120:
                        strong_candidates.append(candidate)
                    elif pre_score >= 40:
                        fallback_candidates.append(candidate)

                for candidate in strong_candidates + fallback_candidates:
                    try:
                        enriched = self._finalize_nfra_policy_candidate(source, candidate, keywords)
                    except Exception:
                        continue
                    if not enriched.get("matched_keywords"):
                        continue
                    articles.append(enriched)
                    seen_urls.add(candidate.get("source_url", ""))
                    if len(articles) >= limit * 3:
                        break

                if len(articles) >= limit * 3:
                    break

            if len(articles) >= limit * 3:
                break

        return self._rank_articles_by_scope_relevance(articles, keywords)[:limit]

    def _finalize_nfra_policy_candidate(
        self,
        source: dict,
        candidate: dict,
        keywords: list[str],
    ) -> dict:
        pdf_url = candidate.get("pdf_url", "")
        title = candidate.get("title", "")
        summary = candidate.get("summary", "")
        body_text = candidate.get("body_text", "")
        institution_name = candidate.get("institution_name", "Not disclosed in source article")
        extractor = candidate.get("extractor", "nfra_policy_meta")

        if pdf_url:
            detailed = self._analyze_direct_pdf(source, pdf_url, keywords)
            title = detailed.get("title", title)
            body_text = detailed.get("body_text", body_text)
            institution_name = detailed.get("institution_name", institution_name)
            extractor = detailed.get("extractor", extractor)
            detailed_matches = detailed.get("matched_keywords", [])
        elif candidate.get("source_url", "").startswith("http"):
            detail_html = self._fetch_html(candidate["source_url"])
            body_text = self._extract_main_text(detail_html)
            title = self._extract_title(detail_html) or title
            institution_name = self._extract_institution_name(body_text)
            extractor = "nfra_policy_html"
            detailed_matches = self._matched_keywords(" ".join([title, summary, body_text]), keywords)
        else:
            detailed_matches = candidate.get("matched_keywords", [])

        scope_text = " ".join([title, summary, body_text])
        if not detailed_matches and not self._is_materially_relevant(title, summary, body_text, keywords):
            return {
                "source_id": candidate.get("source_id", ""),
                "source_name": candidate.get("source_name", ""),
                "title": title,
                "published_at": candidate.get("published_at", ""),
                "source_url": candidate.get("source_url", ""),
                "institution_name": institution_name,
                "body_text": body_text or summary,
                "matched_keywords": [],
                "extractor": extractor,
                "summary": summary or body_text[:500],
                "regulator_name": candidate.get("regulator_name", source.get("name", "")),
            }
        return {
            "source_id": candidate.get("source_id", ""),
            "source_name": candidate.get("source_name", ""),
            "title": title,
            "published_at": candidate.get("published_at", ""),
            "source_url": candidate.get("source_url", ""),
            "institution_name": institution_name,
            "body_text": body_text or summary,
            "matched_keywords": detailed_matches or self._matched_keywords(scope_text, keywords),
            "extractor": extractor,
            "summary": summary or body_text[:500],
            "regulator_name": candidate.get("regulator_name", source.get("name", "")),
        }

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

    def _fetch_nfra_articles(self, source: dict, keywords: list[str], limit: int) -> list[dict]:
        articles = self.nfra_adapter.fetch_penalty_articles(
            keyword_filter=lambda text: self._contains_keyword(text, keywords)
        )
        results: list[dict] = []
        for article in articles[:limit]:
            scope_text = " ".join(
                [
                    article.get("title", ""),
                    article.get("institution_name", ""),
                    article.get("summary", ""),
                    article.get("penalty_text", ""),
                    article.get("raw_text", ""),
                ]
            )
            results.append(
                {
                    "source_id": source.get("source_id", ""),
                    "source_name": source.get("name", ""),
                    "title": article.get("title", ""),
                    "published_at": article.get("published_at", ""),
                    "source_url": article.get("source_url", ""),
                    "institution_name": article.get("institution_name", ""),
                    "body_text": article.get("raw_text", ""),
                    "matched_keywords": self._matched_keywords(scope_text, keywords),
                    "extractor": "nfra_pdf",
                    "summary": article.get("summary", ""),
                    "penalty_text": article.get("penalty_text", ""),
                    "regulator_name": article.get("regulator_name", ""),
                }
            )
        return results

    def _fetch_html(self, url: str) -> str:
        response = requests.get(
            url,
            headers=self.headers,
            timeout=self.timeout,
            verify=False,
        )
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def _extract_article_links(self, html: str, base_url: str) -> list[dict]:
        articles: list[dict] = []
        seen: set[str] = set()
        for match in re.finditer(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", html, re.I | re.S):
            href, title_html = match.groups()
            title = self._clean_text(title_html)
            if not title or len(title) < 4:
                continue
            source_url = urljoin(base_url, href)
            if source_url in seen or not self._looks_like_article_url(source_url):
                continue
            seen.add(source_url)
            articles.append(
                {
                    "title": title,
                    "summary": "",
                    "published_at": self._extract_nearby_date(html, match.start()),
                    "source_url": source_url,
                }
            )
        return articles

    def _extract_nearby_date(self, html: str, index: int) -> str:
        window = html[max(0, index - 120) : index + 120]
        match = re.search(r"([0-9]{4}-[0-9]{2}-[0-9]{2})", window)
        return match.group(1) if match else ""

    def _extract_document_date(self, html: str) -> str:
        text = self._clean_text(re.sub(r"<[^>]+>", " ", html))
        for pattern in (
            r"(?:发布时间|发布日期)[:：]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            r"([0-9]{4}-[0-9]{2}-[0-9]{2})",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _extract_main_text(self, html: str) -> str:
        try:
            import trafilatura

            extracted = trafilatura.extract(html, include_links=False, include_formatting=False)
            if extracted:
                return self._clean_text(extracted)
        except Exception:
            pass
        stripped = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
        stripped = re.sub(r"<style.*?</style>", " ", stripped, flags=re.I | re.S)
        return self._clean_text(re.sub(r"<[^>]+>", " ", stripped))

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        article_title = soup.find("meta", attrs={"name": re.compile(r"^ArticleTitle$", re.I)})
        if article_title and article_title.get("content"):
            title = self._clean_text(
                re.sub(r"<[^>]+>", " ", unescape(article_title.get("content", "")))
            )
            if title:
                return title
        for pattern in (r"<h1[^>]*>(.*?)</h1>", r"<title>(.*?)</title>"):
            match = re.search(pattern, html, re.I | re.S)
            if match:
                title = self._clean_text(
                    re.sub(r"<[^>]+>", " ", unescape(match.group(1)))
                )
                if title:
                    return title
        return ""

    def _extract_title_from_pdf_text(self, text: str) -> str:
        cleaned = self._clean_text(text)
        if not cleaned:
            return ""
        chunks = re.split(r"[。.!?]", cleaned, maxsplit=1)
        title = chunks[0].strip()
        return title[:120]

    def _extract_institution_name(self, text: str) -> str:
        patterns = [
            r"公司名称[:：]?\s*(.*?公司)(?:\s|统一社会信用代码|法定代表人|处罚事由|主要违法违规行为)",
            r"当事人名称[:：]?\s*(.*?)(?:主要违法违规行为|违法违规事实|行政处罚内容)",
            r"机构名称[:：]?\s*(.*?)(?:主要违法违规行为|违法违规事实|行政处罚内容)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.S)
            if match:
                candidate = self._clean_text(match.group(1))
                if candidate:
                    return candidate
        return "Not disclosed in source article"

    def _contains_keyword(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in (text or "") for keyword in keywords)

    def _matched_keywords(self, text: str, keywords: list[str]) -> list[str]:
        return [keyword for keyword in keywords if keyword in (text or "")]

    def _is_materially_relevant(self, title: str, summary: str, body_text: str, keywords: list[str]) -> bool:
        title_text = title or ""
        summary_text = summary or ""
        body = body_text or ""
        matched = self._matched_keywords(" ".join([title_text, summary_text, body]), keywords)
        if not matched:
            return False
        if any(keyword in title_text for keyword in matched):
            return True
        if any(keyword in summary_text for keyword in matched):
            return True
        if any(keyword in title_text for keyword in self.CORE_SCOPE_KEYWORDS):
            return True
        if any(keyword in summary_text for keyword in self.CORE_SCOPE_KEYWORDS):
            return True
        body_hits = self._count_distinct_keyword_mentions(body, matched)
        return body_hits >= 2

    def _count_distinct_keyword_mentions(self, text: str, keywords: list[str]) -> int:
        spans: list[tuple[int, int]] = []
        for keyword in sorted(set(keywords), key=len, reverse=True):
            start = 0
            while True:
                index = text.find(keyword, start)
                if index < 0:
                    break
                end = index + len(keyword)
                if not any(index < span_end and end > span_start for span_start, span_end in spans):
                    spans.append((index, end))
                start = index + 1
        return len(spans)

    def _scope_relevance_score(self, article: dict, keywords: list[str]) -> int:
        title = article.get("title", "") or ""
        summary = article.get("summary", "") or ""
        body = article.get("body_text", "") or ""
        score = 0

        title_matches = self._matched_keywords(title, keywords)
        summary_matches = self._matched_keywords(summary, keywords)
        body_hits = self._count_distinct_keyword_mentions(body, keywords)

        score += len(title_matches) * 100
        score += len(summary_matches) * 60
        score += min(body_hits, 5) * 10

        if any(keyword in title for keyword in self.CORE_SCOPE_KEYWORDS):
            score += 80
        if any(keyword in summary for keyword in self.CORE_SCOPE_KEYWORDS):
            score += 40

        title_text = f"{title} {summary}"
        if any(marker in title_text for marker in ["处罚", "罚款", "整改", "监管", "检查", "通知", "公告"]):
            score += 15
        if "办法" in title_text:
            score += 5
        if article.get("extractor") == "nfra_pdf":
            score += 30
        if article.get("published_at"):
            score += 5

        broad_penalties = [
            "目 录",
            "监管费",
            "许可证管理",
            "行政许可",
            "银行业监督管理法",
            "中华人民共和国",
        ]
        if any(marker in title for marker in broad_penalties):
            score -= 120
        if any(marker in summary for marker in ["基础性法律", "适用于银行保险机构", "全行业", "年度监管费"]):
            score -= 60

        return score

    def _rank_articles_by_scope_relevance(self, articles: list[dict], keywords: list[str]) -> list[dict]:
        return sorted(
            articles,
            key=lambda article: (
                self._scope_relevance_score(article, keywords),
                article.get("published_at", ""),
            ),
            reverse=True,
        )

    def _expand_keywords(self, keywords: list[str]) -> list[str]:
        expanded: list[str] = []
        for keyword in keywords:
            variants = self.KEYWORD_EQUIVALENTS.get(keyword, [keyword])
            for variant in variants:
                if variant not in expanded:
                    expanded.append(variant)
        return expanded

    def _clean_text(self, text: str) -> str:
        normalized = unescape(text or "")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _looks_like_article_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        normalized = url.lower()
        bad_patterns = ["/index.html", "javascript:", "void(0)"]
        if any(pattern in normalized for pattern in bad_patterns):
            return False
        article_signals = [
            "/art/",
            "/detail/",
            "itemdetail",
            "docid=",
            ".shtml",
            ".html",
            ".pdf",
        ]
        return any(signal in normalized for signal in article_signals)

    def _bing_search_url(self, query: str) -> str:
        from urllib.parse import quote_plus

        return f"https://www.bing.com/search?q={quote_plus(query)}"

    def _duckduckgo_search_url(self, query: str) -> str:
        from urllib.parse import quote_plus

        return f"https://duckduckgo.com/html/?q={quote_plus(query)}"
