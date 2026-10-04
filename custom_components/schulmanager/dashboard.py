"""Dashboard „Schule“ automatisch anlegen und aktuell halten.

Die Ansicht wird in den Einstellungen der Integration gewählt:

* ``tabs``   – Reiter „Übersicht“ (Kalender + Schulmanager) und ein Reiter je Kind
* ``single`` – alles auf einer Seite
* ``off``    – das Dashboard wird nicht angefasst

Von Hand geänderte Dashboards werden geschützt: Der Schulmanager überschreibt
nur, was er selbst erzeugt hat, oder wenn in den Einstellungen bewusst eine
andere Ansicht gewählt bzw. die Aktion ``schulmanager.rebuild_dashboard``
aufgerufen wird.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DASHBOARD,
    DASHBOARD_ICON,
    DASHBOARD_MODES,
    DASHBOARD_OFF,
    DASHBOARD_SINGLE,
    DASHBOARD_TABS,
    DASHBOARD_TITLE,
    DASHBOARD_URL,
    DEFAULT_DASHBOARD,
    DOMAIN,
    LOCAL_ICON_URL,
    LOGGER,
)

if TYPE_CHECKING:
    from .manager import SchulManager


# ----------------------------------------------------------------------
# Konfiguration erzeugen
# ----------------------------------------------------------------------
def _eid(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


def _child_entities(hass: HomeAssistant, manager: SchulManager, key: str) -> dict[str, str | None]:
    base = f"{manager.entry.entry_id}_{key}"
    return {
        "status": _eid(hass, "sensor", f"{base}_ampel"),
        "calendar": _eid(hass, "calendar", f"{base}_kalender"),
        "todo": _eid(hass, "todo", f"{base}_aufgaben"),
    }


def _header(names: list[str]) -> dict[str, Any]:
    subtitle = " & ".join(names) if names else "Eltern-Portal"
    return {
        "layout": "responsive",
        "card": {
            "type": "markdown",
            "text_only": True,
            "content": (
                f'# <img src="{LOCAL_ICON_URL}" width="44" height="44"> Schulmanager\n'
                f"{subtitle} · Eltern-Portal, Aufgaben und Fristen"
            ),
        },
    }


def _schulmanager_card(
    hass: HomeAssistant, manager: SchulManager, links: bool, title: bool = True
) -> dict[str, Any]:
    """Entitäten-Karte „Schulmanager“: letzter Abruf und Aktionen.

    Die Kinder stehen nicht mehr als eigene Zeilen darin – dafür gibt es die
    Reiter bzw. die Schulmanager-Karte je Kind.
    """
    rows: list[Any] = []
    if last := _eid(hass, "sensor", f"{manager.entry.entry_id}_letzter_abruf"):
        rows.append(last)
    rows += [
        {
            "type": "button",
            "name": "Portale jetzt abrufen",
            "icon": "mdi:refresh",
            "action_name": "Abrufen",
            "tap_action": {"action": "perform-action", "perform_action": f"{DOMAIN}.refresh"},
        },
        {
            "type": "button",
            "name": "Tagesübersicht jetzt senden",
            "icon": "mdi:cellphone-message",
            "action_name": "Senden",
            "tap_action": {"action": "perform-action", "perform_action": f"{DOMAIN}.send_digest"},
        },
    ]
    card: dict[str, Any] = {"type": "entities", "entities": rows}
    if title:
        card["title"] = "Schulmanager"
    return card


def _termine(child: str | None = None) -> dict[str, Any]:
    """Terminliste mit KI-Kurzbeschreibung beim Überfahren und Legende."""
    card: dict[str, Any] = {"type": "custom:schulmanager-termine", "grid_options": {"columns": 12}}
    if child:
        card["child"] = child
    return card


def _stundenplan(child: str) -> dict[str, Any]:
    return {"type": "custom:schulmanager-stundenplan", "child": child, "grid_options": {"columns": 12}}


def _portal_button(child: dict[str, Any]) -> dict[str, Any] | None:
    url = child.get("portal_url")
    if not url:
        return None
    return {
        "type": "button",
        "name": "Eltern-Portal öffnen",
        "icon": "mdi:open-in-new",
        "show_icon": True,
        "grid_options": {"columns": 12, "rows": 1},
        "tap_action": {"action": "url", "url_path": url},
    }


def build_config(hass: HomeAssistant, manager: SchulManager, mode: str) -> dict[str, Any]:
    """Lovelace-Konfiguration für die gewählte Ansicht."""
    children = manager.children
    names = [c["name"] for c in children.values()]

    if mode == DASHBOARD_SINGLE:
        sections: list[dict[str, Any]] = []
        for key, child in children.items():
            cards: list[dict[str, Any]] = [
                {"type": "custom:schulmanager-card", "child": key, "grid_options": {"columns": 12}},
                _stundenplan(key),
            ]
            if btn := _portal_button(child):
                cards.append(btn)
            sections.append({"type": "grid", "cards": cards})
        sections.append(
            {
                "type": "grid",
                "column_span": 2,
                "cards": [_termine(), _schulmanager_card(hass, manager, links=False)],
            }
        )
        view = {
            "title": "Übersicht",
            "path": "uebersicht",
            "icon": DASHBOARD_ICON,
            "type": "sections",
            "max_columns": 2,
            "header": _header(names),
            "sections": sections,
        }
        return {"title": DASHBOARD_TITLE, "views": [view]}

    # Reiter: Übersicht + je Kind
    views: list[dict[str, Any]] = [
        {
            "title": "Übersicht",
            "path": "uebersicht",
            "type": "sections",
            "max_columns": 2,
            "header": _header(names),
            "sections": [
                {
                    "type": "grid",
                    "cards": [
                        {"type": "heading", "heading": "Termine & Fristen", "icon": "mdi:calendar"},
                        _termine(),
                    ],
                },
                {
                    # Rechte Spalte: Stundenplan je Kind (seit 0.7.1 statt der Schulmanager-Karte)
                    "type": "grid",
                    "cards": [
                        card
                        for key, child in children.items()
                        for card in (
                            {
                                "type": "heading",
                                "heading": f"Stundenplan {child['name']}",
                                "icon": "mdi:timetable",
                            },
                            _stundenplan(key),
                        )
                    ],
                },
            ],
        }
    ]
    for key, child in children.items():
        side: list[dict[str, Any]] = [
            {"type": "heading", "heading": "Stundenplan & Vertretungen", "icon": "mdi:timetable"},
            _stundenplan(key),
            {"type": "heading", "heading": "Termine & Fristen", "icon": "mdi:calendar"},
            _termine(key),
        ]
        if btn := _portal_button(child):
            side.append(btn)
        sections = [
            {
                "type": "grid",
                "cards": [
                    {"type": "custom:schulmanager-card", "child": key, "grid_options": {"columns": 12}}
                ],
            }
        ]
        if side:
            sections.append({"type": "grid", "cards": side})
        views.append(
            {
                "title": child["name"],
                "path": key,
                "type": "sections",
                "max_columns": 2,
                "sections": sections,
            }
        )
    return {"title": DASHBOARD_TITLE, "views": views}


def _hash(config: dict[str, Any] | None) -> str | None:
    if not config:
        return None
    return hashlib.sha1(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ----------------------------------------------------------------------
# Dashboard speichern
# ----------------------------------------------------------------------
def _dashboards_collection(hass: HomeAssistant) -> Any:
    """Die Dashboard-Sammlung von Lovelace (zum Anlegen eines neuen Dashboards)."""
    handlers = hass.data.get("websocket_api", {})
    entry = handlers.get("lovelace/dashboards/create")
    if not entry:
        return None
    func = inspect.unwrap(entry[0])
    return getattr(getattr(func, "__self__", None), "storage_collection", None)


async def _async_get_dashboard(hass: HomeAssistant, create: bool) -> Any:
    lovelace = hass.data.get("lovelace")
    dashboards = getattr(lovelace, "dashboards", None)
    if dashboards is None:
        return None
    dash = dashboards.get(DASHBOARD_URL)
    if dash is None and create:
        collection = _dashboards_collection(hass)
        if collection is None:
            LOGGER.warning("Dashboard „%s“ konnte nicht angelegt werden", DASHBOARD_URL)
            return None
        await collection.async_create_item(
            {
                "url_path": DASHBOARD_URL,
                "title": DASHBOARD_TITLE,
                "icon": DASHBOARD_ICON,
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
        )
        dash = dashboards.get(DASHBOARD_URL)
    if dash is None or not hasattr(dash, "async_save") or getattr(dash, "mode", "storage") != "storage":
        return None
    return dash


async def async_apply(hass: HomeAssistant, manager: SchulManager, force: bool = False) -> bool:
    """Dashboard passend zur gewählten Ansicht schreiben. Gibt True zurück, wenn gespeichert."""
    mode = manager.opt(CONF_DASHBOARD)
    if mode not in DASHBOARD_MODES:
        mode = None
    effective = mode or DEFAULT_DASHBOARD
    if effective == DASHBOARD_OFF or not manager.children:
        return False
    try:
        dash = await _async_get_dashboard(hass, create=True)
        if dash is None:
            return False
        try:
            current = await dash.async_load(False)
        except Exception:  # noqa: BLE001 - ConfigNotFound: noch leer
            current = None
        state = manager.data.setdefault("dashboard", {})
        new = build_config(hass, manager, effective)
        if _hash(new) == _hash(current):
            state.update(hash=_hash(new), mode=mode)
            return False
        allowed = (
            force
            or not current
            or _hash(current) == state.get("hash")
            or (mode is not None and state.get("mode") != mode)
        )
        if not allowed:
            LOGGER.info(
                "Dashboard „%s“ wurde von Hand angepasst und bleibt unverändert "
                "(neu erzeugen: Aktion %s.rebuild_dashboard)",
                DASHBOARD_URL,
                DOMAIN,
            )
            return False
        await dash.async_save(new)
        state.update(hash=_hash(new), mode=mode)
        manager.data["dashboard"] = state
        manager.store.async_delay_save(lambda: manager.data, 2)
        LOGGER.debug("Dashboard „%s“ aktualisiert (%s)", DASHBOARD_URL, effective)
        return True
    except Exception:  # noqa: BLE001
        LOGGER.warning("Dashboard „%s“ konnte nicht aktualisiert werden", DASHBOARD_URL, exc_info=True)
        return False


__all__ = ["DASHBOARD_TABS", "async_apply", "build_config"]
