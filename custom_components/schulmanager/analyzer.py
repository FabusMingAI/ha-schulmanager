"""Auswertung von Mitteilungen: Aufgaben, Fristen, Zahlungen, Termine.

Primär über die Home-Assistant-Aktion ``ai_task.generate_data`` (der in HA
eingerichtete KI-Dienst), ersatzweise über einfache Regeln.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DEFAULT_SUMMARY_LANGUAGES,
    LANGUAGE_PROMPT_NAMES,
    LOGGER,
    SUMMARY_LANGUAGES,
    TASK_TYPES,
)

MAX_TEXT = 14000

PROMPT = """Du bist der Schul-Assistent einer Familie. Werte die folgende Mitteilung \
aus dem Eltern-Portal der Schule aus und finde heraus, was die ELTERN tun müssen.

Heute ist {today} ({weekday}). Kind: {child} (Klasse {classname}), Schule: {school}.
Art: {kind}. Absender: {sender}. Datum der Mitteilung: {sent}.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format:
{{
  "zusammenfassung": "1-2 kurze Sätze auf {main_language}, was die Eltern wissen müssen",
  "zusammenfassungen": {{{summaries_format}}},
  "kategorie": "info | aktion | zahlung | termin | rueckmeldung | leistung | organisation",
  "dringlichkeit": "niedrig | mittel | hoch",
  "aufgaben": [
    {{
      "titel": "kurze Handlungsanweisung, z.B. 'Einverständniserklärung Wandertag unterschreiben'",
      "typ": "aufgabe | zahlung | rueckmeldung | unterschrift | mitbringen | termin",
      "faellig": "YYYY-MM-DD oder null",
      "betrag": 0.0 oder null,
      "empfaenger": "Zahlungsempfänger oder null",
      "iban": "IBAN oder null",
      "verwendungszweck": "Verwendungszweck oder null",
      "details": "wichtige Details (Wo? Wie? Was mitbringen?) oder leer"
    }}
  ],
  "termine": [
    {{"titel": "...", "datum": "YYYY-MM-DD", "uhrzeit": "HH:MM oder null", "ende": "YYYY-MM-DD oder null", "ort": "... oder null"}}
  ]
}}

Regeln:
- Nur echte Handlungen der Eltern als Aufgaben (zahlen, unterschreiben, zurückgeben, \
anmelden, antworten, etwas besorgen/mitgeben). Reine Informationen erzeugen keine Aufgabe.
- Jede Zahlung als eigene Aufgabe mit Typ "zahlung" und Betrag in Euro (Zahl).
- Fälligkeiten immer als absolutes Datum; Jahr aus dem Kontext ergänzen \
(Schuljahr läuft von September bis Juli).
- Veranstaltungen, Elternabende, Ausflüge, Schulaufgaben usw. als "termine".
- "zusammenfassungen" enthält dieselbe Zusammenfassung in jeder angegebenen Sprache \
(Sprachcode als Schlüssel), jeweils natürlich formuliert, nicht wörtlich übersetzt.
- Betrifft ein Termin oder eine Aufgabe ausdrücklich nur andere Klassen oder \
Jahrgangsstufen (nicht Klasse {classname}), lass ihn weg.
- Erfinde nichts. Wenn nichts zu tun ist, ist "aufgaben" eine leere Liste.

--- BETREFF ---
{title}

--- TEXT ---
{body}
"""

def fmt_eur(amount: float | None) -> str:
    """Betrag deutsch formatieren: 1234.5 -> '1.234,50 €'."""
    if amount is None:
        return ""
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _parse_date(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(value[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2) if value > 0 else None
    match = re.search(r"\d+(?:[.,]\d{1,2})?", str(value))
    if not match:
        return None
    amount = float(match[0].replace(",", "."))
    return round(amount, 2) if amount > 0 else None


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Keine JSON-Antwort")
    return json.loads(text[start : end + 1])


def summary_languages(value: Any) -> list[str]:
    """Gewählte Sprachen in fester Reihenfolge; ohne Auswahl Deutsch und Englisch."""
    chosen = [lang for lang in SUMMARY_LANGUAGES if lang in (value or [])]
    return chosen or list(DEFAULT_SUMMARY_LANGUAGES)


def normalize(raw: dict[str, Any], languages: list[str] | None = None) -> dict[str, Any]:
    """KI-Antwort in ein sauberes Format bringen."""
    languages = summary_languages(languages)
    tasks = []
    for t in raw.get("aufgaben") or []:
        if not isinstance(t, dict) or not t.get("titel"):
            continue
        typ = str(t.get("typ") or "aufgabe").lower().strip()
        typ = typ.replace("ü", "ue")
        if typ not in TASK_TYPES:
            typ = "aufgabe"
        amount = _parse_amount(t.get("betrag"))
        if amount and typ == "aufgabe":
            typ = "zahlung"
        tasks.append(
            {
                "title": str(t["titel"]).strip()[:200],
                "type": typ,
                "due": _parse_date(t.get("faellig")),
                "amount": amount,
                "payee": (t.get("empfaenger") or None),
                "iban": (str(t.get("iban")).replace(" ", "") if t.get("iban") else None),
                "reference": (t.get("verwendungszweck") or None),
                "details": (t.get("details") or "").strip() or None,
            }
        )
    events = []
    for e in raw.get("termine") or []:
        if not isinstance(e, dict) or not e.get("titel"):
            continue
        day = _parse_date(e.get("datum"))
        if not day:
            continue
        clock = e.get("uhrzeit")
        if not (isinstance(clock, str) and re.fullmatch(r"\d{1,2}:\d{2}", clock.strip())):
            clock = None
        events.append(
            {
                "title": str(e["titel"]).strip()[:200],
                "date": day,
                "time": clock.strip().zfill(5) if clock else None,
                "end": _parse_date(e.get("ende")),
                "location": e.get("ort") or None,
            }
        )
    urgency = str(raw.get("dringlichkeit") or "mittel").lower()
    if urgency not in ("niedrig", "mittel", "hoch"):
        urgency = "mittel"
    summaries: dict[str, str] = {}
    raw_summaries = raw.get("zusammenfassungen")
    if isinstance(raw_summaries, dict):
        for lang in languages:
            text = raw_summaries.get(lang)
            if isinstance(text, str) and text.strip():
                summaries[lang] = text.strip()[:600]
    summary = str(raw.get("zusammenfassung") or "").strip()[:600]
    if not summary and summaries:
        summary = summaries[next(iter(summaries))]
    if summary and languages[0] not in summaries:
        summaries = {languages[0]: summary, **summaries}
    return {
        "summary": summaries.get(languages[0]) or summary,
        "summaries": summaries,
        "category": str(raw.get("kategorie") or "info").lower(),
        "urgency": urgency,
        "tasks": tasks,
        "events": events,
    }


async def async_analyze_ai(
    hass: HomeAssistant,
    ai_entity: str,
    ctx: dict[str, Any],
    attachments: list[dict[str, str]] | None = None,
    languages: list[str] | None = None,
) -> dict[str, Any]:
    """Mitteilung mit dem KI-Dienst von Home Assistant auswerten."""
    languages = summary_languages(languages)
    today = date.today()
    body = ctx.get("body") or ""
    if len(body) > MAX_TEXT:
        body = body[:MAX_TEXT] + "\n[… gekürzt]"
    prompt = PROMPT.format(
        today=today.isoformat(),
        weekday=WEEKDAYS[today.weekday()],
        child=ctx.get("child") or "?",
        classname=ctx.get("classname") or "?",
        school=ctx.get("school") or "?",
        kind=ctx.get("kind") or "?",
        sender=ctx.get("sender") or "Schule",
        sent=ctx.get("sent") or "?",
        title=ctx.get("title") or "",
        body=body or "(Inhalt steht im angehängten Dokument)",
        main_language=LANGUAGE_PROMPT_NAMES[languages[0]],
        summaries_format=", ".join(
            f'"{lang}": "Zusammenfassung auf {LANGUAGE_PROMPT_NAMES[lang]}"' for lang in languages
        ),
    )
    data: dict[str, Any] = {
        "task_name": f"Schulmanager: {ctx.get('title', '')[:60]}",
        "instructions": prompt,
        "entity_id": ai_entity,
    }
    if attachments:
        data["attachments"] = attachments
    try:
        resp = await hass.services.async_call(
            "ai_task",
            "generate_data",
            data,
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError as err:
        raise AnalyzeError(f"KI-Dienst nicht erreichbar: {err}") from err
    result = (resp or {}).get("data")
    if isinstance(result, dict):
        raw = result
    else:
        try:
            raw = _extract_json(str(result or ""))
        except (ValueError, json.JSONDecodeError) as err:
            LOGGER.debug("Unverständliche KI-Antwort: %s", result)
            raise AnalyzeError(f"KI-Antwort nicht lesbar: {err}") from err
    return normalize(raw, languages)


class AnalyzeError(Exception):
    """Auswertung fehlgeschlagen."""


TRANSLATE_PROMPT = """Übersetze die folgende Zusammenfassung einer Mitteilung aus dem \
Eltern-Portal einer Schule (Sprache: {source}) in diese Sprachen: {targets}.
Formuliere natürlich und knapp, behalte Daten, Beträge und Namen unverändert bei \
und füge nichts hinzu.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt, Sprachcode als Schlüssel:
{{{fmt}}}

--- ZUSAMMENFASSUNG ---
{summary}
"""


async def async_translate_summary(
    hass: HomeAssistant,
    ai_entity: str,
    summary: str,
    source: str,
    targets: list[str],
) -> dict[str, str]:
    """Nur die Zusammenfassung übersetzen – Aufgaben und Termine bleiben unberührt."""
    targets = [t for t in targets if t in LANGUAGE_PROMPT_NAMES and t != source]
    if not targets or not summary:
        return {}
    prompt = TRANSLATE_PROMPT.format(
        source=LANGUAGE_PROMPT_NAMES.get(source, source),
        targets=", ".join(f"{LANGUAGE_PROMPT_NAMES[t]} ({t})" for t in targets),
        fmt=", ".join(f'"{t}": "…"' for t in targets),
        summary=summary,
    )
    try:
        resp = await hass.services.async_call(
            "ai_task",
            "generate_data",
            {"task_name": "Schulmanager: Übersetzung", "instructions": prompt, "entity_id": ai_entity},
            blocking=True,
            return_response=True,
        )
    except HomeAssistantError as err:
        raise AnalyzeError(f"KI-Dienst nicht erreichbar: {err}") from err
    result = (resp or {}).get("data")
    try:
        raw = result if isinstance(result, dict) else _extract_json(str(result or ""))
    except (ValueError, json.JSONDecodeError) as err:
        raise AnalyzeError(f"KI-Antwort nicht lesbar: {err}") from err
    return {
        t: raw[t].strip()[:600]
        for t in targets
        if isinstance(raw.get(t), str) and raw[t].strip()
    }


# ----------------------------------------------------------------------
# Regel-basierte Auswertung (ohne KI)
# ----------------------------------------------------------------------
_RE_AMOUNT = re.compile(r"(\d{1,4}(?:[.,]\d{2})?)\s*(?:€|EUR\b|Euro\b)", re.I)
_RE_DEADLINE = re.compile(
    r"(?:bis\s+(?:spätestens\s+)?(?:zum\s+|am\s+)?|spätestens\s+(?:am\s+|zum\s+|bis\s+)?|"
    r"Abgabe(?:termin)?:?\s+(?:am\s+|bis\s+)?|Rückgabe:?\s+(?:bis\s+)?(?:zum\s+)?|Frist:?\s+)"
    r"(?:[A-Za-zäöüÄÖÜ]+,?\s+(?:den\s+)?)?(\d{1,2})\.\s?(\d{1,2})\.(\d{2,4})?",
    re.I,
)
_RE_ACTION = re.compile(
    r"unterschr|rückmeld|zurückgeben|zurück\s?an|anmeld|einverständnis|überweis|"
    r"bitte\s+(?:geben|füllen|senden|melden)",
    re.I,
)


def _year_for(day: int, month: int, sent: date) -> int:
    year = sent.year
    candidate = date(year, month, day)
    if (candidate - sent).days < -120:  # z.B. Brief im Dezember, Frist im Januar
        year += 1
    return year


def analyze_rules(ctx: dict[str, Any]) -> dict[str, Any]:
    """Einfache Erkennung von Fristen und Beträgen."""
    text = f"{ctx.get('title', '')}\n{ctx.get('body', '')}"
    sent = ctx.get("sent_date") or date.today()
    due = None
    for match in _RE_DEADLINE.finditer(text):
        try:
            day, month = int(match[1]), int(match[2])
            year = match[3]
            year = (
                (int(year) + 2000 if len(year) == 2 else int(year))
                if year
                else _year_for(day, month, sent)
            )
            candidate = date(year, month, day)
        except ValueError:
            continue
        if due is None or candidate < due:
            due = candidate
    amounts = [_parse_amount(m[1]) for m in _RE_AMOUNT.finditer(text)]
    amount = max((a for a in amounts if a), default=None)
    tasks = []
    title = ctx.get("title") or "Mitteilung"
    if amount:
        tasks.append(
            {
                "title": f"{title}: bezahlen",
                "type": "zahlung",
                "due": due.isoformat() if due else None,
                "amount": amount,
                "payee": None,
                "iban": None,
                "reference": None,
                "details": "Automatisch erkannt (ohne KI) – bitte prüfen.",
            }
        )
    elif due or _RE_ACTION.search(text):
        tasks.append(
            {
                "title": f"{title}: erledigen/Rückmeldung",
                "type": "rueckmeldung",
                "due": due.isoformat() if due else None,
                "amount": None,
                "payee": None,
                "iban": None,
                "reference": None,
                "details": "Automatisch erkannt (ohne KI) – bitte prüfen.",
            }
        )
    summary = re.sub(r"\s+", " ", ctx.get("body") or "").strip()
    if len(summary) > 220:
        summary = summary[:217] + "…"
    return {
        "summary": summary,
        "summaries": {},
        "category": "aktion" if tasks else "info",
        "urgency": "mittel" if tasks else "niedrig",
        "tasks": tasks,
        "events": [],
    }
