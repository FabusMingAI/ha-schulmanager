"""Convert WebUntis calendar events into Schulmanager substitution records.

The WebUntis calendar integration exposes structured JSON in the description.
Only actual changes are returned; a missing current teacher alone is ambiguous.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def _names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        str(item.get("name") or item.get("long_name"))
        for item in value
        if isinstance(item, dict) and (item.get("name") or item.get("long_name"))
    ]


def webuntis_payload(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Recognize structured WebUntis descriptions, including ordinary lessons."""
    description = event.get("description")
    if not isinstance(description, str):
        return None
    try:
        data = json.loads(description)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not any(
        key in data for key in ("subjects", "teachers", "original_teachers", "rooms", "code")
    ):
        return None
    return data


def parse_webuntis_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a normalized substitution or None for ordinary/ambiguous lessons.

    Expected input: one event from Home Assistant calendar.get_events.
    """
    data = webuntis_payload(event)
    if data is None:
        return None

    summary = str(event.get("summary") or "")
    code = str(data.get("code") or "").lower()
    cancelled = code in {"cancelled", "canceled"} or summary.lower().startswith("cancelled:")
    rooms = _names(data.get("rooms"))
    original_rooms = _names(data.get("original_rooms"))
    teachers = _names(data.get("teachers"))
    original_teachers = _names(data.get("original_teachers"))
    room_changed = bool(original_rooms and rooms and set(rooms) != set(original_rooms))
    teacher_changed = bool(original_teachers and teachers and set(teachers) != set(original_teachers))

    # WebUntis sometimes omits teachers entirely while retaining original_teachers.
    # This is not sufficient evidence of cancellation or substitution.
    if not (cancelled or room_changed or teacher_changed):
        return None

    kind = "entfall" if cancelled else "vertretung" if teacher_changed else "raum"
    subjects = _names(data.get("subjects"))
    return {
        "uid": f"webuntis:{data.get('id') or event.get('start', '')}",
        "kind": kind,
        "start": event.get("start") or data.get("start"),
        "end": event.get("end") or data.get("end"),
        "summary": subjects[0] if subjects else str(data.get("name") or summary),
        "room": ", ".join(rooms),
        "original_room": ", ".join(original_rooms),
        "teacher": ", ".join(teachers),
        "original_teacher": ", ".join(original_teachers),
        "description": str(data.get("substText") or data.get("info") or ""),
        "source": "webuntis",
    }


def parse_webuntis_events(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Extract changed lessons from a calendar event list."""
    return [
        parsed for event in events
        if isinstance(event, Mapping) and (parsed := parse_webuntis_event(event)) is not None
    ]
