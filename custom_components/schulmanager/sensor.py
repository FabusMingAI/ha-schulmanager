"""Sensoren: Ampel, offene Aufgaben, Fristen, Zahlungen, ungelesene Mitteilungen."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SchulConfigEntry, file_url
from .analyzer import fmt_eur
from .const import (
    AMPEL_GREEN,
    AMPEL_RED,
    AMPEL_YELLOW,
    DOMAIN,
    KIND_LABELS,
    SIGNAL_UPDATED,
    TASK_TYPE_ICONS,
)
from .entity import SchulEntity
from .manager import SchulManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchulConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    entities: list[SensorEntity] = [SchulUpdateSensor(manager)]
    for child in manager.children:
        entities += [
            AmpelSensor(manager, child),
            OpenTasksSensor(manager, child),
            OverdueSensor(manager, child),
            NextDueSensor(manager, child),
            PaymentsSensor(manager, child),
            UnreadSensor(manager, child),
        ]
    async_add_entities(entities)


def _task_attr(m: SchulManager, t: dict[str, Any]) -> dict[str, Any]:
    today = dt_util.now().date()
    days = (date.fromisoformat(t["due"]) - today).days if t.get("due") else None
    return {
        "id": t["id"],
        "titel": t["title"],
        "anzeige": f"{TASK_TYPE_ICONS.get(t['type'], '✅')} {m.task_label(t)}",
        "typ": t["type"],
        "faellig": t.get("due"),
        "tage": days,
        "betrag": t.get("amount"),
        "iban": t.get("iban"),
        "verwendungszweck": t.get("reference"),
        "details": t.get("details"),
        "quelle": t.get("source"),
        "portal": m.items.get(t.get("item_uid") or "", {}).get("url"),
    }


def _item_attr(hass: HomeAssistant, i: dict[str, Any]) -> dict[str, Any]:
    a = i.get("analysis", {})
    return {
        "id": i["uid"],
        "art": KIND_LABELS.get(i["kind"], i["kind"]),
        "titel": i["title"],
        "datum": i.get("sent"),
        "von": i.get("sender"),
        "zusammenfassung": a.get("summary"),
        "dringlichkeit": a.get("urgency"),
        "auswertung": a.get("status"),
        "gelesen": bool(i.get("read")),
        "portal": i["url"],
        "dateien": [
            {"name": f["path"].rsplit("/", 1)[-1], "url": file_url(hass, i["uid"], n)}
            for n, f in enumerate(i.get("files", []))
        ],
    }


class AmpelSensor(SchulEntity, SensorEntity):
    """Rot / Gelb / Grün pro Kind – mit allen Details als Attribute."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [AMPEL_GREEN, AMPEL_YELLOW, AMPEL_RED]
    _unrecorded_attributes = frozenset(
        {"aufgaben", "mitteilungen", "ungelesen", "zahlungen"}
    )

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "ampel")

    @property
    def native_value(self) -> str:
        return self.manager.child_summary(self.child)["ampel"]

    @property
    def icon(self) -> str:
        return {
            AMPEL_RED: "mdi:alert-circle",
            AMPEL_YELLOW: "mdi:clipboard-text-clock",
            AMPEL_GREEN: "mdi:check-circle",
        }[self.native_value]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        m = self.manager
        s = m.child_summary(self.child)
        info = m.children[self.child]
        return {
            "kind": info["name"],
            "klasse": info.get("classname"),
            "schule": info.get("school_name"),
            "portal": info.get("portal_url"),
            "anzahl_offen": len(s["open_tasks"]),
            "anzahl_ueberfaellig": len(s["overdue"]),
            "anzahl_ungelesen": len(s["unread"]),
            "zahlungen_summe": s["payments_total"],
            "aufgaben": [_task_attr(m, t) for t in s["open_tasks"]],
            "ungelesen": [_item_attr(self.hass, i) for i in s["unread"][:15]],
            "mitteilungen": [_item_attr(self.hass, i) for i in m.child_items(self.child)[:25]],
        }


class OpenTasksSensor(SchulEntity, SensorEntity):
    _attr_icon = "mdi:format-list-checks"
    _attr_native_unit_of_measurement = "Aufgaben"

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "offene_aufgaben")

    @property
    def native_value(self) -> int:
        return len(self.manager.child_tasks(self.child))


class OverdueSensor(SchulEntity, SensorEntity):
    _attr_icon = "mdi:calendar-alert"
    _attr_native_unit_of_measurement = "Aufgaben"

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "ueberfaellig")

    @property
    def native_value(self) -> int:
        return len(self.manager.child_summary(self.child)["overdue"])


class NextDueSensor(SchulEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "naechste_frist")

    @property
    def native_value(self) -> date | None:
        t = self.manager.child_summary(self.child)["next_task"]
        return date.fromisoformat(t["due"]) if t else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = self.manager.child_summary(self.child)["next_task"]
        return {"aufgabe": self.manager.task_label(t) if t else None}


class PaymentsSensor(SchulEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:cash-clock"
    _unrecorded_attributes = frozenset({"zahlungen"})

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "offene_zahlungen")

    @property
    def native_value(self) -> float:
        return self.manager.child_summary(self.child)["payments_total"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.manager.child_summary(self.child)
        return {
            "zahlungen": [
                {
                    "titel": t["title"],
                    "betrag": fmt_eur(t.get("amount")),
                    "faellig": t.get("due"),
                    "empfaenger": t.get("payee"),
                    "iban": t.get("iban"),
                    "verwendungszweck": t.get("reference"),
                }
                for t in s["payments"]
            ]
        }


class UnreadSensor(SchulEntity, SensorEntity):
    _attr_icon = "mdi:email-alert"
    _attr_native_unit_of_measurement = "Mitteilungen"

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "ungelesen")

    @property
    def native_value(self) -> int:
        return len(self.manager.child_summary(self.child)["unread"])


class SchulUpdateSensor(SensorEntity):
    """Letzter Abruf aller Portale (Diagnose)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "letzter_abruf"

    def __init__(self, manager: SchulManager) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_letzter_abruf"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, manager.entry.entry_id)},
            "name": "Schulmanager",
            "manufacturer": "Eltern-Portal",
            "entry_type": DeviceEntryType.SERVICE,
        }

    @property
    def native_value(self) -> datetime | None:
        return self.manager.last_update

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pending = sum(
            1 for i in self.manager.items.values()
            if i.get("analysis", {}).get("status") == "pending"
        )
        return {
            "fehler": self.manager.last_errors,
            "auswertung_ausstehend": pending,
            "mitteilungen_gesamt": len(self.manager.items),
            "kinder": [c["name"] for c in self.manager.children.values()],
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATED}_{self.manager.entry.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
