"""Schulmanager – Eltern-Portal-Mitteilungen, Aufgaben und Fristen in Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import os
from typing import Any

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    callback,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from . import dashboard, websocket
from .const import (
    CARD_URL,
    DOMAIN,
    LOCAL_CARD_FILE,
    LOCAL_CARD_URL,
    FILE_URL_BASE,
    LOGGER,
    PLATFORMS,
    SIGNAL_UPDATED,
    TASK_STATUSES,
    TASK_TYPES,
)
from .manager import SchulManager

type SchulConfigEntry = ConfigEntry[SchulManager]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_ITEM = "item_id"
ATTR_TASK = "task_id"
ATTR_CHILD = "child"


def get_manager(hass: HomeAssistant) -> SchulManager:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    raise HomeAssistantError("Schulmanager ist nicht eingerichtet")


def file_url(hass: HomeAssistant, uid: str, index: int) -> str:
    """Signierter Link (30 Tage gültig) auf einen abgelegten Anhang."""
    return async_sign_path(
        hass,
        f"{FILE_URL_BASE}/{uid}/{index}",
        timedelta(days=30),
        use_content_user=True,
    )


class SchulFileView(HomeAssistantView):
    """Liefert abgelegte Anhänge aus – nur mit Anmeldung oder signiertem Link."""

    url = FILE_URL_BASE + "/{uid}/{index}"
    name = "api:schulmanager:datei"
    requires_auth = True

    async def get(self, request: web.Request, uid: str, index: str) -> web.StreamResponse:
        hass: HomeAssistant = request.app["hass"]
        try:
            manager = get_manager(hass)
            item = manager.items[uid]
            meta = item["files"][int(index)]
        except (HomeAssistantError, KeyError, IndexError, ValueError):
            return web.Response(status=404)
        path = os.path.realpath(manager.file_abspath(meta["path"]))
        root = os.path.realpath(manager.media_root[1])
        if not path.startswith(root + os.sep) or not await hass.async_add_executor_job(
            os.path.isfile, path
        ):
            return web.Response(status=404)
        name = os.path.basename(path)
        return web.FileResponse(
            path,
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{_quote(name)}",
                "Cache-Control": "private, max-age=3600",
            },
        )


def _card_path() -> str:
    """Karte als .js oder – z.B. nach Versand per E-Mail – als .txt."""
    www = os.path.join(os.path.dirname(__file__), "www")
    for name in ("schulmanager-card.js", "schulmanager-card.txt"):
        path = os.path.join(www, name)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError("www/schulmanager-card.js fehlt")


class SchulCardView(HomeAssistantView):
    """Liefert die Dashboard-Karte aus (reiner Oberflächen-Code, ohne Daten)."""

    url = CARD_URL
    name = "schulmanager:karte"
    requires_auth = False

    def __init__(self, path: str) -> None:
        self._path = path

    async def get(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(
            self._path,
            headers={
                "Content-Type": "application/javascript; charset=utf-8",
                "Cache-Control": "no-cache",
            },
        )


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.http.register_view(SchulFileView())
    card = await hass.async_add_executor_job(_card_path)
    hass.http.register_view(SchulCardView(card))
    websocket.async_register(hass)
    _register_services(hass)
    if not await _async_register_resource(hass, card):
        # Fallback (z. B. Dashboards im YAML-Modus): Karte als Zusatzmodul laden
        version = str(int(await hass.async_add_executor_job(os.path.getmtime, card)))
        try:
            frontend.add_extra_js_url(hass, f"{CARD_URL}?v={version}")
        except Exception:  # noqa: BLE001 - z.B. ohne Frontend (Tests)
            LOGGER.debug("Karte konnte nicht automatisch geladen werden")
    return True


def _publish_card(hass: HomeAssistant, card: str) -> str | None:
    """Karte nach /config/www/schulmanager kopieren und Versions-Hash liefern.

    /local wird von Home Assistant ab der ersten Sekunde ausgeliefert. So ist die
    Karte auch dann ladbar, wenn ein Client die Seite öffnet, während Home
    Assistant noch startet und der Schulmanager noch nicht eingerichtet ist.
    """
    www = hass.config.path("www")
    if not os.path.isdir(www):
        return None  # /local ist ohne www-Ordner beim Start nicht registriert
    with open(card, "rb") as fh:
        data = fh.read()
    target_dir = os.path.join(www, "schulmanager")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, LOCAL_CARD_FILE)
    try:
        with open(target, "rb") as fh:
            same = fh.read() == data
    except OSError:
        same = False
    if not same:
        with open(target, "wb") as fh:
            fh.write(data)
    icon = os.path.join(os.path.dirname(__file__), "brand", "icon.png")
    icon_target = os.path.join(target_dir, "icon.png")
    if os.path.isfile(icon) and not os.path.isfile(icon_target):
        with open(icon, "rb") as src, open(icon_target, "wb") as dst:
            dst.write(src.read())
    return hashlib.sha1(data).hexdigest()[:10]


async def _async_register_resource(hass: HomeAssistant, card: str) -> bool:
    """Karte als Lovelace-Ressource eintragen (Speichermodus)."""
    try:
        version = await hass.async_add_executor_job(_publish_card, hass, card)
        if not version:
            return False
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None or not hasattr(resources, "async_create_item"):
            return False  # Ressourcen im YAML-Modus
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
        url = f"{LOCAL_CARD_URL}?v={version}"
        mine = [
            item
            for item in resources.async_items()
            if str(item.get("url", "")).split("?")[0] in (LOCAL_CARD_URL, CARD_URL)
        ]
        if mine:
            first, *rest = mine
            if first.get("url") != url or first.get("res_type") != "module":
                await resources.async_update_item(
                    first["id"], {"res_type": "module", "url": url}
                )
            for item in rest:
                await resources.async_delete_item(item["id"])
        else:
            await resources.async_create_item({"res_type": "module", "url": url})
        return True
    except Exception:  # noqa: BLE001
        LOGGER.warning("Karte konnte nicht als Dashboard-Ressource eingetragen werden", exc_info=True)
        return False


async def async_setup_entry(hass: HomeAssistant, entry: SchulConfigEntry) -> bool:
    manager = SchulManager(hass, entry)
    await manager.async_load()
    if manager.children:
        # Daten vorhanden: Start nicht blockieren, Portale im Hintergrund abrufen
        entry.async_create_background_task(
            hass, manager.async_refresh(), "schulmanager_start_abruf"
        )
    else:
        await manager.async_refresh(initial=True)
    entry.runtime_data = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await manager.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _setup_dashboard(hass, entry, manager)
    return True


def _setup_dashboard(hass: HomeAssistant, entry: SchulConfigEntry, manager: SchulManager) -> None:
    """Dashboard nach dem Start und bei neuen/entfernten Kindern aktualisieren."""
    known: set[str] = set()

    async def _apply() -> None:
        await asyncio.sleep(2)  # neue Entitäten zuerst registrieren lassen
        known.clear()
        known.update(manager.children)
        await dashboard.async_apply(hass, manager)

    @callback
    def _updated() -> None:
        if set(manager.children) != known:
            entry.async_create_background_task(hass, _apply(), "schulmanager_dashboard")

    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{SIGNAL_UPDATED}_{entry.entry_id}", _updated)
    )
    entry.async_create_background_task(hass, _apply(), "schulmanager_dashboard")


async def _async_reload(hass: HomeAssistant, entry: SchulConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SchulConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok and (manager := getattr(entry, "runtime_data", None)) is not None:
        await manager.async_stop()
    return ok


# ----------------------------------------------------------------------
# Aktionen (Services)
# ----------------------------------------------------------------------
def _register_services(hass: HomeAssistant) -> None:
    async def refresh(call: ServiceCall) -> None:
        await get_manager(hass).async_refresh()

    async def mark_read(call: ServiceCall) -> ServiceResponse:
        n = get_manager(hass).mark_read(
            uid=call.data.get(ATTR_ITEM),
            child=call.data.get(ATTR_CHILD),
            read=call.data.get("read", True),
        )
        return {"changed": n}

    async def complete_task(call: ServiceCall) -> None:
        get_manager(hass).complete_task(call.data[ATTR_TASK], call.data.get("done", True))

    async def add_task(call: ServiceCall) -> ServiceResponse:
        due = call.data.get("due")
        task = get_manager(hass).add_task(
            call.data[ATTR_CHILD],
            call.data["title"],
            due=due.isoformat() if due else None,
            amount=call.data.get("amount"),
            details=call.data.get("details"),
            type_=call.data.get("type", "aufgabe"),
        )
        return {"task_id": task["id"]}

    async def update_task(call: ServiceCall) -> None:
        changes: dict[str, Any] = {}
        for key in ("status", "comment", "title", "details"):
            if key in call.data:
                changes[key] = call.data[key]
        if "due" in call.data:
            due = call.data["due"]
            changes["due"] = due.isoformat() if due else None
        get_manager(hass).update_task(call.data[ATTR_TASK], **changes)

    async def update_item(call: ServiceCall) -> None:
        get_manager(hass).set_item_status(call.data[ATTR_ITEM], call.data["status"])

    async def reanalyze(call: ServiceCall) -> None:
        await get_manager(hass).async_reanalyze(call.data[ATTR_ITEM])

    async def archive_event(call: ServiceCall) -> None:
        try:
            get_manager(hass).set_event_archived(call.data[ATTR_CHILD], call.data["event_id"], True)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def unarchive_event(call: ServiceCall) -> None:
        try:
            get_manager(hass).set_event_archived(call.data[ATTR_CHILD], call.data["event_id"], False)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

    async def rebuild_dashboard(call: ServiceCall) -> None:
        await dashboard.async_apply(hass, get_manager(hass), force=True)

    async def send_digest(call: ServiceCall) -> None:
        await get_manager(hass).async_send_digest(force=True)

    async def send_reminders(call: ServiceCall) -> ServiceResponse:
        return {"sent": await get_manager(hass).async_send_reminders()}

    async def get_overview(call: ServiceCall) -> ServiceResponse:
        """Übersicht für Skripte, Dashboards und Sprachassistenten."""
        m = get_manager(hass)
        only = call.data.get(ATTR_CHILD)
        out: dict[str, Any] = {"children": {}}
        for key, child in m.children.items():
            if only and key != only:
                continue
            s = m.child_summary(key)
            out["children"][key] = {
                "name": child["name"],
                "class": child.get("classname"),
                "school": child.get("school_name"),
                "status": s["ampel"],
                "open_tasks": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "type": t["type"],
                        "due": t.get("due"),
                        "amount": t.get("amount"),
                        "details": m.task_description(t),
                    }
                    for t in s["open_tasks"]
                ],
                "unread": [
                    {
                        "id": i["uid"],
                        "title": i["title"],
                        "kind": i["kind"],
                        "sent": i.get("sent"),
                        "summary": i.get("analysis", {}).get("summary"),
                    }
                    for i in s["unread"]
                ],
                "open_payments_total": s["payments_total"],
            }
        out["digest"] = m.digest_text()
        return out

    hass.services.async_register(DOMAIN, "refresh", refresh)
    hass.services.async_register(
        DOMAIN,
        "mark_read",
        mark_read,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ITEM): cv.string,
                vol.Optional(ATTR_CHILD): cv.string,
                vol.Optional("read", default=True): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "complete_task",
        complete_task,
        schema=vol.Schema(
            {vol.Required(ATTR_TASK): cv.string, vol.Optional("done", default=True): cv.boolean}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "add_task",
        add_task,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CHILD): cv.string,
                vol.Required("title"): cv.string,
                vol.Optional("due"): cv.date,
                vol.Optional("amount"): vol.Coerce(float),
                vol.Optional("details"): cv.string,
                vol.Optional("type", default="aufgabe"): vol.In(TASK_TYPES),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "update_task",
        update_task,
        schema=vol.Schema(
            {
                vol.Required(ATTR_TASK): cv.string,
                vol.Optional("status"): vol.In(TASK_STATUSES),
                vol.Optional("comment"): vol.Any(None, cv.string),
                vol.Optional("title"): cv.string,
                vol.Optional("details"): vol.Any(None, cv.string),
                vol.Optional("due"): vol.Any(None, cv.date),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "update_item",
        update_item,
        schema=vol.Schema(
            {vol.Required(ATTR_ITEM): cv.string, vol.Required("status"): vol.In(TASK_STATUSES)}
        ),
    )
    hass.services.async_register(
        DOMAIN, "reanalyze", reanalyze, schema=vol.Schema({vol.Required(ATTR_ITEM): cv.string})
    )
    event_schema = vol.Schema({vol.Required(ATTR_CHILD): cv.string, vol.Required("event_id"): cv.string})
    hass.services.async_register(DOMAIN, "archive_event", archive_event, schema=event_schema)
    hass.services.async_register(DOMAIN, "unarchive_event", unarchive_event, schema=event_schema)
    hass.services.async_register(DOMAIN, "send_digest", send_digest)
    hass.services.async_register(DOMAIN, "rebuild_dashboard", rebuild_dashboard)
    hass.services.async_register(
        DOMAIN, "send_reminders", send_reminders, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        "get_overview",
        get_overview,
        schema=vol.Schema({vol.Optional(ATTR_CHILD): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    LOGGER.debug("Schulmanager-Aktionen registriert")
