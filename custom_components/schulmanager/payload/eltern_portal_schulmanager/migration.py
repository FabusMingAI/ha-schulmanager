"""Übernahme bestehender „Schulmanager“-Installationen (Domain ``schulmanager``, bis 0.13).

Hintergrund (Issue #18): „Schulmanager Online“ (MrIcemanLE) nutzt dieselbe Domain
``schulmanager``. Seit 0.14 heißt die Integration „Eltern Portal Manager Bavaria“
mit der Domain ``eltern_portal_schulmanager``.

Home Assistant kann einen Config-Entry nicht in eine andere Domain verschieben. Beim
Hinzufügen der Integration erkennt der Einrichtungsdialog deshalb eine alte Einrichtung
(``legacy_entries``) und legt einen neuen Eintrag mit denselben Zugangsdaten und
Einstellungen an (``CONF_MIGRATED_FROM``). Bevor dessen Entitäten entstehen, übernimmt
``async_migrate``:

1. alten Eintrag entladen,
2. gespeicherte Daten (Aufgaben, Status, Archiv, Zusammenfassungen …) kopieren,
3. Entitäten und Geräte im Register umhängen – Entity-IDs und Verlauf bleiben,
4. abgelegte Dateien in den neuen Medienordner verschieben,
5. Dashboards auf die neuen Kartentypen umschreiben,
6. alte Dashboard-Ressource, ``www/schulmanager`` und den alten Integrationsordner
   (nur wenn er nachweislich zu diesem Projekt gehört) entfernen,
7. alten Eintrag löschen und eine Benachrichtigung zeigen.

Automationen und Skripte mit den alten Aktionen/Events werden nicht angefasst;
``async_check_legacy_references`` meldet sie als Reparatur-Hinweis, bis sie
umgestellt sind.

Einträge von „Schulmanager Online“ werden nie angefasst: Unsere Einträge erkennt man
an ``data["portals"]`` (Liste der Eltern-Portale).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CONF_PORTALS,
    DOMAIN,
    LEGACY_CARD_TYPES,
    LEGACY_CARD_URLS,
    LEGACY_DOMAIN,
    LEGACY_MEDIA_SUBDIR,
    LOGGER,
    MEDIA_SUBDIR,
    NAME,
    STORAGE_VERSION,
)

CONF_MIGRATED_FROM = "migrated_from"
REPO_MARKER = "FabusMingAI/ha-schulmanager"
ISSUE_LEGACY_REFERENCES = "legacy_references"

# Aktionen und Events, die es bis 0.13 unter „schulmanager“ gab
LEGACY_SERVICES = (
    "refresh",
    "mark_read",
    "complete_task",
    "update_task",
    "update_item",
    "add_task",
    "reanalyze",
    "archive_event",
    "unarchive_event",
    "send_digest",
    "send_reminders",
    "rebuild_dashboard",
    "get_overview",
)
LEGACY_EVENTS = ("new_item", "task_reminder", "substitution")

_SERVICE_RE = re.compile(
    rf"\b{LEGACY_DOMAIN}\.({'|'.join(LEGACY_SERVICES)})\b"
)
_EVENT_RE = re.compile(rf"\b{LEGACY_DOMAIN}_({'|'.join(LEGACY_EVENTS)})\b")


# ----------------------------------------------------------------------
# Alte Einrichtung finden
# ----------------------------------------------------------------------
def is_own_legacy_entry(entry: ConfigEntry) -> bool:
    """Gehört der ``schulmanager``-Eintrag zu diesem Projekt (nicht Schulmanager Online)?"""
    portals = entry.data.get(CONF_PORTALS)
    return isinstance(portals, list) and bool(portals)


def legacy_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [
        e for e in hass.config_entries.async_entries(LEGACY_DOMAIN) if is_own_legacy_entry(e)
    ]


def replace_legacy_names(text: str) -> str:
    """Alte Kartentypen, Aktionen, Pfade und Events in einem Text auf die neuen umstellen."""
    for old, new in LEGACY_CARD_TYPES.items():
        text = re.sub(rf"{re.escape(old)}(?![\w-])", new, text)
    text = text.replace(
        f"/config/integrations/integration/{LEGACY_DOMAIN}\"",
        f"/config/integrations/integration/{DOMAIN}\"",
    )
    text = text.replace(f"/local/{LEGACY_DOMAIN}/icon.png", f"/local/{DOMAIN}/icon.png")
    text = _SERVICE_RE.sub(lambda m: f"{DOMAIN}.{m[1]}", text)
    return _EVENT_RE.sub(lambda m: f"{DOMAIN}_{m[1]}", text)


def rewrite_config(config: Any) -> Any:
    """Dashboard-Konfiguration (dict/list) mit den neuen Namen."""
    return json.loads(replace_legacy_names(json.dumps(config, ensure_ascii=False)))


# ----------------------------------------------------------------------
# Übernahme
# ----------------------------------------------------------------------
async def async_migrate(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any] | None:
    """Alte Einrichtung in ``entry`` übernehmen. Liefert die gespeicherten Daten."""
    old_id = entry.data.get(CONF_MIGRATED_FROM)
    if not old_id:
        return None
    old = hass.config_entries.async_get_entry(old_id)
    LOGGER.info("Übernehme die Einrichtung von „Schulmanager“ (%s) in %s", old_id, NAME)

    was_loaded = old is not None and old.state is ConfigEntryState.LOADED
    if was_loaded:
        try:
            await hass.config_entries.async_unload(old_id)
        except Exception:  # noqa: BLE001 - alter Code kann fehlschlagen
            LOGGER.warning("Alte Einrichtung ließ sich nicht entladen", exc_info=True)

    old_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{LEGACY_DOMAIN}.{old_id}")
    data = await old_store.async_load()
    _move_registry(hass, old_id, entry.entry_id)
    if data is not None:
        await _async_move_media(hass, data)
    else:
        LOGGER.warning("Keine gespeicherten Daten der alten Einrichtung gefunden")
    dashboards = await _async_rewrite_dashboards(hass, data)
    if data is not None:
        # Die alte Datei bleibt als Sicherung in .storage liegen.
        new_store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        await new_store.async_save(data)
    await _async_cleanup_frontend(hass)

    if old is not None:
        try:
            await hass.config_entries.async_remove(old_id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("Alte Einrichtung ließ sich nicht entfernen", exc_info=True)
    removed_folder = await hass.async_add_executor_job(_remove_legacy_folder, hass)

    new_data = {k: v for k, v in entry.data.items() if k != CONF_MIGRATED_FROM}
    hass.config_entries.async_update_entry(entry, data=new_data)

    from homeassistant.components import persistent_notification

    lines = [
        f"„Schulmanager“ heißt jetzt **{NAME}**. Einstellungen, Aufgaben, Mitteilungen, "
        "Archiv, Entitäten und Verlauf wurden übernommen.",
    ]
    if dashboards:
        lines.append(f"Dashboards umgestellt: {', '.join(dashboards)}.")
    lines.append(
        "Bitte **Home Assistant neu starten**, damit der alte Code nicht mehr im Speicher bleibt."
        if removed_folder or was_loaded
        else "Ein Neustart von Home Assistant ist empfohlen."
    )
    lines.append(
        f"Automationen oder Skripte mit `{LEGACY_DOMAIN}.…`-Aktionen oder "
        f"`{LEGACY_DOMAIN}_…`-Events bitte auf `{DOMAIN}.…` bzw. `{DOMAIN}_…` umstellen – "
        "betroffene stehen unter Einstellungen → Reparaturen."
    )
    persistent_notification.async_create(
        hass, "\n\n".join(lines), title=NAME, notification_id=f"{DOMAIN}_migration"
    )
    return data


def _new_unique_id(unique_id: str, old_id: str, new_id: str) -> str:
    return new_id + unique_id[len(old_id):] if unique_id.startswith(old_id) else unique_id


@callback
def _move_registry(hass: HomeAssistant, old_id: str, new_id: str) -> None:
    """Geräte und Entitäten auf den neuen Eintrag umhängen (Entity-IDs bleiben)."""
    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, old_id):
        identifiers = {
            (DOMAIN, _new_unique_id(ident, old_id, new_id)) if domain == LEGACY_DOMAIN else (domain, ident)
            for domain, ident in device.identifiers
        }
        dev_reg.async_update_device(
            device.id, new_identifiers=identifiers, add_config_entry_id=new_id
        )
        dev_reg.async_update_device(device.id, remove_config_entry_id=old_id)

    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, old_id):
        # Zustand des entladenen bzw. nie geladenen Eintrags („nicht verfügbar“) entfernen,
        # sonst lässt das Register die Übernahme nicht zu.
        hass.states.async_remove(ent.entity_id)
        new_uid = _new_unique_id(ent.unique_id, old_id, new_id)
        if ent_reg.async_get_entity_id(ent.domain, DOMAIN, new_uid):
            LOGGER.debug("%s existiert schon unter %s", ent.entity_id, DOMAIN)
            continue
        try:
            ent_reg.async_update_entity_platform(
                ent.entity_id,
                DOMAIN,
                new_config_entry_id=new_id,
                new_unique_id=new_uid,
            )
        except ValueError:
            LOGGER.warning("Entität %s ließ sich nicht übernehmen", ent.entity_id, exc_info=True)


def _media_base(hass: HomeAssistant) -> str:
    dirs = hass.config.media_dirs or {}
    if "local" in dirs:
        return dirs["local"]
    if dirs:
        return next(iter(dirs.values()))
    return hass.config.path("media")


async def _async_move_media(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Abgelegte Dateien von ``schulmanager/…`` nach ``eltern_portal_schulmanager/…``."""
    base = _media_base(hass)
    prefix = LEGACY_MEDIA_SUBDIR + os.sep

    def _move() -> int:
        moved = 0
        for item in data.get("items", {}).values():
            for meta in item.get("files", []):
                rel = meta.get("path") or ""
                if not rel.startswith(prefix):
                    continue
                new_rel = MEDIA_SUBDIR + os.sep + rel[len(prefix):]
                src, dst = os.path.join(base, rel), os.path.join(base, new_rel)
                try:
                    if os.path.isfile(src) and not os.path.exists(dst):
                        os.renames(src, dst)  # entfernt leer gewordene alte Ordner
                    if os.path.isfile(dst):
                        meta["path"] = new_rel
                        moved += 1
                except OSError:
                    LOGGER.warning("Datei %s ließ sich nicht verschieben", rel, exc_info=True)
        return moved

    moved = await hass.async_add_executor_job(_move)
    if moved:
        LOGGER.info("%d abgelegte Dateien in den Medienordner „%s“ verschoben", moved, MEDIA_SUBDIR)


async def _async_rewrite_dashboards(
    hass: HomeAssistant, data: dict[str, Any] | None
) -> list[str]:
    """Kartentypen ``custom:schulmanager-*`` in allen Dashboards (Speichermodus) ersetzen."""
    from .dashboard import _hash  # noqa: PLC0415 - Zyklus vermeiden
    from .const import DASHBOARD_URL  # noqa: PLC0415

    lovelace = hass.data.get("lovelace")
    dashboards = getattr(lovelace, "dashboards", None) or {}
    changed: list[str] = []
    for url_path, dash in list(dashboards.items()):
        if getattr(dash, "mode", None) != "storage" or not hasattr(dash, "async_save"):
            continue
        try:
            config = await dash.async_load(False)
        except Exception:  # noqa: BLE001 - leeres Dashboard
            continue
        if not config:
            continue
        new = rewrite_config(config)
        if new == config:
            continue
        await dash.async_save(new)
        changed.append(
            (getattr(dash, "config", None) or {}).get("title") or url_path or "Übersicht"
        )
        if url_path == DASHBOARD_URL and data is not None:
            # Unverändertes, von der Integration erzeugtes Dashboard bleibt „unverändert“,
            # damit es danach wieder automatisch aktualisiert wird.
            state = data.setdefault("dashboard", {})
            if state.get("hash") == _hash(config):
                state["hash"] = _hash(new)
    if changed:
        LOGGER.info("Dashboards auf die neuen Kartentypen umgestellt: %s", ", ".join(changed))
    return changed


async def _async_cleanup_frontend(hass: HomeAssistant) -> None:
    """Alte Dashboard-Ressource und den alten Ordner unter /config/www entfernen."""
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is not None and hasattr(resources, "async_delete_item"):
        try:
            if not getattr(resources, "loaded", True):
                await resources.async_load()
                resources.loaded = True
            for item in list(resources.async_items()):
                if str(item.get("url", "")).split("?")[0] in LEGACY_CARD_URLS:
                    await resources.async_delete_item(item["id"])
        except Exception:  # noqa: BLE001
            LOGGER.warning("Alte Dashboard-Ressource ließ sich nicht entfernen", exc_info=True)

    def _www() -> None:
        old = hass.config.path("www", LEGACY_DOMAIN)
        if not os.path.isdir(old):
            return
        ours = {"schulmanager-card.js", "schulmanager-card.txt", "icon.png"}
        if set(os.listdir(old)) <= ours:
            shutil.rmtree(old, ignore_errors=True)

    await hass.async_add_executor_job(_www)


def _remove_legacy_folder(hass: HomeAssistant) -> bool:
    """Alten Ordner custom_components/schulmanager löschen – nur wenn er von uns ist.

    HACS legt nach dem Update den neuen Ordner an, lässt den alten aber liegen. Bliebe er,
    würde Home Assistant den alten Code weiter laden und „Schulmanager Online“ ließe sich
    weiterhin nicht installieren.
    """
    folder = hass.config.path("custom_components", LEGACY_DOMAIN)
    manifest = os.path.join(folder, "manifest.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            info = json.load(fh)
    except (OSError, ValueError):
        return False
    text = " ".join(str(info.get(k, "")) for k in ("documentation", "issue_tracker", "codeowners"))
    if info.get("domain") != LEGACY_DOMAIN or REPO_MARKER.lower() not in text.lower():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    LOGGER.info("Alten Ordner %s entfernt", folder)
    return True


async def async_remove_leftover_bridge(hass: HomeAssistant) -> bool:
    """Übrig gebliebenen Ordner der Brücken-Version (0.14.1, Domain ``schulmanager``) entfernen.

    HACS installiert die Brücke auch dort, wo die Übernahme schon erledigt ist. Solange
    keine eigene alte Einrichtung mehr existiert, wird der Ordner nicht mehr gebraucht –
    und er würde „Schulmanager Online“ im Weg stehen. Fremde Ordner bleiben unangetastet.
    """
    if legacy_entries(hass):
        return False
    return await hass.async_add_executor_job(_remove_legacy_folder, hass)


# ----------------------------------------------------------------------
# Reparatur-Hinweis: Automationen und Skripte mit alten Namen
# ----------------------------------------------------------------------
def _configs(hass: HomeAssistant, domain: str) -> list[tuple[str, str, Any]]:
    component = hass.data.get(domain)
    out: list[tuple[str, str, Any]] = []
    for ent in getattr(component, "entities", []) or []:
        raw = getattr(ent, "raw_config", None)
        if raw:
            name = getattr(ent, "name", None) or ent.entity_id
            out.append((ent.entity_id, str(name), raw))
    return out


@callback
def find_legacy_references(hass: HomeAssistant) -> list[str]:
    """Automationen und Skripte, die noch alte Aktionen oder Events nutzen."""
    found: list[str] = []
    if hass.config_entries.async_entries(LEGACY_DOMAIN):
        # Eine andere Integration mit der Domain „schulmanager“ (z. B. Schulmanager Online)
        # ist installiert: Aufrufe könnten ihr gehören, nur eindeutige Fälle melden.
        services = re.compile(
            rf"\b{LEGACY_DOMAIN}\.({'|'.join(s for s in LEGACY_SERVICES if s != 'refresh')})\b"
        )
    else:
        services = _SERVICE_RE
    for domain in ("automation", "script"):
        for entity_id, name, raw in _configs(hass, domain):
            text = json.dumps(raw, ensure_ascii=False, default=str)
            if services.search(text) or _EVENT_RE.search(text):
                found.append(f"{name} ({entity_id})")
    return sorted(found)


@callback
def async_check_legacy_references(hass: HomeAssistant) -> None:
    found = find_legacy_references(hass)
    if not found:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LEGACY_REFERENCES)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_LEGACY_REFERENCES,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_LEGACY_REFERENCES,
        translation_placeholders={
            "items": "\n".join(f"- {f}" for f in found),
            "old_domain": LEGACY_DOMAIN,
            "new_domain": DOMAIN,
        },
        learn_more_url="https://github.com/FabusMingAI/ha-schulmanager#renamed-from-schulmanager",
    )


@callback
def async_watch_legacy_references(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Nach dem Start und nach jedem Neuladen von Automationen/Skripten prüfen."""

    @callback
    def _check(_: Any = None) -> None:
        async_check_legacy_references(hass)

    @callback
    def _later(_: Event | None = None) -> None:
        entry.async_on_unload(async_call_later(hass, 2, _check))

    @callback
    def _on_service(event: Event) -> None:
        if event.data.get("service") in ("reload", "reload_all") and event.data.get(
            "domain"
        ) in ("script", "automation", "homeassistant"):
            _later()

    entry.async_on_unload(hass.bus.async_listen("automation_reloaded", _later))
    entry.async_on_unload(hass.bus.async_listen("call_service", _on_service))
    if hass.state is CoreState.running:
        _later()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _later)
        )


__all__ = [
    "CONF_MIGRATED_FROM",
    "async_check_legacy_references",
    "async_migrate",
    "async_watch_legacy_references",
    "find_legacy_references",
    "legacy_entries",
    "replace_legacy_names",
    "rewrite_config",
]
