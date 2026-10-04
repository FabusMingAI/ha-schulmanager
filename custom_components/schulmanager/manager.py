"""Kernlogik des Schulmanagers: Abruf, Ablage, Auswertung, Aufgaben, Erinnerungen."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
import hashlib
import os
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .analyzer import (
    AnalyzeError,
    analyze_rules,
    async_analyze_ai,
    async_translate_summary,
    fmt_eur,
    summary_languages,
)
from .classes import concerns_class
from .const import (
    ACTION_DONE,
    ACTION_READ,
    ACTION_SNOOZE,
    AMPEL_GREEN,
    APPT_EXAM,
    APPT_TEST,
    CONF_APPOINTMENT_KINDS,
    CONF_OWN_CLASS_ONLY,
    CONF_SUMMARY_LANGUAGES,
    DEFAULT_APPOINTMENT_KINDS,
    DEFAULT_OWN_CLASS_ONLY,
    AMPEL_RED,
    AMPEL_YELLOW,
    CONF_AI_ENTITY,
    CONF_ANALYZE_DAYS,
    CONF_AUTO_DOWNLOAD,
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_LOOKBACK_DAYS,
    CONF_NOTIFY,
    CONF_PORTALS,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL,
    CONF_TTS_END,
    CONF_TTS_ENGINE,
    CONF_TTS_START,
    CONF_TTS_TARGETS,
    DEFAULT_ANALYZE_DAYS,
    DEFAULT_AUTO_DOWNLOAD,
    DEFAULT_DIGEST_ENABLED,
    DEFAULT_DIGEST_TIME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_TIME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TTS_END,
    DEFAULT_TTS_START,
    DOMAIN,
    EVENT_CATEGORIES,
    EVENT_NEW_ITEM,
    EVENT_SUBSTITUTION,
    EVENT_TASK_REMINDER,
    KIND_LABELS,
    KIND_LETTER,
    KIND_MANUAL,
    KIND_POLL,
    LOGGER,
    MEDIA_SUBDIR,
    SIGNAL_UPDATED,
    STATUS_DONE,
    STATUS_OPEN,
    STATUS_PROGRESS,
    STORAGE_VERSION,
    SUBSTITUTION_KINDS,
    TASK_TYPE_ICONS,
)
from .portal import (
    appointment_kind,
    appointment_subject,
    PortalAuthError,
    PortalConnectionError,
    PortalFile,
    PortalItem,
    PortalResult,
    SchulPortal,
)

MAX_STORED_TEXT = 20000


def school_year(day: date) -> str:
    """Schuljahr als '2026-27' (Wechsel am 1. August)."""
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _safe_name(text: str, limit: int = 80) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", text or "").strip(" .")
    text = re.sub(r"\s+", " ", text)
    return text[:limit].rstrip(" .") or "Dokument"


def _parse_time(value: str | None, default: str) -> time:
    try:
        return time.fromisoformat(value or default)
    except ValueError:
        return time.fromisoformat(default)


def _fmt_date(value: str | None) -> str:
    if not value:
        return ""
    d = date.fromisoformat(value[:10])
    return d.strftime("%d.%m.")


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _day_label(day: date, today: date) -> str:
    if day == today:
        return "Heute"
    if day == today + timedelta(days=1):
        return "Morgen"
    return f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')}"


def _days_text(days: int) -> str:
    if days == 0:
        return "heute"
    if days == 1:
        return "morgen"
    if days == -1:
        return "seit gestern überfällig"
    if days < 0:
        return f"seit {-days} Tagen überfällig"
    return f"in {days} Tagen"


class SchulManager:
    """Verwaltet alle Portale, Kinder, Eingänge und Aufgaben."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.data: dict[str, Any] = {}
        self.last_update: datetime | None = None
        self.last_errors: list[str] = []
        self._sessions: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._queue_event = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------
    def opt(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, default)

    @property
    def items(self) -> dict[str, dict[str, Any]]:
        return self.data["items"]

    @property
    def tasks(self) -> dict[str, dict[str, Any]]:
        return self.data["tasks"]

    @property
    def children(self) -> dict[str, dict[str, Any]]:
        return self.data["children"]

    @property
    def media_root(self) -> tuple[str, str]:
        """(media-source-Schlüssel, Pfad auf der Platte)."""
        dirs = self.hass.config.media_dirs or {}
        if "local" in dirs:
            return "local", dirs["local"]
        if dirs:
            key = next(iter(dirs))
            return key, dirs[key]
        return "local", self.hass.config.path("media")

    def file_abspath(self, rel: str) -> str:
        return os.path.join(self.media_root[1], rel)

    def media_content_id(self, rel: str) -> str:
        return f"media-source://media_source/{self.media_root[0]}/{rel}"

    def _save(self) -> None:
        self.store.async_delay_save(lambda: self.data, 2)

    @callback
    def _changed(self) -> None:
        self._save()
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATED}_{self.entry.entry_id}")

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    async def async_load(self) -> None:
        stored = await self.store.async_load() or {}
        self.data = {
            "items": stored.get("items", {}),
            "tasks": stored.get("tasks", {}),
            "events": stored.get("events", {}),
            "appointments": stored.get("appointments", {}),
            "children": stored.get("children", {}),
            "initialized": stored.get("initialized", []),
            "dashboard": stored.get("dashboard", {}),
            "timetable": stored.get("timetable", {}),
            "substitutions": stored.get("substitutions", {}),
            "subs_seen": stored.get("subs_seen", {}),
            "sicknotes": stored.get("sicknotes", {}),
        }

    async def async_start(self) -> None:
        interval = timedelta(
            minutes=max(10, int(self.opt(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._scheduled_refresh, interval, name="Schulmanager Abruf"
            )
        )
        rt = _parse_time(self.opt(CONF_REMINDER_TIME), DEFAULT_REMINDER_TIME)
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._scheduled_reminders, rt.hour, rt.minute, 0
            )
        )
        if self.opt(CONF_DIGEST_ENABLED, DEFAULT_DIGEST_ENABLED):
            dt_ = _parse_time(self.opt(CONF_DIGEST_TIME), DEFAULT_DIGEST_TIME)
            self._unsubs.append(
                async_track_time_change(
                    self.hass, self._scheduled_digest, dt_.hour, dt_.minute, 0
                )
            )
        self._unsubs.append(
            self.hass.bus.async_listen(
                "mobile_app_notification_action", self._handle_mobile_action
            )
        )
        self._worker = self.entry.async_create_background_task(
            self.hass, self._analysis_worker(), "schulmanager_analyse"
        )
        if self._pending() or self._missing_translations():
            self._queue_event.set()

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._worker:
            self._worker.cancel()
        await self.store.async_save(self.data)

    # ------------------------------------------------------------------
    # Abruf
    # ------------------------------------------------------------------
    async def _scheduled_refresh(self, _now: datetime) -> None:
        try:
            await self.async_refresh()
        except HomeAssistantError as err:
            LOGGER.warning("Abruf fehlgeschlagen: %s", err)

    async def async_refresh(self, initial: bool = False) -> None:
        """Alle Portale abrufen und neue Eingänge verarbeiten."""
        async with self._lock:
            errors: list[str] = []
            for portal in self.entry.data.get(CONF_PORTALS, []):
                school = portal[CONF_SCHOOL]
                session = self._sessions.get(school)
                if session is None:
                    session = self._sessions[school] = async_create_clientsession(
                        self.hass
                    )
                api = SchulPortal(
                    session,
                    school,
                    portal["username"],
                    portal["password"],
                    int(self.opt(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS)),
                )
                try:
                    result = await api.async_fetch(self._need_download)
                except PortalAuthError as err:
                    msg = f"{school}: Anmeldung fehlgeschlagen ({err})"
                    if initial:
                        raise ConfigEntryAuthFailed(msg) from err
                    errors.append(msg)
                    continue
                except PortalConnectionError as err:
                    msg = f"{school}: Portal nicht erreichbar ({err})"
                    if initial and not self.children:
                        raise ConfigEntryNotReady(msg) from err
                    errors.append(msg)
                    continue
                errors.extend(f"{school}: {e}" for e in result.errors)
                await self._merge(result)
            self.last_errors = errors
            self.last_update = dt_util.now()
            self._changed()
            if self._pending():
                self._queue_event.set()

    def _need_download(self, item: PortalItem) -> bool:
        if not self.opt(CONF_AUTO_DOWNLOAD, DEFAULT_AUTO_DOWNLOAD):
            return False
        stored = self.items.get(item.uid)
        if stored is None or not stored.get("files"):
            return True
        return stored.get("version") != item.version

    async def _merge(self, result: PortalResult) -> None:
        first_import = result.school not in self.data["initialized"]
        today = dt_util.now().date()
        analyze_from = today - timedelta(
            days=int(self.opt(CONF_ANALYZE_DAYS, DEFAULT_ANALYZE_DAYS))
        )
        new_count = 0
        fresh_subs: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for pchild in result.children:
            key = slugify(pchild.firstname) or pchild.student_id
            self.children[key] = {
                "name": pchild.firstname,
                "fullname": pchild.fullname,
                "classname": pchild.classname,
                "school": result.school,
                "school_name": result.school_name,
                "student_id": pchild.student_id,
                "portal_url": result.base_url,
            }
            self.data["appointments"][key] = [
                {
                    "uid": a["uid"],
                    "title": a["title"],
                    "detail": a.get("detail"),
                    "kind": a.get("kind"),
                    "start": a["start"].isoformat() if a["start"] else None,
                    "end": a["end"].isoformat() if a["end"] else None,
                }
                for a in pchild.appointments
            ]
            if pchild.timetable is not None and (
                pchild.timetable or not self.data["timetable"].get(key, {}).get("lessons")
            ):
                # leere Antwort (z. B. Seite gerade nicht erreichbar) überschreibt nichts
                self.data["timetable"][key] = {
                    "lessons": pchild.timetable,
                    "updated": dt_util.now().isoformat(),
                }
            if pchild.sicknotes is not None and (
                pchild.sicknotes or not self.data["sicknotes"].get(key)
            ):
                # leere Antwort überschreibt keine bekannten Krankmeldungen
                self.data["sicknotes"][key] = sorted(
                    pchild.sicknotes, key=lambda n: (n["start"], n["end"])
                )
            if pchild.substitutions is not None and (
                pchild.substitutions.get("available")
                or key not in self.data["substitutions"]
            ):
                if fresh := self._merge_substitutions(key, pchild.substitutions):
                    fresh_subs[key] = fresh
            for pitem in pchild.items:
                stored = self.items.get(pitem.uid)
                if stored is None:
                    if pitem.kind == KIND_POLL:
                        end = pitem.meta.get("ende")
                        recent = bool(end) and date.fromisoformat(end) >= today
                    else:
                        recent = (
                            pitem.sent is None
                            or pitem.sent.date() >= analyze_from
                            or (
                                pitem.kind == KIND_LETTER
                                and not pitem.meta.get("empfang_bestaetigt", True)
                            )
                        )
                    stored = self._new_item(key, result, pitem)
                    if first_import and not recent:
                        stored["read"] = True
                        stored["analysis"] = {"status": "archiv"}
                    else:
                        stored["notify"] = not first_import
                        new_count += 1
                    self.items[pitem.uid] = stored
                    await self._store_files(stored, pitem.files)
                elif stored.get("version") != pitem.version:
                    stored.update(
                        title=pitem.title,
                        body=pitem.body,
                        sent=pitem.sent.isoformat() if pitem.sent else stored.get("sent"),
                        version=pitem.version,
                        meta=pitem.meta,
                        read=False,
                        notify=not first_import,
                        updated=dt_util.now().isoformat(),
                    )
                    stored["analysis"] = {"status": "pending"}
                    await self._store_files(stored, pitem.files)
                else:
                    stored["meta"] = pitem.meta
                    if pitem.files and not stored.get("files"):
                        await self._store_files(stored, pitem.files)
                self._sync_portal_tasks(stored, today)
        for key, fresh in fresh_subs.items():
            await self._notify_substitutions(key, fresh)
        if first_import:
            self.data["initialized"].append(result.school)
            if new_count:
                await self._notify(
                    f"Schulmanager: {result.school_name}",
                    f"Eingerichtet. {new_count} aktuelle Mitteilungen werden ausgewertet, "
                    "ältere liegen im Archiv.",
                    {"tag": f"schulmanager-init-{result.school}"},
                )

    def _new_item(self, child: str, result: PortalResult, p: PortalItem) -> dict[str, Any]:
        return {
            "uid": p.uid,
            "child": child,
            "school": result.school,
            "school_name": result.school_name,
            "kind": p.kind,
            "title": p.title,
            "body": p.body,
            "sender": p.sender,
            "sent": p.sent.isoformat() if p.sent else None,
            "url": p.url,
            "version": p.version,
            "meta": p.meta,
            "files": [],
            "text": "",
            "read": False,
            "notify": False,
            "analysis": {"status": "pending"},
            "created": dt_util.now().isoformat(),
        }

    # ------------------------------------------------------------------
    # Ablage
    # ------------------------------------------------------------------
    async def _store_files(self, item: dict[str, Any], files: list[PortalFile]) -> None:
        if not files:
            return
        child = self.children.get(item["child"], {}).get("name", item["child"])
        sent = date.fromisoformat(item["sent"][:10]) if item.get("sent") else dt_util.now().date()
        rel_dir = os.path.join(MEDIA_SUBDIR, _safe_name(child), school_year(sent))
        base = f"{sent.isoformat()} {KIND_LABELS.get(item['kind'], '')} - {_safe_name(item['title'], 60)}"
        known = {f["name"] for f in item.get("files", [])}

        def _write() -> tuple[list[dict[str, Any]], str]:
            abs_dir = self.file_abspath(rel_dir)
            os.makedirs(abs_dir, exist_ok=True)
            saved: list[dict[str, Any]] = []
            texts: list[str] = []
            for f in files:
                if f.name in known:
                    continue
                stem, ext = os.path.splitext(f.name)
                if not ext and f.content_type == "application/pdf":
                    ext = ".pdf"
                name = base if len(files) == 1 else f"{base} - {_safe_name(stem, 40)}"
                fname = f"{name}{ext.lower()}"
                n = 2
                while os.path.exists(os.path.join(abs_dir, fname)):
                    fname = f"{name} ({n}){ext.lower()}"
                    n += 1
                with open(os.path.join(abs_dir, fname), "wb") as fh:
                    fh.write(f.content)
                saved.append(
                    {
                        "name": f.name,
                        "path": os.path.join(rel_dir, fname),
                        "content_type": f.content_type,
                        "size": len(f.content),
                    }
                )
                if ext.lower() == ".pdf" or f.content_type == "application/pdf":
                    texts.append(_pdf_text(os.path.join(abs_dir, fname)))
            return saved, "\n\n".join(t for t in texts if t)

        saved, text = await self.hass.async_add_executor_job(_write)
        item.setdefault("files", []).extend(saved)
        if text:
            item["text"] = ((item.get("text") or "") + "\n\n" + text).strip()[:MAX_STORED_TEXT]

    # ------------------------------------------------------------------
    # Aufgaben, die direkt aus dem Portal folgen (ohne KI)
    # ------------------------------------------------------------------
    def _sync_portal_tasks(self, item: dict[str, Any], today: date) -> None:
        meta = item.get("meta") or {}
        if item["kind"] == KIND_POLL:
            tid = f"{item['uid']}-umfrage"
            voted = bool(meta.get("abgestimmt"))
            end = meta.get("ende")
            if not voted and end and date.fromisoformat(end) >= today:
                self._ensure_task(
                    tid,
                    item,
                    title=f"Umfrage beantworten: {item['title']}",
                    type_="rueckmeldung",
                    due=end,
                    source="portal",
                )
            elif voted and tid in self.tasks:
                self._set_done(tid, True)
        elif item["kind"] == KIND_LETTER:
            tid = f"{item['uid']}-empfang"
            confirmed = meta.get("empfang_bestaetigt", True)
            if not confirmed and not item.get("files"):
                self._ensure_task(
                    tid,
                    item,
                    title=f"Elternbrief lesen und Empfang im Portal bestätigen: {item['title']}",
                    type_="lesen",
                    due=None,
                    source="portal",
                )
            elif confirmed and tid in self.tasks:
                self._set_done(tid, True)

    def _ensure_task(
        self,
        tid: str,
        item: dict[str, Any] | None,
        *,
        title: str,
        type_: str,
        due: str | None,
        source: str,
        amount: float | None = None,
        details: str | None = None,
        payee: str | None = None,
        iban: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        task = self.tasks.get(tid)
        if task is None:
            task = self.tasks[tid] = {
                "id": tid,
                "child": item["child"] if item else None,
                "item_uid": item["uid"] if item else None,
                "status": STATUS_OPEN,
                "created": dt_util.now().isoformat(),
                "completed": None,
                "reminded": [],
                "snoozed_until": None,
            }
        task.update(
            title=title,
            type=type_,
            due=due,
            amount=amount,
            details=details,
            payee=payee,
            iban=iban,
            reference=reference,
            source=source,
        )
        return task

    def _set_done(self, tid: str, done: bool) -> None:
        task = self.tasks[tid]
        if done and task["status"] != STATUS_DONE:
            task["status"] = STATUS_DONE
            task["completed"] = dt_util.now().isoformat()
        elif not done and task["status"] == STATUS_DONE:
            task["status"] = STATUS_OPEN
            task["completed"] = None

    def _set_status(self, tid: str, status: str) -> None:
        if status == STATUS_DONE:
            self._set_done(tid, True)
            return
        task = self.tasks[tid]
        task["status"] = STATUS_PROGRESS if status == STATUS_PROGRESS else STATUS_OPEN
        task["completed"] = None

    # ------------------------------------------------------------------
    # KI-Auswertung (Warteschlange)
    # ------------------------------------------------------------------
    def _pending(self) -> list[dict[str, Any]]:
        return sorted(
            (i for i in self.items.values() if i.get("analysis", {}).get("status") == "pending"),
            key=lambda i: i.get("sent") or "",
        )

    def _missing_translations(self) -> list[dict[str, Any]]:
        """Ausgewertete Mitteilungen, denen eine der gewählten Sprachen fehlt."""
        if not self.opt(CONF_AI_ENTITY):
            return []
        langs = self.summary_languages
        out = []
        for item in self.items.values():
            a = item.get("analysis", {})
            if a.get("status") != "fertig" or not a.get("summary"):
                continue
            have = set(a.get("summaries") or {}) or {"de"}
            missing = [lang for lang in langs if lang not in have]
            tried = set(a.get("translate_tried") or [])
            if missing and not set(missing) <= tried:
                out.append(item)
        return sorted(out, key=lambda i: i.get("sent") or "", reverse=True)

    async def _translate(self, item: dict[str, Any]) -> None:
        """Fehlende Sprachen der Zusammenfassung ergänzen – ohne Aufgaben neu zu erzeugen."""
        a = item["analysis"]
        summaries = dict(a.get("summaries") or {})
        if not summaries:
            # vor 0.8.0 ausgewertet: Zusammenfassung ist deutsch
            summaries = {"de": a["summary"]}
        source = next(iter(summaries))
        missing = [lang for lang in self.summary_languages if lang not in summaries]
        a["translate_tried"] = sorted(set(a.get("translate_tried") or []) | set(missing))
        try:
            summaries.update(
                await async_translate_summary(
                    self.hass, self.opt(CONF_AI_ENTITY), summaries[source], source, missing
                )
            )
        except AnalyzeError as err:
            LOGGER.debug("Übersetzung von %s fehlgeschlagen: %s", item["uid"], err)
        a["summaries"] = summaries

    async def _analysis_worker(self) -> None:
        while True:
            await self._queue_event.wait()
            self._queue_event.clear()
            await self._work_queue()
            # danach fehlende Sprachen der Zusammenfassung nachtragen (neue Mitteilungen haben Vorrang)
            while not self._pending() and (todo := self._missing_translations()):
                item = todo[0]
                try:
                    await self._translate(item)
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Übersetzung von %s fehlgeschlagen", item["uid"])
                    item["analysis"]["translate_tried"] = list(self.summary_languages)
                self._changed()
                await asyncio.sleep(1)
            await self._work_queue()

    async def _work_queue(self) -> None:
        while pending := self._pending():
            item = pending[0]
            try:
                await self._analyze(item)
            except Exception as err:  # noqa: BLE001
                LOGGER.exception("Auswertung von %s fehlgeschlagen", item["uid"])
                item["analysis"] = {"status": "fehler", "error": str(err)}
            self._changed()
            if item.pop("notify", False):
                await self._notify_item(item)
            await asyncio.sleep(0)

    def _context(self, item: dict[str, Any]) -> dict[str, Any]:
        child = self.children.get(item["child"], {})
        body = item.get("body") or ""
        if item.get("text"):
            body = f"{body}\n\n--- Inhalt der angehängten Datei(en) ---\n{item['text']}"
        sent = item.get("sent")
        return {
            "child": child.get("name"),
            "classname": child.get("classname"),
            "school": item.get("school_name"),
            "kind": KIND_LABELS.get(item["kind"], item["kind"]),
            "sender": item.get("sender"),
            "sent": sent[:16].replace("T", " ") if sent else None,
            "sent_date": date.fromisoformat(sent[:10]) if sent else None,
            "title": item.get("title"),
            "body": body.strip(),
        }

    async def _analyze(self, item: dict[str, Any]) -> None:
        ctx = self._context(item)
        ai_entity = self.opt(CONF_AI_ENTITY)
        method = "regeln"
        error = None
        result = None
        if ai_entity:
            attachments = None
            if not item.get("text") and item.get("files"):
                attachments = [
                    {
                        "media_content_id": self.media_content_id(f["path"]),
                        "media_content_type": f.get("content_type") or "application/pdf",
                    }
                    for f in item["files"]
                ]
            try:
                result = await async_analyze_ai(
                    self.hass, ai_entity, ctx, attachments, self.summary_languages
                )
                method = "ki"
            except AnalyzeError as err:
                error = str(err)
                LOGGER.warning("KI-Auswertung fehlgeschlagen, nutze Regeln: %s", err)
        if result is None:
            result = analyze_rules(ctx)
        self._apply_analysis(item, result, method)
        item["analysis"] = {
            "status": "fertig",
            "method": method,
            "summary": result["summary"],
            "summaries": result.get("summaries") or {},
            "category": result["category"],
            "urgency": result["urgency"],
            "error": error,
            "at": dt_util.now().isoformat(),
        }

    def _apply_analysis(self, item: dict[str, Any], result: dict[str, Any], method: str) -> None:
        uid = item["uid"]
        keep: set[str] = set()
        for t in result["tasks"]:
            tid = f"{uid}-{hashlib.sha1(t['title'].lower().encode()).hexdigest()[:8]}"
            keep.add(tid)
            existing = self.tasks.get(tid)
            if existing and existing["status"] == STATUS_DONE:
                continue
            self._ensure_task(
                tid,
                item,
                title=t["title"],
                type_=t["type"],
                due=t["due"],
                source=method,
                amount=t["amount"],
                details=t["details"],
                payee=t["payee"],
                iban=t["iban"],
                reference=t["reference"],
            )
        for tid, task in list(self.tasks.items()):
            if (
                task.get("item_uid") == uid
                and task.get("source") in ("ki", "regeln")
                and task["status"] == STATUS_OPEN
                and tid not in keep
            ):
                del self.tasks[tid]
        events = self.data["events"]
        for eid in [e for e, ev in events.items() if ev.get("item_uid") == uid]:
            del events[eid]
        for n, ev in enumerate(result["events"]):
            eid = f"{uid}-termin-{n}"
            events[eid] = {**ev, "uid": eid, "item_uid": uid, "child": item["child"]}

    # ------------------------------------------------------------------
    # Öffentliche Aktionen
    # ------------------------------------------------------------------
    async def async_reanalyze(self, uid: str) -> None:
        if uid not in self.items:
            raise HomeAssistantError(f"Unbekannte Mitteilung: {uid}")
        self.items[uid]["analysis"] = {"status": "pending"}
        self._changed()
        self._queue_event.set()

    def mark_read(self, uid: str | None = None, child: str | None = None, read: bool = True) -> int:
        count = 0
        for item in self.items.values():
            if uid and item["uid"] != uid:
                continue
            if child and item["child"] != child:
                continue
            if item.get("read") != read:
                item["read"] = read
                count += 1
        self._changed()
        return count

    @property
    def summary_languages(self) -> list[str]:
        return summary_languages(self.opt(CONF_SUMMARY_LANGUAGES))

    def set_item_status(self, uid: str, status: str) -> None:
        """Status einer Mitteilung: offen, in Arbeit oder erledigt (erledigt = gelesen)."""
        item = self.items.get(uid)
        if item is None:
            raise HomeAssistantError(f"Unbekannte Mitteilung: {uid}")
        if status not in (STATUS_OPEN, STATUS_PROGRESS, STATUS_DONE):
            raise HomeAssistantError(f"Unbekannter Status: {status}")
        item["status"] = status
        if status == STATUS_DONE:
            item["read"] = True
            item["done_at"] = dt_util.now().isoformat()
        else:
            item.pop("done_at", None)
        self._changed()

    def complete_task(self, tid: str, done: bool = True) -> None:
        if tid not in self.tasks:
            raise HomeAssistantError(f"Unbekannte Aufgabe: {tid}")
        self._set_done(tid, done)
        self._changed()

    def add_task(
        self,
        child: str,
        title: str,
        due: str | None = None,
        amount: float | None = None,
        details: str | None = None,
        type_: str = "aufgabe",
    ) -> dict[str, Any]:
        if child not in self.children:
            raise HomeAssistantError(f"Unbekanntes Kind: {child}")
        tid = f"manuell-{dt_util.now().strftime('%Y%m%d%H%M%S%f')}"
        task = self._ensure_task(
            tid,
            None,
            title=title,
            type_="zahlung" if amount else type_,
            due=due,
            source=KIND_MANUAL,
            amount=amount,
            details=details,
        )
        task["child"] = child
        self._changed()
        return task

    def update_task(self, tid: str, **changes: Any) -> None:
        task = self.tasks.get(tid)
        if task is None:
            raise HomeAssistantError(f"Unbekannte Aufgabe: {tid}")
        if "status" in changes:
            status = changes.pop("status")
            # „offen“ aus der To-do-Liste soll „in Arbeit“ nicht zurücksetzen
            if not (status == STATUS_OPEN and task["status"] == STATUS_PROGRESS):
                self._set_status(tid, status)
        if "due" in changes and changes["due"] != task.get("due"):
            task["reminded"] = []
            task["snoozed_until"] = None
        if "comment" in changes:
            task["comment"] = (changes.pop("comment") or "").strip() or None
            task["comment_at"] = dt_util.now().isoformat()
        task.update({k: v for k, v in changes.items() if k in ("title", "due", "details")})
        self._changed()

    def delete_tasks(self, tids: list[str]) -> None:
        for tid in tids:
            self.tasks.pop(tid, None)
        self._changed()

    # ------------------------------------------------------------------
    # Auswertung für Sensoren / Dashboard
    # ------------------------------------------------------------------
    def child_tasks(self, child: str, include_done: bool = False) -> list[dict[str, Any]]:
        tasks = [
            t
            for t in self.tasks.values()
            if t.get("child") == child and (include_done or t["status"] != STATUS_DONE)
        ]
        return sorted(tasks, key=lambda t: (t["status"] == STATUS_DONE, t.get("due") or "9999", t["created"]))

    def child_items(self, child: str) -> list[dict[str, Any]]:
        items = [i for i in self.items.values() if i["child"] == child]
        return sorted(items, key=lambda i: i.get("sent") or i.get("created") or "", reverse=True)

    def child_summary(self, child: str) -> dict[str, Any]:
        today = dt_util.now().date()
        open_tasks = self.child_tasks(child)
        overdue, soon, week = [], [], []
        for t in open_tasks:
            if not t.get("due"):
                continue
            days = (date.fromisoformat(t["due"]) - today).days
            if days < 0:
                overdue.append(t)
            elif days <= 1:
                soon.append(t)
            elif days <= 7:
                week.append(t)
        unread = [i for i in self.child_items(child) if not i.get("read")]
        urgent_unread = [
            i for i in unread if i.get("analysis", {}).get("urgency") == "hoch"
        ]
        payments = [t for t in open_tasks if t.get("type") == "zahlung"]
        if overdue or soon or urgent_unread:
            ampel = AMPEL_RED
        elif week or unread or open_tasks:
            ampel = AMPEL_YELLOW
        else:
            ampel = AMPEL_GREEN
        dated = [t for t in open_tasks if t.get("due")]
        return {
            "ampel": ampel,
            "open_tasks": open_tasks,
            "overdue": overdue,
            "due_soon": soon,
            "due_week": week,
            "unread": unread,
            "payments": payments,
            "payments_total": round(sum(t.get("amount") or 0 for t in payments), 2),
            "next_task": dated[0] if dated else None,
        }

    def child_events(self, child: str, subst_from: date | None = None) -> list[dict[str, Any]]:
        """Alle Kalendereinträge eines Kindes (normalisiert).

        Neben den Feldern für den Kalender enthält jeder Eintrag ``category``,
        ``icon``, ``title`` und ``hover`` (Kurzbeschreibung, bei Mitteilungen die
        KI-Zusammenfassung) sowie ggf. ``item_uid``/``task_id`` für die Karte.
        """
        out: list[dict[str, Any]] = []
        tz = dt_util.get_default_time_zone()
        kinds = set(self.opt(CONF_APPOINTMENT_KINDS, DEFAULT_APPOINTMENT_KINDS) or [])
        classname = self.children.get(child, {}).get("classname")
        own_only = self.opt(CONF_OWN_CLASS_ONLY, DEFAULT_OWN_CLASS_ONLY)

        def other_class(text: str | None) -> bool:
            return bool(own_only) and concerns_class(text, classname) is False

        for a in self.data["appointments"].get(child, []):
            if not a.get("start"):
                continue
            kind = a.get("kind") or appointment_kind(None, a.get("title"))
            if kind not in kinds:
                continue
            if other_class(f"{a.get('title') or ''} {a.get('detail') or ''}"):
                continue
            category = {APPT_EXAM: "schulaufgabe", APPT_TEST: "test"}.get(kind, "portal")
            icon, label = EVENT_CATEGORIES[category]
            start = datetime.fromisoformat(a["start"])
            end = datetime.fromisoformat(a["end"]) if a.get("end") else start
            end = end - timedelta(hours=2)  # pyelternportal addiert 2 h
            hover = a.get("detail") or a["title"]
            out.append(
                {
                    "uid": a["uid"],
                    "summary": f"{icon} {a['title']}",
                    "start": start.date(),
                    "end": max(end.date(), start.date()) + timedelta(days=1),
                    "description": f"{label} (Eltern-Portal)",
                    "category": category,
                    "icon": icon,
                    "title": a["title"],
                    "hover": f"{hover} – {label}",
                    "subject": appointment_subject(a.get("detail") or a["title"]),
                }
            )
        for ev in self.data["events"].values():
            if ev.get("child") != child:
                continue
            if other_class(ev.get("title")):
                continue
            item = self.items.get(ev.get("item_uid"), {})
            day = date.fromisoformat(ev["date"])
            desc = f"Aus: {item.get('title', '')}"
            if ev.get("time"):
                start = datetime.combine(day, time.fromisoformat(ev["time"]), tz)
                entry = {"start": start, "end": start + timedelta(hours=1)}
            else:
                end_day = date.fromisoformat(ev["end"]) if ev.get("end") else day
                entry = {"start": day, "end": max(end_day, day) + timedelta(days=1)}
            summary = item.get("analysis", {}).get("summary")
            hover = [summary or ev.get("details") or ""]
            if ev.get("location"):
                hover.append(f"Ort: {ev['location']}")
            if item:
                hover.append(f"Aus: {item.get('title', '')}")
            out.append(
                {
                    "uid": ev["uid"],
                    "summary": f"📅 {ev['title']}",
                    "description": desc,
                    "location": ev.get("location"),
                    "category": "termin",
                    "icon": "📅",
                    "title": ev["title"],
                    "hover": " · ".join(h for h in hover if h),
                    "item_uid": ev.get("item_uid"),
                    **entry,
                }
            )
        for t in self.child_tasks(child):
            if not t.get("due"):
                continue
            day = date.fromisoformat(t["due"])
            item = self.items.get(t.get("item_uid") or "", {})
            icon = TASK_TYPE_ICONS.get(t["type"], "✅")
            hover = [
                t.get("details") or "",
                item.get("analysis", {}).get("summary") or "",
            ]
            if item:
                hover.append(f"Aus: {item.get('title', '')}")
            out.append(
                {
                    "uid": f"frist-{t['id']}",
                    "summary": f"{icon} Frist: {self.task_label(t)}",
                    "start": day,
                    "end": day + timedelta(days=1),
                    "description": self.task_description(t),
                    "category": f"frist_{t['type']}",
                    "icon": icon,
                    "title": f"Frist: {self.task_label(t)}",
                    "hover": " · ".join(dict.fromkeys(h for h in hover if h)),
                    "item_uid": t.get("item_uid"),
                    "task_id": t["id"],
                }
            )
        for n in self.data["sicknotes"].get(child, []):
            first = date.fromisoformat(n["start"])
            last = date.fromisoformat(n.get("end") or n["start"])
            name = self.children.get(child, {}).get("name", child)
            span = "" if first == last else f" ({first.strftime('%d.%m.')}–{last.strftime('%d.%m.')})"
            out.append(
                {
                    "uid": f"krank-{child}-{n['start']}-{n.get('end')}",
                    "summary": f"🤒 Krankmeldung {name}",
                    "start": first,
                    "end": max(last, first) + timedelta(days=1),
                    "description": n.get("comment") or "Krankmeldung im Eltern-Portal",
                    "category": "krank",
                    "icon": "🤒",
                    "title": f"Krankmeldung{span}",
                    "hover": (n.get("comment") or "Krankmeldung im Eltern-Portal")
                    + span,
                }
            )
        since = subst_from or dt_util.now().date() - timedelta(days=7)
        for d in self.data["substitutions"].get(child, {}).get("days", []):
            day = date.fromisoformat(d["date"])
            if day < since:
                continue
            for e in d["entries"]:
                kind = e.get("kind") if e.get("kind") in SUBSTITUTION_KINDS else "vertretung"
                icon = EVENT_CATEGORIES[kind][0]
                begin, finish = self.lesson_times(child, day, e.get("lesson") or "")
                if begin:
                    start = datetime.combine(day, time.fromisoformat(begin), tz)
                    stop = (
                        datetime.combine(day, time.fromisoformat(finish), tz)
                        if finish
                        else start + timedelta(minutes=45)
                    )
                    entry = {"start": start, "end": max(stop, start + timedelta(minutes=5))}
                else:
                    entry = {"start": day, "end": day + timedelta(days=1)}
                text = self.substitution_text(e)
                hover = [text]
                if e.get("teacher"):
                    hover.append(f"Lehrkraft laut Plan: {e['teacher']}")
                out.append(
                    {
                        "uid": f"vertretung-{e['uid']}",
                        "summary": f"{icon} {self.substitution_text(e, with_teacher=False)}",
                        "description": "\n".join(hover),
                        "location": e.get("room") or None,
                        "category": kind,
                        "icon": icon,
                        "title": self.substitution_text(e, with_teacher=False),
                        "hover": " · ".join(hover),
                        **entry,
                    }
                )
        return out

    def task_label(self, t: dict[str, Any]) -> str:
        label = t["title"]
        if t.get("amount"):
            label += f" ({fmt_eur(t['amount'])})"
        return label

    def task_description(self, t: dict[str, Any]) -> str:
        lines = []
        if t.get("details"):
            lines.append(t["details"])
        if t.get("amount"):
            pay = [f"Betrag: {fmt_eur(t['amount'])}"]
            if t.get("payee"):
                pay.append(f"Empfänger: {t['payee']}")
            if t.get("iban"):
                pay.append(f"IBAN: {t['iban']}")
            if t.get("reference"):
                pay.append(f"Verwendungszweck: {t['reference']}")
            lines.append("\n".join(pay))
        item = self.items.get(t.get("item_uid") or "")
        if item:
            src = f"Quelle: {KIND_LABELS.get(item['kind'], '')} „{item['title']}“"
            if item.get("sent"):
                src += f" vom {_fmt_date(item['sent'])}"
            lines.append(src)
            lines.append(f"Portal: {item['url']}")
        if t.get("comment"):
            lines.append(f"💬 Kommentar: {t['comment']}")
        if t.get("source") == "regeln":
            lines.append("⚠️ Ohne KI erkannt – bitte prüfen.")
        return "\n\n".join(lines)


    # ------------------------------------------------------------------
    # Stundenplan und Vertretungsplan
    # ------------------------------------------------------------------
    def _merge_substitutions(
        self, key: str, subst: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        """Vertretungsplan speichern; liefert neu aufgetauchte Einträge ab heute."""
        today = dt_util.now().date()
        known = key in self.data["substitutions"]
        seen = set(self.data["subs_seen"].get(key, []))
        days: list[dict[str, Any]] = []
        fresh: list[tuple[str, dict[str, Any]]] = []
        for d in subst.get("days", []):
            entries = []
            for e in d.get("entries", []):
                e = dict(e)
                raw = "|".join(
                    [key, d["date"]]
                    + [str(e.get(k) or "") for k in ("lesson", "subject", "substitute", "room", "info")]
                )
                e["uid"] = hashlib.sha1(raw.encode()).hexdigest()[:12]
                entries.append(e)
                if date.fromisoformat(d["date"]) >= today and e["uid"] not in seen:
                    fresh.append((d["date"], e))
            days.append({"date": d["date"], "entries": entries})
        self.data["substitutions"][key] = {
            "available": bool(subst.get("available")),
            "stand": subst.get("stand"),
            "days": days,
            "updated": dt_util.now().isoformat(),
        }
        current = [e["uid"] for d in days for e in d["entries"]]
        self.data["subs_seen"][key] = (current + [u for u in seen if u not in current])[:300]
        return fresh if known else []

    def lesson_times(self, child: str, day: date, lesson: str) -> tuple[str | None, str | None]:
        """Beginn und Ende einer Stunde (z. B. '3' oder '3-4') laut Stundenplan."""
        lessons = self.data["timetable"].get(child, {}).get("lessons", [])
        nums = re.findall(r"\d+", lesson or "")
        if not nums or not lessons:
            return None, None

        def find(num: str, field: str) -> str | None:
            same_day = [x for x in lessons if x["weekday"] == day.isoweekday()]
            for pool in (same_day, lessons):
                for x in pool:
                    if x["lesson"] == num and x.get(field):
                        return x[field]
            return None

        return find(nums[0], "start"), find(nums[-1], "end")

    def child_sicknotes(self, child: str, school_year_only: bool = False) -> list[dict[str, Any]]:
        """Krankmeldungen eines Kindes, neueste zuerst, mit Zahl der Schultage."""
        today = dt_util.now().date()
        start_year = date(today.year if today.month >= 8 else today.year - 1, 8, 1)
        out = []
        for n in self.data["sicknotes"].get(child, []):
            first = date.fromisoformat(n["start"])
            last = date.fromisoformat(n.get("end") or n["start"])
            if school_year_only and last < start_year:
                continue
            days = sum(
                1
                for i in range((last - first).days + 1)
                if (first + timedelta(days=i)).isoweekday() <= 5
            )
            out.append({**n, "days": days})
        return sorted(out, key=lambda n: n["start"], reverse=True)

    def child_substitutions(self, child: str, include_past: bool = False) -> list[dict[str, Any]]:
        """Tage des Vertretungsplans ab heute (mit Einträgen und leeren Tagen)."""
        today = dt_util.now().date()
        plan = self.data["substitutions"].get(child, {})
        return [
            d for d in plan.get("days", [])
            if include_past or date.fromisoformat(d["date"]) >= today
        ]

    def substitution_text(self, e: dict[str, Any], with_teacher: bool = True) -> str:
        lesson = f"{e['lesson']}. Std." if e.get("lesson") else ""
        subj = e.get("subject") or e.get("old_subject") or ""
        head = " ".join(x for x in (lesson, subj) if x)
        info = (e.get("info") or "").strip()
        if e.get("kind") == "entfall":
            text = f"{head} entfällt"
            if info and not re.fullmatch(r"(?i)entf[aä]llt\.?", info):
                text += f" – {info}"
            return text
        if e.get("kind") == "raum":
            text = f"{head}: Raum {e.get('room') or '?'}"
            if re.fullmatch(r"(?i)raum(änderung|wechsel)\.?", info):
                info = ""
        else:
            text = f"{head}: Vertretung"
            if with_teacher and e.get("substitute"):
                text += f" {e['substitute']}"
            if e.get("room"):
                text += f", Raum {e['room']}"
        if e.get("old_subject"):
            text += f" (statt {e['old_subject']})"
        if info:
            text += f" – {info}"
        return text

    async def _notify_substitutions(
        self, child: str, fresh: list[tuple[str, dict[str, Any]]]
    ) -> None:
        name = self.children.get(child, {}).get("name", child)
        today = dt_util.now().date()
        lines = []
        for day, e in sorted(fresh, key=lambda x: (x[0], x[1].get("lesson") or "")):
            lines.append(f"{_day_label(date.fromisoformat(day), today)}: {self.substitution_text(e)}")
        await self._notify(
            f"🔁 Vertretungsplan {name}",
            "\n".join(lines[:8]) + (f"\n… und {len(lines) - 8} weitere" if len(lines) > 8 else ""),
            {"tag": f"schulmanager-vertretung-{child}", "group": f"schulmanager-{child}"},
        )
        self.hass.bus.async_fire(
            EVENT_SUBSTITUTION,
            {
                "child": child,
                "entries": [{"date": d, **e} for d, e in fresh],
            },
        )

    # ------------------------------------------------------------------
    # Benachrichtigungen
    # ------------------------------------------------------------------
    async def _notify(self, title: str, message: str, data: dict[str, Any] | None = None) -> None:
        for svc in self.opt(CONF_NOTIFY, []) or []:
            svc = svc.removeprefix("notify.")
            try:
                await self.hass.services.async_call(
                    "notify",
                    svc,
                    {"title": title, "message": message, "data": data or {}},
                    blocking=True,
                )
            except (HomeAssistantError, ValueError) as err:
                LOGGER.warning("Benachrichtigung über notify.%s fehlgeschlagen: %s", svc, err)

    def _tts_allowed(self) -> bool:
        now = dt_util.now().time()
        start = _parse_time(self.opt(CONF_TTS_START), DEFAULT_TTS_START)
        end = _parse_time(self.opt(CONF_TTS_END), DEFAULT_TTS_END)
        return start <= now <= end

    async def async_announce(self, text: str, force: bool = False) -> None:
        targets = self.opt(CONF_TTS_TARGETS, []) or []
        if not targets or not (force or self._tts_allowed()):
            return
        engine = self.opt(CONF_TTS_ENGINE)
        for target in targets:
            try:
                if target.startswith("assist_satellite."):
                    await self.hass.services.async_call(
                        "assist_satellite",
                        "announce",
                        {"entity_id": target, "message": text},
                        blocking=True,
                    )
                elif target.startswith("media_player.") and engine:
                    await self.hass.services.async_call(
                        "tts",
                        "speak",
                        {
                            "entity_id": engine,
                            "media_player_entity_id": target,
                            "message": text,
                        },
                        blocking=True,
                    )
            except HomeAssistantError as err:
                LOGGER.warning("Ansage auf %s fehlgeschlagen: %s", target, err)

    async def _notify_item(self, item: dict[str, Any]) -> None:
        child = self.children.get(item["child"], {}).get("name", item["child"])
        analysis = item.get("analysis", {})
        tasks = [
            t for t in self.tasks.values()
            if t.get("item_uid") == item["uid"] and t["status"] != STATUS_DONE
        ]
        lines = [item["title"]]
        if analysis.get("summary"):
            lines.append(analysis["summary"])
        for t in tasks[:4]:
            due = f" – bis {_fmt_date(t['due'])}" if t.get("due") else ""
            lines.append(f"{TASK_TYPE_ICONS.get(t['type'], '✅')} {self.task_label(t)}{due}")
        if item.get("files"):
            lines.append(f"📎 {len(item['files'])} Anhang/Anhänge abgelegt")
        actions = [{"action": f"{ACTION_READ}::{item['uid']}", "title": "Gelesen"}]
        if len(tasks) == 1:
            actions.append({"action": f"{ACTION_DONE}::{tasks[0]['id']}", "title": "Erledigt"})
        actions.append({"action": "URI", "title": "Im Portal öffnen", "uri": item["url"]})
        prefix = "🔴" if analysis.get("urgency") == "hoch" else "📬"
        await self._notify(
            f"{prefix} {child} · {KIND_LABELS.get(item['kind'], '')}",
            "\n".join(lines),
            {
                "tag": f"schulmanager-{item['uid']}",
                "group": f"schulmanager-{item['child']}",
                "url": item["url"],
                "clickAction": item["url"],
                "actions": actions,
            },
        )
        self.hass.bus.async_fire(
            EVENT_CATEGORIES,
    EVENT_NEW_ITEM,
    EVENT_SUBSTITUTION,
            {
                "child": item["child"],
                "kind": item["kind"],
                "title": item["title"],
                "summary": analysis.get("summary"),
                "urgency": analysis.get("urgency"),
                "item_uid": item["uid"],
                "tasks": [self.task_label(t) for t in tasks],
            },
        )
        if analysis.get("urgency") == "hoch":
            await self.async_announce(
                f"Neue wichtige Nachricht der Schule für {child}: {item['title']}. "
                f"{analysis.get('summary', '')}"
            )

    async def _scheduled_reminders(self, _now: datetime) -> None:
        await self.async_send_reminders()

    async def async_send_reminders(self) -> int:
        """Fällige Erinnerungen verschicken (einmal pro Stufe, überfällig täglich)."""
        today = dt_util.now().date()
        try:
            stages = {
                int(x) for x in str(self.opt(CONF_REMINDER_DAYS, DEFAULT_REMINDER_DAYS)).split(",") if x.strip()
            }
        except ValueError:
            stages = {3, 1, 0}
        spoken: list[str] = []
        sent = 0
        for t in list(self.tasks.values()):
            if t["status"] == STATUS_DONE:
                continue
            snoozed = t.get("snoozed_until")
            key = None
            if snoozed and snoozed == today.isoformat():
                key = f"snooze-{today.isoformat()}"
            elif snoozed and snoozed > today.isoformat():
                continue
            elif t.get("due"):
                days = (date.fromisoformat(t["due"]) - today).days
                if days < 0:
                    key = f"over-{today.isoformat()}"
                elif days in stages:
                    key = f"d{days}"
            if key is None or key in t.get("reminded", []):
                continue
            t.setdefault("reminded", []).append(key)
            sent += 1
            await self._remind(t, today)
            if t.get("due") and (date.fromisoformat(t["due"]) - today).days <= 1:
                child = self.children.get(t["child"], {}).get("name", "")
                spoken.append(f"für {child}: {t['title']}, {_days_text((date.fromisoformat(t['due']) - today).days)}")
        if spoken:
            await self.async_announce("Erinnerung Schule. " + ". ".join(spoken) + ".")
        if sent:
            self._changed()
        return sent

    async def _remind(self, t: dict[str, Any], today: date) -> None:
        child = self.children.get(t["child"], {}).get("name", t.get("child") or "")
        when = ""
        if t.get("due"):
            days = (date.fromisoformat(t["due"]) - today).days
            when = f"Fällig {_days_text(days)} ({_fmt_date(t['due'])})"
        body = "\n".join(x for x in (self.task_label(t), when, t.get("details") or "") if x)
        if t.get("iban"):
            body += f"\nIBAN: {t['iban']}"
        if t.get("reference"):
            body += f"\nVerwendungszweck: {t['reference']}"
        item = self.items.get(t.get("item_uid") or "")
        actions = [
            {"action": f"{ACTION_DONE}::{t['id']}", "title": "Erledigt"},
            {"action": f"{ACTION_SNOOZE}::{t['id']}", "title": "Morgen erinnern"},
        ]
        if item:
            actions.append({"action": "URI", "title": "Im Portal öffnen", "uri": item["url"]})
        await self._notify(
            f"⏰ {child}: {TASK_TYPE_ICONS.get(t['type'], '✅')} Schul-Erinnerung",
            body,
            {
                "tag": f"schulmanager-task-{t['id']}",
                "group": f"schulmanager-{t.get('child')}",
                "actions": actions,
            },
        )
        self.hass.bus.async_fire(
            EVENT_TASK_REMINDER,
            {"child": t.get("child"), "task_id": t["id"], "title": t["title"], "due": t.get("due")},
        )

    async def _scheduled_digest(self, _now: datetime) -> None:
        await self.async_send_digest()

    def digest_text(self) -> str:
        today = dt_util.now().date()
        icons = {AMPEL_RED: "🔴", AMPEL_YELLOW: "🟡", AMPEL_GREEN: "🟢"}
        blocks = []
        for key, child in sorted(self.children.items()):
            s = self.child_summary(key)
            lines = [f"{icons[s['ampel']]} {child['name']}"]
            for t in s["overdue"] + s["due_soon"] + s["due_week"]:
                days = (date.fromisoformat(t["due"]) - today).days
                lines.append(f"  • {self.task_label(t)} – {_days_text(days)}")
            undated = [t for t in s["open_tasks"] if not t.get("due")]
            if undated:
                lines.append(f"  • {len(undated)} weitere Aufgabe(n) ohne Frist")
            if s["unread"]:
                lines.append(f"  📬 {len(s['unread'])} ungelesen: " + "; ".join(i["title"] for i in s["unread"][:3]))
            for ev in self.child_events(key):
                start = ev["start"]
                day = start.date() if isinstance(start, datetime) else start
                if day == today and not ev["uid"].startswith("frist-"):
                    lines.append(f"  {ev['icon']} Heute: {ev['title']}")
                elif day == today + timedelta(days=1) and ev.get("category") in ("schulaufgabe", "test"):
                    lines.append(f"  {ev['icon']} Morgen: {ev['title']}")
            if len(lines) == 1:
                lines.append("  Alles erledigt.")
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

    async def async_send_digest(self, force: bool = False) -> bool:
        today = dt_util.now().date()
        has_content = any(
            (s := self.child_summary(k))["overdue"] or s["due_soon"] or s["due_week"] or s["unread"]
            for k in self.children
        ) or any(
            d["entries"]
            for k in self.children
            for d in self.child_substitutions(k)
            if d["date"] == today.isoformat()
        )
        if not (has_content or force):
            return False
        await self._notify(
            "🎒 Schule heute",
            self.digest_text(),
            {"tag": "schulmanager-digest", "group": "schulmanager"},
        )
        return True

    async def _handle_mobile_action(self, event: Event) -> None:
        action = str(event.data.get("action", ""))
        if "::" not in action:
            return
        kind, _, ref = action.partition("::")
        if kind == ACTION_DONE and ref in self.tasks:
            self.complete_task(ref, True)
        elif kind == ACTION_SNOOZE and ref in self.tasks:
            self.tasks[ref]["snoozed_until"] = (dt_util.now().date() + timedelta(days=1)).isoformat()
            self._changed()
        elif kind == ACTION_READ and ref in self.items:
            self.mark_read(uid=ref)

    def remove_portal_data(self, school: str) -> None:
        """Daten einer entfernten Schule löschen (Dateien bleiben liegen)."""
        kids = [k for k, c in self.children.items() if c.get("school") == school]
        for k in kids:
            self.children.pop(k)
            self.data["appointments"].pop(k, None)
            self.data["timetable"].pop(k, None)
            self.data["substitutions"].pop(k, None)
            self.data["subs_seen"].pop(k, None)
            self.data["sicknotes"].pop(k, None)
        for uid in [u for u, i in self.items.items() if i.get("school") == school]:
            self.items.pop(uid)
        for tid in [t for t, v in self.tasks.items() if v.get("child") in kids]:
            self.tasks.pop(tid)
        for eid in [e for e, v in self.data["events"].items() if v.get("child") in kids]:
            self.data["events"].pop(eid)
        if school in self.data["initialized"]:
            self.data["initialized"].remove(school)


def _pdf_text(path: str, max_pages: int = 15) -> str:
    """Text aus einem PDF lesen (läuft im Executor)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    except Exception as err:  # noqa: BLE001
        LOGGER.debug("PDF-Text aus %s nicht lesbar: %s", path, err)
        return ""


__all__ = ["SchulManager", "school_year", "Callable"]
