"""Gemeinsame Basis der Schulmanager-Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATED
from .manager import SchulManager


class SchulEntity(Entity):
    """Entität, die zu einem Kind gehört und bei Änderungen aktualisiert."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SchulManager, child: str, key: str) -> None:
        self.manager = manager
        self.child = child
        info = manager.children[child]
        self._attr_unique_id = f"{manager.entry.entry_id}_{child}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{manager.entry.entry_id}_{child}")},
            name=f"Schule {info['name']}",
            manufacturer=info.get("school_name"),
            model=f"Klasse {info['classname']}" if info.get("classname") else "Eltern-Portal",
            configuration_url=info.get("portal_url"),
            entry_type=DeviceEntryType.SERVICE,
        )

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
        if self.child in self.manager.children:
            self.async_write_ha_state()
