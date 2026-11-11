"""Privacy-preserving diagnostics: counts and fixed status codes only."""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from . import SchulConfigEntry
from .const import CONF_PORTALS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SchulConfigEntry
) -> dict[str, Any]:
    """Use an allowlist; free-text server errors can contain personal data.

    Never export entry data/options, school identifiers, children, message
    content, tasks, files, teacher lists, links or AI summaries.
    """
    manager = entry.runtime_data
    health = Counter(manager.portal_status.values())
    return {
        "portals": {
            "configured": len(entry.data.get(CONF_PORTALS, [])),
            "not_checked": sum(
                p["school"] not in manager.portal_status
                for p in entry.data.get(CONF_PORTALS, [])
            ),
            **{status: health[status] for status in ("ok", "partial", "auth_failed", "connection_failed")},
        },
        "last_fetch": manager.last_update.isoformat() if manager.last_update else None,
        "error_count": len(manager.last_errors),
        "stored": {
            key: len(manager.data.get(key, {}))
            for key in ("children", "items", "tasks", "events", "timetable", "substitutions", "sicknotes")
        },
        "pending_analysis": len(manager._pending()),
        "pending_translations": len(manager._missing_translations()),
    }
