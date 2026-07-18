from __future__ import annotations

from collections import Counter
from datetime import datetime

CATEGORY_LABELS = {
    "业务合规": "Business Compliance",
    "信息披露": "Information Disclosure",
    "监管处罚": "Regulatory Penalty",
    "监管动态": "Regulatory Update",
    "公司治理": "Corporate Governance",
    "关联交易": "Related-Party Governance",
    "风险管理": "Risk Management",
    "信用风险": "Credit Risk",
}

REASON_RULES = [
    (
        "Asset Authenticity and Penetration Review",
        ("真实性", "穿透", "租赁物", "核验", "底层资产"),
    ),
    (
        "Disclosure and Reporting Discipline",
        ("披露", "报送", "公告", "信息更新"),
    ),
    (
        "Related-Party Governance",
        ("关联交易", "关联方"),
    ),
    (
        "External Credit Deterioration",
        ("信用", "执行", "异常"),
    ),
    (
        "Rectification and Penalty Escalation",
        ("处罚", "罚", "整改", "监管措施"),
    ),
]


def localize_category(label: str) -> str:
    return CATEGORY_LABELS.get(label, label)


def build_summary(events: list[dict], sources: list[dict]) -> dict:
    region_counter = Counter(event["region"] for event in events)
    category_counter = Counter(event["category"] for event in events)
    return {
        "total_events": len(events),
        "major_events": sum(1 for event in events if event["severity"] == "major"),
        "pending_reviews": sum(
            1 for event in events if event["review_status"] == "pending"
        ),
        "active_sources": sum(1 for source in sources if source["status"] == "active"),
        "top_region": region_counter.most_common(1)[0][0] if region_counter else "N/A",
        "top_category": (
            localize_category(category_counter.most_common(1)[0][0]) if category_counter else "N/A"
        ),
    }


def build_charts(events: list[dict]) -> dict:
    week_counter: Counter[str] = Counter()
    region_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()

    for event in events:
        week_key = datetime.fromisoformat(event["published_at"]).strftime("%Y-W%W")
        week_counter[week_key] += 1
        region_counter[event["region"]] += 1
        category_counter[event["category"]] += 1

    return {
        "events_by_week": [
            {"label": label, "value": value}
            for label, value in sorted(week_counter.items())
        ],
        "events_by_region": [
            {"label": label, "value": value}
            for label, value in region_counter.most_common()
        ],
        "top_categories": [
            {"label": localize_category(label), "value": value}
            for label, value in category_counter.most_common(5)
        ],
    }


def classify_reason(event: dict) -> str:
    text = " ".join(
        [
            event.get("title", ""),
            event.get("summary", ""),
            event.get("risk_hint", ""),
            event.get("category", ""),
        ]
    )
    for label, keywords in REASON_RULES:
        if any(keyword in text for keyword in keywords):
            return label
    return "General Conduct and Control Weakness"


def build_management_dashboard(events: list[dict], trend_window: dict | None = None) -> dict:
    if not events:
        return {
            "headline": "No enforcement events available yet.",
            "trend_window_label": (trend_window or {}).get("label", "No source-backed trend window available yet"),
            "top_penalty_reasons": [],
            "penalty_intelligence": [],
            "early_warning": {
                "headline": "No early warning available yet.",
                "summary": "Load events or update sources to generate management-facing compliance warnings.",
                "control_domains": [],
                "management_actions": [],
                "actions": [],
                "supporting_events": [],
            },
        }

    analyzed_events = [
        event for event in events if event.get("analysis_summary") or event.get("penalty_focus")
    ] or events
    penalty_events = [
        event
        for event in analyzed_events
        if event.get("is_penalty_event")
        or event.get("severity") == "major"
        or "处罚" in event.get("title", "")
        or "罚" in event.get("summary", "")
    ]
    focus_events = penalty_events or analyzed_events
    reason_counter: Counter[str] = Counter()

    for event in focus_events:
        reason_counter[classify_reason(event)] += 1

    top_reasons = [
        {
            "reason": reason,
            "count": count,
            "share": round((count / max(len(focus_events), 1)) * 100, 1),
        }
        for reason, count in reason_counter.most_common(3)
    ]

    primary_reason = top_reasons[0]["reason"] if top_reasons else "General Conduct and Control Weakness"
    support_events = sorted(
        focus_events,
        key=lambda item: (item.get("severity") != "major", item.get("published_at", "")),
        reverse=True,
    )[:3]

    early_warning = {
        "headline": "Regulatory signals point to immediate control review priorities.",
        "summary": (
            f"Recent public cases suggest regulators are concentrating on {primary_reason.lower()}. "
            "For Siemens Financial Leasing and Siemens Commercial Factoring, the immediate management "
            "question is whether similar control gaps could exist in asset onboarding, regulatory reporting, "
            "or affiliate oversight before they become a formal enforcement issue."
        ),
        "control_domains": [
            "Asset Authenticity and Penetration Review",
            "Disclosure and Reporting Discipline",
            "Related-Party Governance",
        ],
        "management_actions": [
            "Run a targeted control check on lease/factoring transactions that depend on underlying asset authenticity, document completeness, and penetration review.",
            "Reconfirm disclosure and regulatory reporting timeliness for local filings, public notices, and exception escalation routines.",
            "Review related-party approval, conflict checks, and management reporting for transactions involving group or connected counterparties.",
        ],
        "actions": [
            "Run a targeted control check on lease/factoring transactions that depend on underlying asset authenticity, document completeness, and penetration review.",
            "Reconfirm disclosure and regulatory reporting timeliness for local filings, public notices, and exception escalation routines.",
            "Review related-party approval, conflict checks, and management reporting for transactions involving group or connected counterparties.",
        ],
        "supporting_events": [
            {
                "title": event.get("title", "Untitled signal"),
                "reason": classify_reason(event),
                "analysis_summary": event.get("analysis_summary") or event.get("risk_hint", ""),
                "source_url": ((event.get("sources") or [{}])[0]).get("url", ""),
                "published_at": event.get("published_at", ""),
            }
            for event in support_events
        ],
    }

    return {
        "headline": "Management Early Warning for Siemens Financial Leasing and Commercial Factoring",
        "trend_window_label": (trend_window or {}).get("label", "Trend window unavailable"),
        "top_penalty_reasons": top_reasons,
        "penalty_intelligence": [
            {
                "label": "Analyzed Articles",
                "value": len(analyzed_events),
            },
            {
                "label": "Penalty-Focused Articles",
                "value": len(penalty_events),
            },
            {
                "label": "Primary Penalty Theme",
                "value": primary_reason,
            },
        ],
        "early_warning": early_warning,
    }
