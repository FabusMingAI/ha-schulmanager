"""Kalender „Schule <Kind>“: Fristen, Termine aus Briefen, Schulaufgaben aus dem Portal."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SchulConfigEntry
from .entity import SchulEntity
from .manager import SchulManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchulConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(SchulCalendar(manager, child) for child in manager.children)


def _as_dt(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return dt_util.as_local(value)
    return dt_util.start_of_local_day(value)


class SchulCalendar(SchulEntity, CalendarEntity):
    """Kalender eines Kindes."""

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "kalender")
        self._attr_icon = "mdi:calendar-school"

    def _events(self) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                start=e["start"],
                end=e["end"],
                summary=e["summary"],
                description=e.get("description"),
                location=e.get("location"),
                uid=e["uid"],
            )
            for e in self.manager.child_events(self.child)
        ]

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [
            e for e in self._events() if _as_dt(e.end) > now
        ]
        upcoming.sort(key=lambda e: _as_dt(e.start))
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._events()
            if _as_dt(e.start) < end_date and _as_dt(e.end) > start_date
        ]


__all__ = ["SchulCalendar", "timedelta"]
