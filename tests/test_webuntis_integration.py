"""Optional calendar configuration and real HA calendar-service integration."""

from copy import deepcopy
from datetime import datetime, time, timedelta
import json
import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, CoreState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.exceptions import HomeAssistantError
from homeassistant.data_entry_flow import InvalidData
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.eltern_portal_schulmanager.const import CONF_WEBUNTIS_CALENDARS, DOMAIN, EVENT_SUBSTITUTION
from custom_components.eltern_portal_schulmanager.manager import SchulManager
from custom_components.eltern_portal_schulmanager.portal import PortalChild, PortalResult


@pytest.fixture(autouse=True)
def custom_integrations(hass, enable_custom_integrations):
    hass.config.language = "de"
    hass.state = CoreState.running
    yield


class FixtureCalendar(CalendarEntity):
    _attr_name = "WebUntis Demo"
    _attr_unique_id = "webuntis-demo"
    _attr_should_poll = False
    entity_id = "calendar.webuntis_demo"

    def __init__(self):
        self.events = []
        self.calls = 0
        self.error = None

    @property
    def event(self):
        return None

    async def async_get_events(self, hass, start_date, end_date):
        self.calls += 1
        if self.error:
            raise self.error
        return [event for event in self.events if event.end > start_date and event.start < end_date]


@pytest.fixture
async def source(hass):
    assert await async_setup_component(hass, "calendar", {})
    calendar = FixtureCalendar()
    day = dt_util.start_of_local_day() + timedelta(days=1)
    raw = json.loads((Path(__file__).parent / "fixtures/webuntis/events.json").read_text())
    calendar.events = [
        CalendarEvent(
            start=day + timedelta(hours=8 + i), end=day + timedelta(hours=8 + i, minutes=45),
            summary=event["summary"], description=event["description"],
        ) for i, event in enumerate(raw)
    ]
    await hass.data["calendar"].async_add_entities([calendar])
    await hass.async_block_till_done()
    return calendar


def portal_result():
    return PortalResult(
        school="demo", school_name="Demo", base_url="https://demo.eltern-portal.org/",
        children=[PortalChild(student_id=name, firstname=name, fullname=name, classname="5a") for name in ("Anna", "Ben")],
    )


async def setup_manager(hass, options=None):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={
        "portals": [{"school": "demo", "school_name": "Demo", "username": "demo", "password": "demo"}],
    }, options=options or {})
    entry.add_to_hass(hass)
    with patch.object(SchulManager, "_async_fetch_portal", return_value=portal_result()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, entry.runtime_data


async def refresh(manager):
    with patch.object(SchulManager, "_async_fetch_portal", return_value=portal_result()):
        await manager.async_refresh()
        await manager.hass.async_block_till_done()


def changed(manager, child="anna"):
    return [e for day in manager.child_substitutions(child) for e in day["entries"]]


async def test_no_calendar_configured_does_not_query_webuntis(hass, source):
    _, manager = await setup_manager(hass)
    calls = source.calls
    await refresh(manager)
    assert source.calls == calls
    assert changed(manager) == [] and manager.last_errors == []


async def test_calendar_service_to_child_sensor_and_events(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    entries = changed(manager)
    assert [e["kind"] for e in entries] == ["entfall", "vertretung", "raum"]
    assert changed(manager, "ben") == []
    assert source.calls > 0
    assert hass.states.get("sensor.schule_anna_vertretungen").state == "3"
    events = [e for e in manager.child_events("anna") if e["category"] in ("entfall", "vertretung", "raum")]
    assert len(events) == 3 and all(e["start"].tzinfo is not None for e in events)
    assert events[1]["start"] == source.events[2].start
    assert events[1]["end"] == source.events[2].end
    assert manager.last_errors == []


async def test_changes_removals_failures_and_notifications(hass, source):
    notifications = async_capture_events(hass, EVENT_SUBSTITUTION)
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    assert notifications == []  # No flood on initial import.
    before = deepcopy(changed(manager))
    source.error = HomeAssistantError("Calendar offline")
    await refresh(manager)
    assert changed(manager) == before and "Calendar offline" in manager.last_errors[0]
    source.error = None
    description = json.loads(source.events[2].description)
    description["rooms"] = [{"name": "NEW-ROOM"}]
    source.events[2] = CalendarEvent(start=source.events[2].start, end=source.events[2].end,
                                   summary="Changed", description=json.dumps(description))
    await refresh(manager)
    assert len(notifications) == 1
    assert changed(manager)[1]["room"] == "NEW-ROOM"
    assert changed(manager)[1]["uid"] == before[1]["uid"]
    await refresh(manager)
    assert len(notifications) == 1  # Unchanged records are not notified again.
    source.events = []
    await refresh(manager)
    assert changed(manager) == [] and manager.last_errors == []
    assert hass.states.get("sensor.schule_anna_vertretungen").state == "0"


async def test_unavailable_or_non_json_calendar_preserves_previous_data(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    before = deepcopy(changed(manager))
    source._attr_available = False
    source.async_write_ha_state()
    await refresh(manager)
    assert changed(manager) == before and manager.last_errors
    source._attr_available = True
    source.events = [CalendarEvent(start=source.events[0].start, end=source.events[0].end,
                                  summary="Wrong source format", description="plain text")]
    source.async_write_ha_state()
    await refresh(manager)
    assert changed(manager) == before and "JSON" in manager.last_errors[0]


async def test_options_assign_and_remove_calendar_per_child(hass, source):
    entry, manager = await setup_manager(hass, {"reminder_days": "2,0"})
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert "webuntis" in flow["menu_options"]
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "webuntis"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"child": "anna"})
    assert flow["step_id"] == "webuntis_calendar"
    own_id = "calendar.schule_anna_kalender"
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(flow["flow_id"], {"calendar": own_id})
    invalid = await hass.config_entries.options.async_configure(flow["flow_id"], {"calendar": "calendar.missing"})
    assert invalid["errors"]["calendar"] == "webuntis_invalid_calendar"
    with patch.object(SchulManager, "_async_fetch_portal", return_value=portal_result()):
        result = await hass.config_entries.options.async_configure(flow["flow_id"], {"calendar": source.entity_id})
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options[CONF_WEBUNTIS_CALENDARS] == {"anna": source.entity_id}
    assert entry.options["reminder_days"] == "2,0"
    assert len(changed(entry.runtime_data)) == 3
    # Editing unrelated settings must retain the optional source mapping.
    general = await hass.config_entries.options.async_init(entry.entry_id)
    general = await hass.config_entries.options.async_configure(general["flow_id"], {"next_step_id": "settings"})
    with patch.object(SchulManager, "_async_fetch_portal", return_value=portal_result()):
        await hass.config_entries.options.async_configure(general["flow_id"], {"dashboard": {"dashboard": "off"}})
        await hass.async_block_till_done()
    assert entry.options[CONF_WEBUNTIS_CALENDARS] == {"anna": source.entity_id}
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "webuntis"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"child": "anna"})
    with patch.object(SchulManager, "_async_fetch_portal", return_value=portal_result()):
        await hass.config_entries.options.async_configure(flow["flow_id"], {})
        await hass.async_block_till_done()
    assert entry.options[CONF_WEBUNTIS_CALENDARS] == {}
    assert changed(entry.runtime_data) == []


async def test_both_sources_combined_and_duplicate_suppressed(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    external = deepcopy(changed(manager)[1])
    day = dt_util.as_local(source.events[2].start).date().isoformat()
    external["uid"] = "portal-duplicate"
    external.pop("source")
    manager.data["substitutions"]["anna"] = {"available": True, "days": [{"date": day, "entries": [
        external, {"uid": "portal-extra", "kind": "entfall", "lesson": "8", "subject": "Demo extra"},
    ]}]}
    entries = changed(manager)
    assert len(entries) == 4
    assert any(e["uid"] == "portal-extra" for e in entries)
    assert sum(e.get("room") == external["room"] for e in entries) == 1
    # A distinct note from the other source must remain visible.
    manager.data["substitutions"]["anna"]["days"][0]["entries"].append({
        **external, "uid": "portal-different-note", "info": "Additional portal information",
    })
    assert len(changed(manager)) == 5


async def test_switching_source_drops_old_cached_changes(hass, source):
    entry, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    assert len(changed(manager)) == 3
    # A stored source switch must not expose changes from the old calendar.
    with patch("custom_components.eltern_portal_schulmanager._async_reload"):
        hass.config_entries.async_update_entry(entry, options={CONF_WEBUNTIS_CALENDARS: {"anna": "calendar.missing"}})
        await hass.async_block_till_done()
    await refresh(manager)
    assert changed(manager) == [] and manager.last_errors


async def test_without_webuntis_installation_or_mapping(hass):
    entry, manager = await setup_manager(hass)
    assert CONF_WEBUNTIS_CALENDARS not in entry.options
    assert manager.last_errors == [] and changed(manager) == []


def serve_all(calendar):
    """Return every fixture event unfiltered, including all-day entries."""
    async def all_events(hass, start_date, end_date):
        return list(calendar.events)
    calendar.async_get_events = all_events


async def test_single_invalid_event_does_not_block_other_changes(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    assert len(changed(manager)) == 3
    lesson = json.loads(source.events[0].description)
    lesson["code"] = "cancelled"
    source.events[0] = CalendarEvent(start=source.events[0].start, end=source.events[0].end,
                                     summary="Cancelled: M", description=json.dumps(lesson))
    day = dt_util.now().date() + timedelta(days=2)
    source.events.append(CalendarEvent(
        start=day, end=day + timedelta(days=1), summary="Cancelled: X",
        description=json.dumps({"id": 999, "code": "cancelled", "subjects": [{"name": "X"}]}),
    ))
    serve_all(source)
    await refresh(manager)
    assert len(changed(manager)) == 4  # the new cancellation is imported
    assert manager.data["webuntis"]["anna"]["skipped"] == 1
    assert any("übersprungen" in error for error in manager.last_errors)


async def test_unexpected_calendar_exception_keeps_refresh_running(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    before_data = deepcopy(changed(manager))
    before_update = manager.last_update
    source.error = OSError("socket closed")
    await refresh(manager)  # must not raise
    assert manager.last_update != before_update
    assert changed(manager) == before_data
    assert "OSError" in manager.last_errors[0]


async def test_webuntis_error_does_not_block_portal_archive_cleanup(hass, source):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    source.error = HomeAssistantError("Calendar offline")
    with patch.object(SchulManager, "_prune_archived") as prune:
        await refresh(manager)
    assert prune.called and manager.last_errors


async def test_portal_and_webuntis_changes_share_one_notification(hass, source):
    notifications = async_capture_events(hass, EVENT_SUBSTITUTION)
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    assert notifications == []
    tomorrow = (dt_util.now().date() + timedelta(days=1)).isoformat()
    result = portal_result()
    result.children[0].substitutions = {"available": True, "days": [{"date": tomorrow, "entries": [
        {"kind": "entfall", "lesson": "6", "subject": "Portal-Demo"},
    ]}]}
    lesson = json.loads(source.events[0].description)
    lesson["code"] = "cancelled"
    source.events[0] = CalendarEvent(start=source.events[0].start, end=source.events[0].end,
                                     summary="Cancelled: M", description=json.dumps(lesson))
    with patch.object(SchulManager, "_async_fetch_portal", return_value=result), \
            patch.object(SchulManager, "_notify") as notify:
        # first portal plan is the initial import (no notification) ...
        await manager.async_refresh()
        await hass.async_block_till_done()
        notifications.clear()
        notify.reset_mock()
        result.children[0].substitutions["days"][0]["entries"].append(
            {"kind": "vertretung", "lesson": "7", "subject": "Portal-Neu"})
        lesson["substText"] = "Neu aus WebUntis"
        source.events[0] = CalendarEvent(start=source.events[0].start, end=source.events[0].end,
                                         summary="Cancelled: M", description=json.dumps(lesson))
        await manager.async_refresh()
        await hass.async_block_till_done()
    assert len(notifications) == 1
    sources = {entry.get("source", "portal") for entry in notifications[0].data["entries"]}
    assert sources == {"portal", "webuntis"}
    substitution_calls = [c for c in notify.call_args_list if "Vertretungsplan" in c.args[0]]
    assert len(substitution_calls) == 1


@pytest.mark.parametrize("arrival", ["together", "portal_first", "webuntis_first"])
async def test_realistic_cross_source_notification_slots(hass, source, arrival):
    """Independent source spellings stay displayed but notify a time slot once."""
    webuntis = source.events[2]
    source.events = []
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    result = portal_result()
    day = dt_util.as_local(webuntis.start).date()
    result.children[0].timetable = [{
        "weekday": day.isoweekday(), "lesson": "3", "start": "10:00", "end": "10:45", "subject": "Biologie",
    }]
    result.children[0].substitutions = {"available": True, "days": [{"date": day.isoformat(), "entries": []}]}
    notifications = async_capture_events(hass, EVENT_SUBSTITUTION)
    with patch.object(SchulManager, "_async_fetch_portal", return_value=result):
        await manager.async_refresh()  # Quiet, empty baseline for both sources.
        if arrival != "webuntis_first":
            result.children[0].substitutions["days"][0]["entries"] = [{
                "kind": "vertretung", "lesson": "3", "subject": "Biologie",
                "teacher": "Herr Demolehrer D", "substitute": "Frau Demolehrerin C",
                "room": "Raum 201", "info": "Bitte Buch mitbringen",
            }]
        if arrival != "portal_first":
            source.events = [webuntis]
        await manager.async_refresh()
        if arrival == "portal_first":
            source.events = [webuntis]
            await manager.async_refresh()
        elif arrival == "webuntis_first":
            result.children[0].substitutions["days"][0]["entries"] = [{
                "kind": "vertretung", "lesson": "3", "subject": "Biologie",
                "teacher": "Herr Demolehrer D", "substitute": "Frau Demolehrerin C",
                "room": "Raum 201", "info": "Bitte Buch mitbringen",
            }]
            await manager.async_refresh()
        await hass.async_block_till_done()
    assert len(changed(manager)) == 2  # Display still combines both original records.
    assert len(notifications) == 1
    assert len(notifications[0].data["entries"]) == 1
    if arrival == "together":
        note = notifications[0].data["entries"][0]["info"]
        assert "Bitte Buch mitbringen" in note and "Demodaten" in note
    # The source's later actual content change must still notify.
    payload = json.loads(webuntis.description)
    payload["substText"] = "Neuer Hinweis am Folgetag"
    source.events = [CalendarEvent(start=webuntis.start, end=webuntis.end,
                                  summary=webuntis.summary, description=json.dumps(payload))]
    with patch.object(SchulManager, "_async_fetch_portal", return_value=result):
        await manager.async_refresh()
        await hass.async_block_till_done()
    assert len(notifications) == 2


@pytest.mark.parametrize("legacy_seen", [False, True])
async def test_timetable_change_does_not_notify_unchanged_webuntis(hass, source, legacy_seen):
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    notifications = async_capture_events(hass, EVENT_SUBSTITUTION)
    if legacy_seen:
        cache = manager.data["webuntis"]["anna"]
        cache.pop("seen_version")
        cache["seen"] = [hashlib.sha1(json.dumps(e, sort_keys=True).encode()).hexdigest()
                         for day in cache["days"] for e in day["entries"]]
    day = dt_util.as_local(source.events[2].start).date()
    result = portal_result()
    result.children[0].timetable = [{
        "weekday": day.isoweekday(), "lesson": "3", "start": "10:00", "end": "10:45", "subject": "Biologie",
    }]
    with patch.object(SchulManager, "_async_fetch_portal", return_value=result):
        await manager.async_refresh()
        await hass.async_block_till_done()
    assert changed(manager)[1]["lesson"] == "3" and notifications == []
    payload = json.loads(source.events[2].description)
    payload["substText"] = "Actual source update"
    event = source.events[2]
    source.events[2] = CalendarEvent(start=event.start, end=event.end,
                                    summary=event.summary, description=json.dumps(payload))
    await refresh(manager)
    assert len(notifications) == 1


@pytest.mark.parametrize(("begin", "finish", "expected"), [
    ("10:05", "10:50", "3"),
    ("10:05", "11:30", "3-4"),
    ("14:00", "14:45", ""),
    ("10:22:30", "11:07:30", ""),  # Exactly half of two adjacent periods.
])
async def test_tolerant_period_assignment_preserves_event_times(hass, source, begin, finish, expected):
    original = source.events[2]
    day = dt_util.as_local(original.start).date()
    start = datetime.combine(day, time.fromisoformat(begin), dt_util.get_default_time_zone())
    end = datetime.combine(day, time.fromisoformat(finish), dt_util.get_default_time_zone())
    source.events = [CalendarEvent(start=start, end=end, summary=original.summary, description=original.description)]
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    manager.data["timetable"]["anna"] = {"lessons": [
        {"weekday": day.isoweekday(), "lesson": "3", "start": "10:00", "end": "10:45"},
        {"weekday": day.isoweekday(), "lesson": "4", "start": "10:45", "end": "11:30"},
    ]}
    await refresh(manager)
    entry = changed(manager)[0]
    assert entry["lesson"] == expected
    event = next(e for e in manager.child_events("anna") if e["category"] == "vertretung")
    assert event["start"] == start and event["end"] == end


async def test_calendar_waits_for_started_without_repeating_portal(hass, source):
    hass.state = CoreState.starting
    _, manager = await setup_manager(hass, {CONF_WEBUNTIS_CALENDARS: {"anna": source.entity_id}})
    assert manager.children and source.calls == 0
    assert manager.last_errors == [] and changed(manager) == []
    with patch.object(SchulManager, "_async_fetch_portal") as portal:
        hass.state = CoreState.running
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        portal.assert_not_called()
    assert source.calls == 1 and len(changed(manager)) == 3
    assert manager.last_errors == []
