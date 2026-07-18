from __future__ import annotations


def build_event_quality(
    *,
    article_url: str,
    title: str,
    institution_name: str,
    llm_completed: bool = False,
) -> dict:
    subject_present = bool(
        institution_name and institution_name != "Not disclosed in source article"
    )
    source_verified = bool(article_url and article_url.startswith(("http://", "https://")))
    article_opened = bool(title)
    if source_verified and article_opened and subject_present:
        confidence = "high"
    elif source_verified and article_opened:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "source_link_verified": source_verified,
        "article_opened": article_opened,
        "original_subject_extracted": subject_present,
        "llm_analysis_completed": llm_completed,
        "extraction_confidence": confidence,
    }
