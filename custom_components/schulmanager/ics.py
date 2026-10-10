"""Einzelne Termine als iCalendar-Datei (.ics, RFC 5545) und Google-Kalender-Link (#12).

Die Funktionen arbeiten auf den normalisierten Einträgen aus
``SchulManager.child_events()``: ``start``/``end`` sind entweder ``date``
(ganztägig, ``end`` exklusiv) oder zeitzonenbehaftete ``datetime``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

PRODID = "-//FabusMingAI//Schulmanager for Home Assistant//DE"
GOOGLE_URL = "https://calendar.google.com/calendar/render"
MAX_GOOGLE_DETAILS = 1500


def _escape(text: str) -> str:
    """TEXT-Wert nach RFC 5545 §3.3.11 maskieren."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Zeilen nach 75 Oktetten umbrechen, ohne UTF-8-Zeichen zu zerteilen."""
    out: list[str] = []
    current = ""
    size = 0
    limit = 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(current)
            current = " " + ch
            size = 1 + n
            limit = 75
        else:
            current += ch
            size += n
    out.append(current)
    return "\r\n".join(out)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _day(value: date) -> str:
    return value.strftime("%Y%m%d")


def _is_timed(ev: dict[str, Any]) -> bool:
    return isinstance(ev["start"], datetime)


def event_summary(ev: dict[str, Any], child_name: str | None) -> str:
    summary = ev.get("summary") or ev.get("title") or "Termin"
    return f"{child_name}: {summary}" if child_name else summary


def event_details(ev: dict[str, Any], portal_url: str | None = None) -> str:
    """Beschreibung aus Kurzbeschreibung und Kalendertext, ohne Wiederholungen."""
    lines: list[str] = []
    for part in (ev.get("hover"), ev.get("description")):
        part = (part or "").strip()
        if part and part not in "\n\n".join(lines):
            lines.append(part)
    if portal_url and portal_url not in "\n".join(lines):
        lines.append(f"Eltern-Portal: {portal_url}")
    return "\n\n".join(lines)


def event_uid(child: str, uid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{child}-{uid}").strip("-")
    return f"{safe}@schulmanager"


def build_ics(
    ev: dict[str, Any],
    child: str,
    child_name: str | None,
    portal_url: str | None = None,
    now: datetime | None = None,
) -> str:
    """Eine Kalenderdatei mit genau einem VEVENT.

    Die UID ist stabil (Kind + Termin-ID): erneutes Eintragen aktualisiert den
    vorhandenen Termin statt ein Duplikat anzulegen.
    """
    now = now or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event_uid(child, ev['uid'])}",
        f"DTSTAMP:{_utc(now)}",
    ]
    if _is_timed(ev):
        lines.append(f"DTSTART:{_utc(ev['start'])}")
        lines.append(f"DTEND:{_utc(ev['end'])}")
    else:
        end = ev.get("end") or ev["start"] + timedelta(days=1)
        lines.append(f"DTSTART;VALUE=DATE:{_day(ev['start'])}")
        lines.append(f"DTEND;VALUE=DATE:{_day(end)}")
        lines.append("TRANSP:TRANSPARENT")
    lines.append(f"SUMMARY:{_escape(event_summary(ev, child_name))}")
    details = event_details(ev, portal_url)
    if details:
        lines.append(f"DESCRIPTION:{_escape(details)}")
    if ev.get("location"):
        lines.append(f"LOCATION:{_escape(str(ev['location']))}")
    if portal_url:
        lines.append(f"URL:{portal_url}")
    if ev.get("category"):
        lines.append(f"CATEGORIES:{_escape('Schule')},{_escape(str(ev['category']))}")
    # Erinnerung: ganztägig am Vortag um 18 Uhr, mit Uhrzeit eine Stunde vorher
    lines += [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(event_summary(ev, child_name))}",
        f"TRIGGER:{'-PT1H' if _is_timed(ev) else '-PT6H'}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def google_url(
    ev: dict[str, Any],
    child_name: str | None,
    time_zone: str,
    portal_url: str | None = None,
) -> str:
    """Link „In Google Kalender öffnen“ (Fallback für Android)."""
    if _is_timed(ev):
        tz = ZoneInfo(time_zone)
        fmt = "%Y%m%dT%H%M%S"
        dates = f"{ev['start'].astimezone(tz).strftime(fmt)}/{ev['end'].astimezone(tz).strftime(fmt)}"
    else:
        end = ev.get("end") or ev["start"] + timedelta(days=1)
        dates = f"{_day(ev['start'])}/{_day(end)}"
    params = {
        "action": "TEMPLATE",
        "text": event_summary(ev, child_name),
        "dates": dates,
        "ctz": time_zone,
    }
    details = event_details(ev, portal_url)
    if details:
        params["details"] = details[:MAX_GOOGLE_DETAILS]
    if ev.get("location"):
        params["location"] = str(ev["location"])
    return f"{GOOGLE_URL}?{urlencode(params)}"


def ics_filename(ev: dict[str, Any]) -> str:
    start = ev["start"]
    day = (start.date() if isinstance(start, datetime) else start).isoformat()
    title = re.sub(r'[\\/:*?"<>|\n\r\t]+', " ", ev.get("title") or "Termin").strip()
    return f"{day} {title[:60]}.ics"
