from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_state(events: list[dict], sources: list[dict], models: dict) -> dict:
    return {
        "initialized_at": utc_now_iso(),
        "events": deepcopy(events),
        "sources": deepcopy(sources),
        "models": deepcopy(models),
    }
