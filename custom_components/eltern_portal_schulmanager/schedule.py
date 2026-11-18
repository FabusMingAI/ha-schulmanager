"""Validated message appointments and durable timetable identities."""
from __future__ import annotations

from datetime import date, time, timedelta
import hashlib
import re
from typing import Any

from .classes import concerns_class

SCHEDULE_VERSION = 1
HOLIDAY_SOURCE = "https://www.gesetze-bayern.de/Content/Document/BayVV_2230_1_1_0_K_13479/true"
# Inclusive dates, Bayerisches Ministerialblatt 2022 Nr. 747.
HOLIDAYS = (
    ("Sommerferien", "2024-07-29", "2024-09-09"),
    ("Herbstferien", "2024-10-28", "2024-10-31"),
    ("Weihnachtsferien", "2024-12-23", "2025-01-03"),
    ("Frühjahrsferien", "2025-03-03", "2025-03-07"),
    ("Osterferien", "2025-04-14", "2025-04-25"),
    ("Pfingstferien", "2025-06-10", "2025-06-20"),
    ("Sommerferien", "2025-08-01", "2025-09-15"),
    ("Herbstferien", "2025-11-03", "2025-11-07"),
    ("Weihnachtsferien", "2025-12-22", "2026-01-05"),
    ("Frühjahrsferien", "2026-02-16", "2026-02-20"),
    ("Osterferien", "2026-03-30", "2026-04-10"),
    ("Pfingstferien", "2026-05-26", "2026-06-05"),
    ("Sommerferien", "2026-08-03", "2026-09-14"),
    ("Herbstferien", "2026-11-02", "2026-11-06"),
    ("Weihnachtsferien", "2026-12-24", "2027-01-08"),
    ("Frühjahrsferien", "2027-02-08", "2027-02-12"),
    ("Osterferien", "2027-03-22", "2027-04-02"),
    ("Pfingstferien", "2027-05-18", "2027-05-28"),
    ("Sommerferien", "2027-08-02", "2027-09-13"),
    ("Herbstferien", "2027-11-02", "2027-11-05"),
    ("Weihnachtsferien", "2027-12-24", "2028-01-07"),
    ("Frühjahrsferien", "2028-02-28", "2028-03-03"),
    ("Osterferien", "2028-04-10", "2028-04-21"),
    ("Pfingstferien", "2028-06-06", "2028-06-16"),
    ("Sommerferien", "2028-07-31", "2028-09-11"),
    ("Herbstferien", "2028-10-30", "2028-11-03"),
    ("Weihnachtsferien", "2028-12-23", "2029-01-05"),
    ("Frühjahrsferien", "2029-02-12", "2029-02-16"),
    ("Osterferien", "2029-03-26", "2029-04-06"),
    ("Pfingstferien", "2029-05-22", "2029-06-01"),
    ("Sommerferien", "2029-07-30", "2029-09-10"),
    ("Herbstferien", "2029-10-29", "2029-11-02"),
    ("Weihnachtsferien", "2029-12-24", "2030-01-04"),
    ("Frühjahrsferien", "2030-03-04", "2030-03-08"),
    ("Osterferien", "2030-04-15", "2030-04-26"),
    ("Pfingstferien", "2030-06-11", "2030-06-21"),
    ("Sommerferien", "2030-07-29", "2030-09-09"),
)


def clock(value: Any) -> str | None:
    """Accept only real local clock times."""
    try:
        return time.fromisoformat(str(value).strip().zfill(5)).strftime("%H:%M")
    except ValueError:
        return None


def identity(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p).strip().casefold() for p in parts).encode()).hexdigest()[:20]


def lesson_uid(lesson: dict[str, Any]) -> str:
    return "lesson-" + identity(lesson.get("weekday"), lesson.get("lesson"), lesson.get("subject"))


def holiday_entries() -> list[dict[str, Any]]:
    return [{"uid": f"holiday-by-{start}", "title": title, "date": start, "end": end,
             "kind": "holiday", "source_url": HOLIDAY_SOURCE, "status": "confirmed"}
            for title, start, end in HOLIDAYS]


def message_entries(events: list[dict[str, Any]], items: dict[str, Any], classname: str) -> list[dict[str, Any]]:
    """Group exact duplicates while retaining every message source."""
    grouped: dict[tuple, dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: items.get(e.get("item_uid"), {}).get("sent") or ""):
        item = items.get(event.get("item_uid"), {})
        if concerns_class(event.get("audience") or event.get("title"), classname) is False:
            continue
        key = tuple(str(event.get(k) or "").strip().casefold() for k in
                    ("title", "date", "time", "time_end", "end", "weekday", "repeat_until"))
        source = {"item_uid": item.get("uid"), "title": item.get("title"), "url": item.get("url"), "sent": item.get("sent")}
        if key not in grouped:
            grouped[key] = {**event, "kind": "message", "sources": [], "aliases": [], "choice_key": "event-" + identity(*key)}
        grouped[key]["sources"].append(source)
        grouped[key]["aliases"].append(event["uid"])
        grouped[key]["status"] = event.get("status", "confirmed")
    # An explicit cancellation applies even if its message omits the clock time.
    cancelled = {(str(e["title"]).casefold(), e["date"]) for e in grouped.values()
                 if e.get("status") == "cancelled"}
    cancelled.update((str(e["title"]).casefold(), e["replaces_date"]) for e in grouped.values()
                     if e.get("status") == "confirmed" and e.get("replaces_date"))
    for event in grouped.values():
        if (str(event["title"]).casefold(), event["date"]) in cancelled:
            event["status"] = "cancelled"
    return list(grouped.values())


def occurrences(event: dict[str, Any]) -> list[date]:
    """Bound explicitly dated weekly series to at most one school year."""
    start = date.fromisoformat(event["date"])
    weekday, until = event.get("weekday"), event.get("repeat_until")
    if not weekday or not until:
        return [start]
    end = min(date.fromisoformat(until), start + timedelta(days=366))
    first = start + timedelta(days=(weekday - start.isoweekday()) % 7)
    return [first + timedelta(days=n) for n in range(0, (end - first).days + 1, 7)]


def in_holidays(day: date) -> bool:
    return any(start <= day.isoformat() <= end for _, start, end in HOLIDAYS)


def rule_events(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Conservative dated suggestions when no AI provider is available."""
    text = re.sub(r"<[^>]*>", "\n", ctx.get("body") or "")
    sent = ctx.get("sent_date")
    out = []
    for line in text.splitlines():
        if not re.search(r"ausflug|elternabend|kurs|prüfung|schulaufgabe|veranstaltung|wandertag|konzert|training", line, re.I):
            continue
        for match in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?", line):
            if not match[3] and not sent:
                continue
            try:
                year = int(match[3]) if match[3] else sent.year
                day = date(year, int(match[2]), int(match[1]))
                if not match[3] and (day - sent).days < -120:
                    day = day.replace(year=year + 1)
            except ValueError:
                continue
            times = re.findall(r"\b\d{1,2}:\d{2}\b", line)
            out.append({"title": (ctx.get("title") or line)[:200], "date": day.isoformat(),
                        "time": clock(times[0]) if times else None,
                        "time_end": clock(times[1]) if len(times) > 1 else None,
                        "end": None, "location": None, "status": "proposed", "details": line[:600]})
    return out
