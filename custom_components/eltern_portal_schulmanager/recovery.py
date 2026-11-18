"""Reversible quarantine of historical inbox imports made by v0.15.0."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

BAD_RELEASE_AT = datetime(2026, 11, 18, 9, 35, 17, tzinfo=timezone.utc)


def quarantine_archive_imports(data: dict[str, Any], lookback_days: int) -> int:
    """Keep original records, tasks and user edits in a recoverable journal.

    Only records first created after the affected release and outside the normal
    portal lookback qualify. Pre-existing records and manually maintained tasks
    are never inferred to be unwanted from their age alone.
    """
    journal = data.setdefault("schedule_recovery", {"items": {}, "tasks": {}})
    if journal.get("version") == 1:
        return 0
    sources = data.setdefault("schedule_sources", {})
    moved = 0
    for uid, item in list(data["items"].items()):
        try:
            created = datetime.fromisoformat(item.get("created") or "")
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            sent = datetime.fromisoformat(item.get("sent") or "").date()
        except ValueError:
            continue
        if created < BAD_RELEASE_AT or sent >= created.date() - timedelta(days=lookback_days):
            continue
        journal["items"].setdefault(uid, deepcopy(item))
        sources.setdefault(uid, {**item, "notify": False, "schedule_only": True})
        del data["items"][uid]
        moved += 1
        for tid, task in list(data["tasks"].items()):
            if task.get("item_uid") != uid or task.get("source") not in ("ki", "regeln", "portal"):
                continue
            # Preserve explicit user work even on an accidentally imported task.
            if task.get("status") != "offen" or task.get("comment"):
                continue
            journal["tasks"].setdefault(tid, deepcopy(task))
            del data["tasks"][tid]
    journal["version"] = 1
    return moved
