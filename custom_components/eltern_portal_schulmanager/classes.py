"""Erkennen, ob ein Termin die Klasse des Kindes betrifft.

Viele Schulen tragen im Eltern-Portal Termine aller Klassen ein, z. B.
„Schullandheim 5b+5c“, „Zammgrauft Projekt 8A“, „Grundwissenstest Chemie Jgst. 10“
oder „Wissenschaftswoche 11. Klassen“. Eigene Termine tragen oft Kurscodes wie
„9_F_9D_FH“ oder „9_Ev_9ABCDEF_Joc“.

``concerns_class`` liefert ``True`` (betrifft die Klasse), ``False`` (nennt nur
andere Klassen/Jahrgangsstufen) oder ``None`` (nennt keine Klasse – im Zweifel
anzeigen).
"""

from __future__ import annotations

import re

_RE_HTML = re.compile(r"<[^>]+>")
_RE_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b(?:\s*Uhr)?")
_RE_DATE = re.compile(r"\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?")
# Klassen wie 5b, 8A, 9ABCDEF (in Kurscodes), 10c – nicht „3D-Druck“
_RE_CLASS = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})\s?([A-Fa-f]{1,6})(?![A-Za-z0-9-])")
# Bereiche: „Klassen 6 bis 11“, „Jgst. 5-7“, „6-13“, „5.-7. Klasse“
_RE_RANGE = re.compile(r"(?<![\d.])(\d{1,2})\.?\s*(?:-|–|bis)\s*(\d{1,2})(?![\d])")
# Einzelne Stufen: „Jgst. 10“, „Jahrgangsstufe 6“, „Jgst. 11 und 12“, „Klasse 7“
_RE_GRADE_WORD = re.compile(
    r"(?:Jgst\.?|Jahrgangsstufen?|Jahrgang|Klassenstufen?|Klassen?)\s*"
    r"(\d{1,2}(?:\s*(?:,|und|\+|/|&)\s*\d{1,2})*)(?![\d.]*\s*(?:-|–|bis))",
    re.I,
)
# „5. Klassen“, „(6. Klassen)“, „11. Klasse“
_RE_GRADE_ORD = re.compile(r"(?<![\d.])(\d{1,2})\.\s*Klass", re.I)
_RE_CLASSNAME = re.compile(r"(\d{1,2})\s*([A-Za-z]?)")

_MIN_GRADE, _MAX_GRADE = 1, 13


def _own(classname: str | None) -> tuple[int, str] | None:
    if not classname:
        return None
    m = _RE_CLASSNAME.search(classname)
    if not m:
        return None
    return int(m[1]), m[2].lower()


def concerns_class(text: str | None, classname: str | None) -> bool | None:
    """Betrifft ``text`` die Klasse ``classname`` (z. B. „9D“)?"""
    own = _own(classname)
    if not own or not text:
        return None
    grade, letter = own
    clean = _RE_HTML.sub(" ", text)
    clean = _RE_TIME.sub(" ", clean)
    clean = _RE_DATE.sub(" ", clean)

    mentioned = False
    for m in _RE_CLASS.finditer(clean):
        g = int(m[1])
        if not _MIN_GRADE <= g <= _MAX_GRADE:
            continue
        mentioned = True
        if g == grade and (not letter or letter in m[2].lower()):
            return True
    for m in _RE_RANGE.finditer(clean):
        a, b = int(m[1]), int(m[2])
        if not (_MIN_GRADE <= a < b <= _MAX_GRADE):
            continue
        mentioned = True
        if a <= grade <= b:
            return True
    for m in _RE_GRADE_WORD.finditer(clean):
        for g in (int(x) for x in re.findall(r"\d{1,2}", m[1])):
            if _MIN_GRADE <= g <= _MAX_GRADE:
                mentioned = True
                if g == grade:
                    return True
    for m in _RE_GRADE_ORD.finditer(clean):
        g = int(m[1])
        if _MIN_GRADE <= g <= _MAX_GRADE:
            mentioned = True
            if g == grade:
                return True
    return False if mentioned else None
