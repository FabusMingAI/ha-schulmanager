"""Archive backfill and reversible, child-scoped timetable additions."""
from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eltern_portal_schulmanager.analyzer import (
    AnalyzeError, MAX_TEXT, async_extract_schedule, normalize,
)
from custom_components.eltern_portal_schulmanager.const import DOMAIN
from custom_components.eltern_portal_schulmanager.manager import SchulManager
from custom_components.eltern_portal_schulmanager.schedule import (
    clock, holiday_entries, in_holidays, lesson_uid, message_entries, occurrences, rule_events,
)

MODULE = "custom_components.eltern_portal_schulmanager.manager"


def event(**kw):
    return {"title": "Robotikkurs 8b", "date": "2026-11-16", "time": "14:00",
            "time_end": "15:30", "end": None, "location": "101", "status": "confirmed", **kw}


@pytest.fixture
async def manager(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={"portals": []}, options={})
    entry.add_to_hass(hass)
    m = SchulManager(hass, entry)
    await m.async_load()
    m.children["anna"] = {"name": "Anna", "classname": "8b", "school": "demo"}
    m.children["max"] = {"name": "Max", "classname": "6a", "school": "other"}
    m.items["letter"] = {"uid": "letter", "child": "anna", "kind": "nachricht", "read": True,
                         "sent": "2026-11-01T10:00:00", "title": "Robotikkurs", "version": "v1",
                         "body": "Robotikkurs am 16.11.2026 von 14:00 bis 15:30", "analysis": {"status": "archiv"}}
    m._changed = lambda: None
    return m


def test_schedule_validation_holidays_and_weekly_series():
    assert clock("7:30") == "07:30"
    assert clock("25:00") is None and clock(None) is None
    holidays = holiday_entries()
    assert len(holidays) == 37
    assert in_holidays(date(2026, 12, 24)) and in_holidays(date(2027, 1, 8))
    assert not in_holidays(date(2027, 1, 11))
    assert occurrences(event()) == [date(2026, 11, 16)]
    assert occurrences(event(weekday=1, repeat_until="2026-11-30")) == [date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30)]
    assert len(occurrences(event(weekday=1, repeat_until="2030-01-01"))) <= 53
    raw = {"termine": [{"titel": "Kurs", "datum": "2026-11-16", "sicher": True,
                       "beleg": "Kurs", "optional": True, "wochentag": 1, "wiederholen_bis": "2026-01-01",
                       "uhrzeit": "99:99", "ende_uhrzeit": "15:30"}]}
    normalized = normalize(raw)["events"][0]
    assert normalized["status"] == "proposed" and normalized["time"] is None
    assert normalized["repeat_until"] is None and normalized["time_end"] == "15:30"
    raw["termine"][0].update(optional=False, wochentag=9, abgesagt=True)
    assert normalize(raw)["events"][0]["status"] == "cancelled"


def test_fallback_suggestions_use_message_year_and_validate_dates():
    ctx = {"title": "Ausflüge", "sent_date": date(2025, 12, 1),
           "body": "<p>Ausflug am 12.01. um 7:30 bis 09:00</p>\nKurs am 31.02.2026\nKonzert am 20.12.2025\nBitte zahlen bis 10.12.2025"}
    events = rule_events(ctx)
    assert len(events) == 2 and events[0]["date"] == "2026-01-12"
    assert events[0]["time"] == "07:30" and events[0]["time_end"] == "09:00"
    assert all(e["status"] == "proposed" for e in events)
    assert not rule_events({"body": "Kurs am 12.01."})
    assert rule_events({"body": "Kurs am 12.01.2026"})[0]["time"] is None


def test_deduplication_class_filter_and_cancellation():
    items = {"one": {"uid": "one", "sent": "2026-11-01"}, "two": {"uid": "two", "sent": "2026-11-02"}}
    rows = [event(uid="a", item_uid="one"), event(uid="b", item_uid="two"),
            event(uid="c", title="Ausflug 6a", item_uid="one")]
    grouped = message_entries(rows, items, "8b")
    assert len(grouped) == 1 and grouped[0]["aliases"] == ["a", "b"]
    assert len(grouped[0]["sources"]) == 2
    rows.append(event(uid="cancel", item_uid="two", time=None, status="cancelled"))
    assert all(e["status"] == "cancelled" for e in message_entries(rows, items, "8b"))


async def test_archive_backfill_preserves_tasks_read_state_and_resumes(manager):
    m = manager
    m.tasks["existing"] = {"title": "Existing", "status": "erledigt"}
    before = deepcopy(m.tasks)
    await m._schedule_backfill()
    assert m.tasks == before and m.items["letter"]["read"] is True
    assert m.items["letter"]["analysis"] == {"status": "archiv"}
    assert len(m.data["events"]) == 1 and not m._schedule_pending()
    assert m.schedule_progress == {"total": 1, "pending": 0, "failed": 0, "unreadable": 0}
    uid = next(iter(m.data["events"]))
    m.schedule_action("anna", uid, "hide")
    m.rescan_schedule()
    await m._schedule_backfill()
    assert next(e for e in m.schedule_entries("anna") if e["uid"] == uid)["hidden"]
    m.schedule_action("anna", uid, "restore")
    m.schedule_action("anna", uid, "confirm")
    assert next(e for e in m.schedule_entries("anna") if e["uid"] == uid)["status"] == "confirmed"
    assert any(e["title"] == "Robotikkurs" for e in m.child_events("anna"))
    m.set_schedule_options("anna", False, False)
    assert m.schedule_options("anna") == {"messages": False, "holidays": False}
    assert not any(e["title"] == "Robotikkurs" for e in m.child_events("anna"))
    with pytest.raises(ServiceValidationError):
        m.schedule_action("max", uid, "hide")
    with pytest.raises(ServiceValidationError):
        m.schedule_action("missing", uid, "hide")
    with pytest.raises(ServiceValidationError):
        m.schedule_action("anna", "missing", "hide")


async def test_legacy_uids_updates_reordering_tombstones_and_optional_lessons(manager):
    m = manager
    item = m.items["letter"]
    m.data["events"]["legacy-termin-0"] = event(uid="legacy-termin-0", item_uid="letter", child="anna")
    m._replace_events(item, [event(), event(title="Ausflug", date="2026-12-01")], "ki")
    assert "legacy-termin-0" in m.data["events"]
    m.schedule_action("anna", "legacy-termin-0", "hide")
    m._replace_events(item, [event(title="Ausflug", date="2026-12-01"), event(date="2026-11-23")], "ki")
    assert m.data["events"]["legacy-termin-0"]["date"] == "2026-11-23"
    assert next(e for e in m.schedule_entries("anna") if e["uid"] == "legacy-termin-0")["hidden"]
    m.data["timetable"]["anna"] = {"lessons": [{"weekday": 1, "lesson": "7", "subject": "Robotik", "optional": True}]}
    lesson = m.child_timetable("anna")[0]
    uid = lesson_uid(lesson)
    m.schedule_action("anna", uid, "hide")
    assert m.child_timetable("anna")[0]["hidden"]
    m.schedule_action("anna", uid, "restore")
    assert not m.child_timetable("anna")[0]["hidden"]
    # User choices are persisted independently of disappearing source content.
    m.schedule_action("anna", "legacy-termin-0", "hide")
    m._replace_events(item, [], "ki")
    assert m.data["schedule_choices"]["anna"]["legacy-termin-0"] == "hidden"


async def test_calendar_series_skips_holidays_and_uses_end_times(manager):
    m = manager
    m._replace_events(m.items["letter"], [event(date="2026-12-21", weekday=1, repeat_until="2027-01-11")], "ki")
    events = [e for e in m.child_events("anna") if e["category"] == "termin"]
    assert [e["start"].date().isoformat() for e in events] == ["2026-12-21", "2027-01-11"]
    assert all(e["end"] - e["start"] == timedelta(minutes=90) for e in events)
    m._replace_events(m.items["letter"], [event(time=None, time_end=None, end="2026-11-18")], "ki")
    assert next(e for e in m.child_events("anna") if e["category"] == "termin")["end"] == date(2026, 11, 19)
    m._replace_events(m.items["letter"], [event(status="cancelled")], "ki")
    assert not any(e["category"] == "termin" for e in m.child_events("anna"))


async def test_backfill_ai_failure_retry_and_concurrent_edits(manager):
    m = manager
    m.hass.config_entries.async_update_entry(m.entry, options={"ai_task_entity": "ai_task.demo"})
    with patch(f"{MODULE}.async_extract_schedule", side_effect=AnalyzeError("offline")):
        await m._schedule_backfill()
    assert m.schedule_progress["failed"] == 1
    m.rescan_schedule()
    with patch(f"{MODULE}.async_extract_schedule", return_value=[event()]):
        await m._schedule_backfill()
    assert m.schedule_progress["failed"] == 0
    m.rescan_schedule()
    with patch.object(m, "_schedule_context", side_effect=ValueError("unreadable")):
        await m._schedule_backfill()
    assert m.schedule_progress["failed"] == 1
    m.rescan_schedule()
    async def edited(*args, **kwargs):
        m.items["letter"]["body"] = "Changed during analysis"
        return [event()]
    with patch(f"{MODULE}.async_extract_schedule", side_effect=edited):
        await m._schedule_backfill()
    assert m._schedule_pending()


async def test_archive_attachments_and_chunking(manager):
    m = manager
    m.items["letter"]["files"] = [{"path": "example.pdf", "content_type": "application/pdf"}]
    with patch(f"{MODULE}._pdf_text", return_value="Page 20: Kurs am 20.11.2026") as read:
        ctx = await m._schedule_context(m.items["letter"])
    assert "Page 20" in ctx["body"] and read.call_args.kwargs == {"max_pages": None}
    with patch(f"{MODULE}._pdf_text", return_value=""):
        assert (await m._schedule_context(m.items["letter"]))["body"] == m._context(m.items["letter"])["body"]
    body = "x" * (MAX_TEXT * 2 + 300)
    with patch("custom_components.eltern_portal_schulmanager.analyzer.async_analyze_ai", new_callable=AsyncMock, return_value={"events": []}) as analyze:
        assert await async_extract_schedule(m.hass, "ai_task.demo", {"body": body}) == []
        chunks = [call.args[2]["body"] for call in analyze.call_args_list]
    assert len(chunks) == 3 and all(len(c) <= MAX_TEXT for c in chunks)
    assert sum(len(c) for c in chunks) >= len(body)
