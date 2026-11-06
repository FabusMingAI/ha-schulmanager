"""Evidence-based course teachers; no inference from a message's sender."""
from __future__ import annotations

from datetime import date
import html
import re
from typing import Any

import bs4

_COURSE = re.compile(r"\bInt_([A-Za-zÄÖÜäöü]+)_(\d{1,2}[a-fA-F]{1,6})\b")
_SLOT = re.compile(r"\b(Mo|Di|Mi|Do|Fr)\s+(\d{1,2})\.?\s*Std\.?", re.I)
_CODE = re.compile(r"\b([A-ZÄÖÜ]{2,5})\s+\d+\b")
_DAYS = {"mo": 1, "di": 2, "mi": 3, "do": 4, "fr": 5}


def parse_course_registrations(html: str, parser: str = "html.parser") -> list[str] | None:
    """None means unavailable/unrecognized, [] means explicitly no registrations."""
    soup = bs4.BeautifulSoup(html, parser)
    heading = soup.find("h2")
    if not heading or "Voranmeldung Intensivierungskurse" not in heading.get_text(" ", strip=True):
        return None
    text = soup.get_text(" ", strip=True)
    courses = [h.get_text(" ", strip=True) for h in soup.select("h4.link_buchungen")]
    if "Für folgende Intensivierungskurse besteht eine Anmeldung" in text and courses:
        return list(dict.fromkeys(courses))
    if soup.find("form"):
        return None
    if re.search(r"(?:keine Anmeldungen|keine Anmeldung|nicht angemeldet|keine Intensivierungskurse)", text, re.I):
        return []
    return None  # An open booking form is not a complete participation list.


def course_evidence(items: list[dict[str, Any]], classname: str, teachers: dict[str, str], today: date) -> list[dict[str, Any]]:
    """Recognize explicit class/course + weekday/period + teacher-code table rows."""
    year = today.year if today.month >= 8 else today.year - 1
    own = re.fullmatch(r"(\d{1,2})([a-f])", classname.strip(), re.I)
    if not own:
        return []
    out = []
    for item in items:
        text = re.sub(r"<[^>]+>", " ", html.unescape(item.get("body") or ""))
        text = " ".join((item.get("title") or "", text, item.get("text") or ""))
        if not re.search(rf"\b{year}\s*/\s*(?:{year + 1}|{str(year + 1)[-2:]})\b", text):
            continue
        try:
            sent = date.fromisoformat((item.get("sent") or "")[:10])
        except ValueError:
            continue
        if not date(year, 8, 1) <= sent <= today:
            continue
        rows = list(_COURSE.finditer(text))
        for i, row in enumerate(rows):
            group = re.fullmatch(r"(\d{1,2})([a-f]+)", row[2], re.I)
            if not group or int(group[1]) != int(own[1]) or own[2].lower() not in group[2].lower():
                continue
            tail = text[row.end():rows[i + 1].start() if i + 1 < len(rows) else row.end() + 220]
            slot = _SLOT.search(tail[:160])
            code = _CODE.search(tail[slot.end():slot.end() + 100]) if slot else None
            if not slot or not code or code[1] not in teachers:
                continue
            out.append({
                "subject": row[1] + "Int", "weekday": _DAYS[slot[1].lower()],
                "lesson": str(int(slot[2])), "teacher": teachers[code[1]],
                "teacher_code": code[1], "course": row[0],
                "optional": bool(re.search(r"freiwillig\w*\s+Intensivierung", text, re.I)),
                "source": {"item_uid": item.get("uid"), "title": item.get("title"),
                           "url": item.get("url"), "sent": item.get("sent")},
            })
    return out


def enrich_timetable(lessons: list[dict[str, Any]], items: list[dict[str, Any]], classname: str,
                     teachers: dict[str, str], today: date, registrations: list[str] | None = None) -> list[dict[str, Any]]:
    """Return a derived view; retain raw lessons so expired evidence disappears."""
    evidence = course_evidence(items, classname, teachers, today)
    out = []
    for original in lessons:
        lesson = dict(original)
        matches = [e for e in evidence if (e["subject"], e["weekday"], e["lesson"]) ==
                   (lesson.get("subject"), lesson.get("weekday"), lesson.get("lesson"))]
        # Multiple contradictory documents do not produce an arbitrary assignment.
        if matches and len({(e["teacher"], e["course"]) for e in matches}) == 1:
            e = max(matches, key=lambda e: e["source"].get("sent") or "")
            if not lesson.get("teacher"):
                lesson.update(teacher=e["teacher"], teacher_code=e["teacher_code"], teacher_source=e["source"])
            lesson["course"] = e["course"]
            if e["optional"]:
                lesson["optional"] = True
                lesson["participation"] = "unknown" if registrations is None else (
                    "registered" if e["course"].casefold() in {c.casefold() for c in registrations} else "not_registered")
        out.append(lesson)
    return out
