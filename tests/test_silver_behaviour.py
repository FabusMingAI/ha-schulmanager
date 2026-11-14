"""Failure recovery and resilience requirements for Bronze and Silver."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import ClientConnectionError
from homeassistant import config_entries
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eltern_portal_schulmanager import analyzer, classes
from custom_components.eltern_portal_schulmanager.const import DOMAIN
from custom_components.eltern_portal_schulmanager.portal import PortalAuthError
from tests.test_eltern_portal_schulmanager import _fake_result
from tests.test_quality_runtime import setup_entry, MANAGER, PORTAL


@pytest.fixture(autouse=True)
def enable(hass, enable_custom_integrations, tmp_path):
    hass.config.language = "de"
    hass.config.media_dirs = {"local": str(tmp_path)}


@pytest.fixture
async def loaded(hass):
    entry = await setup_entry(hass)
    yield entry.runtime_data
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cached_start_validates_live_connection_but_preserves_local_access(hass):
    error = ClientConnectionError("offline")
    entry = await setup_entry(hass)
    children = deepcopy(entry.runtime_data.children)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=error) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    fetch.assert_awaited_once()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.runtime_data.children == children
    assert entry.runtime_data.last_errors
    assert hass.states.get("todo.schule_anna_aufgaben").state != "unavailable"
    assert hass.states.get("sensor.schule_anna_stundenplan").state == "unavailable"
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date(), with_pdf=False)):
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert entry.runtime_data.children == children
    assert entry.runtime_data.last_errors == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_section_failure_recovers_without_discarding_last_data(hass, loaded, caplog):
    result = _fake_result(dt_util.now().date(), with_pdf=False)
    child = result.children[0]
    child.timetable = [{"weekday": 1, "lesson": "1", "subject": "Math", "start": "08:00", "end": "08:45"}]
    child.substitutions = {"available": True, "days": []}
    child.sicknotes = []
    with patch(f"{MANAGER}._async_fetch_portal", return_value=result):
        await loaded.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.schule_anna_stundenplan").state != "unavailable"
    assert hass.states.get("sensor.schule_anna_vertretungen").state == "0"
    saved = deepcopy(loaded.data["timetable"])
    child.timetable = None
    result.errors = ["lesson: offline"]
    with patch(f"{MANAGER}._async_fetch_portal", return_value=result):
        await loaded.async_refresh()
        await loaded.async_refresh()
        await hass.async_block_till_done()
    assert caplog.text.count("bspgym: lesson unavailable") == 1
    assert hass.states.get("sensor.schule_anna_stundenplan").state == "unavailable"
    assert hass.states.get("sensor.schule_anna_vertretungen").state == "0"
    assert loaded.data["timetable"] == saved
    child.timetable = saved["anna"]["lessons"]
    result.errors = []
    with patch(f"{MANAGER}._async_fetch_portal", return_value=result):
        await loaded.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.schule_anna_stundenplan").state != "unavailable"


@pytest.mark.parametrize("action,data,key", [
    ("complete_task", {"task_id": "missing"}, "unknown_task"),
    ("update_task", {"task_id": "missing", "title": "test"}, "unknown_task"),
    ("reanalyze", {"item_id": "missing"}, "unknown_item"),
    ("mark_read", {"item_id": "missing"}, "unknown_item"),
    ("mark_read", {"child": "missing"}, "unknown_child"),
    ("update_item", {"item_id": "missing", "status": "offen"}, "unknown_item"),
    ("update_item", {"item_id": "", "status": "erledigt"}, "unknown_item"),
    ("archive_event", {"child": "anna", "event_id": "missing"}, "unknown_event"),
    ("update_item", {"child": "missing", "status": "offen"}, "unknown_child"),
    ("add_task", {"child": "missing", "title": "task"}, "unknown_child"),
    ("get_overview", {"child": "missing"}, "unknown_child"),
    ("archive_event", {"child": "missing", "event_id": "x"}, "unknown_child"),
    ("unarchive_event", {"child": "missing", "event_id": "x"}, "unknown_child"),
])
async def test_action_invalid_identifiers(hass, loaded, action, data, key):
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=action=="get_overview")
    assert err.value.translation_key == key


async def test_refresh_action_reports_outage(hass, loaded):
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=ClientConnectionError("offline")), pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    assert err.value.translation_key == "refresh_failed"


async def test_dashboard_action_reports_failure(hass, loaded):
    with patch("custom_components.eltern_portal_schulmanager.dashboard.async_apply", return_value=False), pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "rebuild_dashboard", {}, blocking=True)
    assert err.value.translation_key == "dashboard_failed"


async def test_notification_actions_report_failure_and_reminders_retry(hass, loaded):
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        hass.config_entries.async_update_entry(loaded.entry, options={"notify_services": ["missing"]})
        await hass.async_block_till_done()
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "send_digest", {}, blocking=True)
    assert err.value.translation_key == "notification_failed"
    task = loaded.add_task("anna", "Pay", due=dt_util.now().date().isoformat())
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "send_reminders", {}, blocking=True)
    assert task["reminded"] == []


async def test_todo_invalid_updates_and_deletes_are_atomic(loaded):
    from custom_components.eltern_portal_schulmanager.todo import SchulTodo, _due
    todo = SchulTodo(loaded, "anna")
    with pytest.raises(ServiceValidationError):
        await todo.async_update_todo_item(TodoItem(uid="missing", summary="test"))
    task = loaded.add_task("anna", "Task")
    with pytest.raises(ServiceValidationError):
        await todo.async_delete_todo_items([task["id"], "missing"])
    assert task["id"] in loaded.tasks
    await todo.async_update_todo_item(TodoItem(uid=task["id"], summary="Renamed", description="💬 Kommentar: unchanged", status=TodoItemStatus.NEEDS_ACTION))
    assert loaded.tasks[task["id"]]["title"] == "Renamed"
    await todo.async_delete_todo_items([task["id"], task["id"]])
    assert task["id"] not in loaded.tasks
    assert _due(datetime(2026, 11, 8, 9)) == "2026-11-08"
    assert _due(None) is None


def test_malformed_ai_answers_are_normalized():
    result = analyzer.normalize({"aufgaben": [None, {}, {"titel": "Pay", "typ": "unsupported", "betrag": "12,50 Euro", "faellig": "31.12.26"}, {"titel": "Question", "betrag": "none", "faellig": "invalid"}], "termine": [None, {}, {"titel": "Invalid", "datum": "not a date"}, {"titel": "Valid", "datum": "08.11.2026", "uhrzeit": "invalid"}], "dringlichkeit": "unknown", "zusammenfassungen": {"en": "Summary"}}, ["en"])
    assert result["tasks"][0]["type"] == "zahlung"
    assert result["tasks"][0]["due"] == "2026-12-31"
    assert result["tasks"][1]["amount"] is None
    assert len(result["events"]) == 1 and result["events"][0]["time"] is None
    assert result["urgency"] == "mittel"
    assert result["summary"] == "Summary"
    assert analyzer.fmt_eur(None) == ""
    assert analyzer._parse_amount(0) is None
    assert analyzer._parse_amount("0,00") is None


@pytest.mark.parametrize("payload", [None, {"data": "bad response"}, {"data": '{"aufgaben": []}'}])
async def test_ai_response_protocol(hass, payload):
    async def answer(call):
        return payload
    hass.services.async_register("ai_task", "generate_data", answer, supports_response=SupportsResponse.ONLY)
    if payload and "aufgaben" in str(payload):
        result = await analyzer.async_analyze_ai(hass, "ai_task.test", {"body": "x"*15000})
        assert result["tasks"] == []
    else:
        with pytest.raises(analyzer.AnalyzeError):
            await analyzer.async_analyze_ai(hass, "ai_task.test", {})


async def test_ai_service_and_translation_failures(hass):
    with pytest.raises(analyzer.AnalyzeError):
        await analyzer.async_analyze_ai(hass, "ai_task.missing", {})
    with pytest.raises(analyzer.AnalyzeError):
        await analyzer.async_translate_summary(hass, "ai_task.missing", "Summary", "de", ["en"])
    assert await analyzer.async_translate_summary(hass, "ai_task.test", "", "de", ["en"]) == {}
    async def bad_response(call):
        return {"data": "not JSON"}
    hass.services.async_register("ai_task", "generate_data", bad_response, supports_response=SupportsResponse.ONLY)
    with pytest.raises(analyzer.AnalyzeError):
        await analyzer.async_translate_summary(hass, "ai_task.test", "Summary", "de", ["en"])


def test_rules_invalid_dates_and_long_messages():
    result = analyzer.analyze_rules({"body": "Bis 31.02.2026. Bis 1.12.26. " + "text "*80, "sent_date": date(2026, 11, 8)})
    assert result["tasks"][0]["due"] == "2026-12-01"
    assert len(result["summary"]) == 218
    assert analyzer._year_for(10, 1, date(2026, 12, 1)) == 2027


@pytest.mark.parametrize("text,classname,expected", [("Info", "unknown", None), ("99a", "8b", None), ("Klassen 13-1", "8b", None)])
def test_class_filters_ignore_invalid_labels(text, classname, expected):
    assert classes.concerns_class(text, classname) is expected


async def test_websocket_error_and_task_protocol(hass, loaded, hass_ws_client):
    from custom_components.eltern_portal_schulmanager import websocket as ws
    client = await hass_ws_client(hass)
    number = 0
    async def request(kind, **data):
        nonlocal number
        number += 1
        await client.send_json({"id": number, "type": f"{DOMAIN}/{kind}", **data})
        return await client.receive_json()
    for kind, params in [("item", {"item_id": "missing"}), ("task", {"task_id": "missing"}), ("event_links", {"child": "anna", "event_id": "missing"})]:
        assert not (await request(kind, **params))["success"]
    task = loaded.add_task("anna", "Own task", due=dt_util.now().date().isoformat())
    detail = await request("task", task_id=task["id"])
    assert detail["success"] and detail["result"]["calendar"]
    assert detail["result"]["item"] is None
    loaded.complete_task(task["id"])
    task["completed"] = (dt_util.now() - timedelta(days=90)).isoformat()
    result = await request("data", child="anna")
    assert all(t["id"] != task["id"] for t in result["result"]["children"][0]["tasks"])
    assert (await request("data", child="missing"))["result"]["children"] == []
    await hass.config_entries.async_unload(loaded.entry.entry_id)
    for kind in ("data", "subscribe"):
        assert (await request(kind))["error"]["code"] == "not_loaded"
    with patch.object(ws.Path, "read_text", side_effect=OSError):
        assert ws._read_version() is None
    event = {"start": dt_util.now(), "end": dt_util.now()+timedelta(hours=1), "uid": "test", "summary": "Event"}
    assert ws._event_light(event)["time"]
    loaded.data["events"]["future"] = {"uid": "future", "child": "anna", "title": "Future", "date": (dt_util.now().date()+timedelta(days=200)).isoformat()}
    assert not any(e["uid"] == "future" for e in ws._agenda(loaded, "anna"))


async def test_dashboard_missing_storage_and_failed_save(hass, loaded):
    from types import SimpleNamespace
    from custom_components.eltern_portal_schulmanager import dashboard as dash
    assert await dash._async_get_dashboard(hass, True) is None
    hass.data["lovelace"] = SimpleNamespace(dashboards={})
    assert await dash._async_get_dashboard(hass, True) is None
    loaded.children["anna"].pop("portal_url", None)
    assert dash.build_config(hass, loaded, "single")["views"]
    assert dash._child_entities(hass, loaded, "anna")["status"]
    fake = SimpleNamespace(mode="storage", async_load=AsyncMock(side_effect=RuntimeError), async_save=AsyncMock(side_effect=RuntimeError))
    with patch.object(loaded, "opt", return_value="tabs"), patch.object(dash, "_async_get_dashboard", return_value=fake):
        assert not await dash.async_apply(hass, loaded)


async def test_attachment_and_calendar_not_found(hass, loaded):
    from custom_components.eltern_portal_schulmanager import SchulIcsView, SchulFileView, _card_path
    request = Mock(app={"hass": hass})
    assert (await SchulIcsView().get(request, "anna", "missing")).status == 404
    await hass.config_entries.async_unload(loaded.entry.entry_id)
    assert (await SchulIcsView().get(request, "anna", "missing")).status == 404
    assert (await SchulFileView().get(request, "missing", "x")).status == 404
    with patch("custom_components.eltern_portal_schulmanager.os.path.isfile", return_value=False), pytest.raises(FileNotFoundError):
        _card_path()


def test_date_labels_and_invalid_dates():
    from custom_components.eltern_portal_schulmanager.manager import _parse_time, _fmt_date, _day_label, _days_text, _clean_stored_appointment
    from datetime import time
    assert _parse_time("invalid", "07:00:00") == time(7)
    with pytest.raises(ValueError):
        _fmt_date("invalid")
    assert _fmt_date(None) == ""
    today = date(2026, 11, 8)
    assert "10.11." in _day_label(today+timedelta(days=2), today)
    assert [_days_text(n) for n in (0, 1, -1, -3, 4)] == ["heute", "morgen", "seit gestern überfällig", "seit 3 Tagen überfällig", "in 4 Tagen"]
    cleaned = _clean_stored_appointment({"title": "8:00 - 9:00<br>Meeting", "detail": "<b>Other</b>"})
    assert cleaned["title"] == "Meeting" and cleaned["time"] == "08:00"


async def test_voice_targets_and_error_reporting(hass, loaded):
    calls = []
    async def announce(call):
        calls.append((call.domain, call.service))
    hass.services.async_register("assist_satellite", "announce", announce)
    hass.services.async_register("tts", "speak", announce)
    options = {"tts_targets": ["assist_satellite.kitchen", "media_player.kitchen"], "tts_engine": "tts.test", "tts_start": "00:00:00", "tts_end": "23:59:59"}
    with patch.object(loaded, "opt", side_effect=lambda key, default=None: options.get(key, default)):
        assert loaded._tts_allowed()
        await loaded.async_announce("Message", force=True)
        assert calls == [("assist_satellite", "announce"), ("tts", "speak")]
        with patch.object(type(hass.services), "async_call", side_effect=HomeAssistantError("offline")):
            await loaded.async_announce("Message", force=True)
            with pytest.raises(HomeAssistantError):
                await loaded.async_announce("Message", force=True, strict=True)
            await loaded._notify("title", "message")
    with patch.object(loaded, "opt", return_value=["notify.missing"]):
        await loaded._notify("title", "message")


async def test_remove_school_preserves_other_school_and_files(loaded):
    loaded.data["events"]["x"] = {"child": "anna"}
    loaded.data["teachers"]["bspgym"] = {"updated": "invalid", "list": {}}
    assert loaded._teachers_due("bspgym")
    task = loaded.add_task("anna", "Own task")
    loaded.children["ben"] = {"name": "Ben", "school": "other"}
    loaded.portal_status["other"] = "ok"
    loaded.remove_portal_data("bspgym")
    assert set(loaded.children) == {"ben"}
    assert not loaded.items and task["id"] not in loaded.tasks
    assert "x" not in loaded.data["events"]
    assert loaded.portal_status == {"other": "ok"}
    assert "bspgym" not in loaded.data["initialized"]


async def test_worker_failures_do_not_drop_queue_or_data(loaded):
    await loaded.async_stop()
    item = next(iter(loaded.items.values()))
    item["analysis"] = {"status": "pending"}
    item["notify"] = True
    with patch.object(loaded, "_analyze", side_effect=ValueError("malformed AI")), patch.object(loaded, "_notify_item", side_effect=HomeAssistantError("notification down")):
        await loaded._work_queue()
    assert item["analysis"]["status"] == "fehler"
    assert item["uid"] in loaded.items
    assert not loaded._pending()


async def test_media_roots_timers_and_invalid_status(hass, loaded):
    hass.config.media_dirs = {}
    assert loaded.media_root == ("local", hass.config.path("media"))
    hass.config.media_dirs = {"other": "/tmp/fictional-media"}
    assert loaded.media_root == ("other", "/tmp/fictional-media")
    task = loaded.add_task("anna", "Task")
    with pytest.raises(ServiceValidationError):
        loaded.update_task(task["id"], status="unsupported")
    with pytest.raises(ServiceValidationError):
        loaded.set_item_status(None, "unsupported")
    with patch.object(loaded, "async_refresh", side_effect=HomeAssistantError("offline")):
        await loaded._scheduled_refresh(dt_util.now())
    with patch.object(loaded, "async_send_digest", return_value=False) as digest, patch.object(loaded, "async_send_reminders", return_value=0) as reminders:
        await loaded._scheduled_digest(dt_util.now())
        await loaded._scheduled_reminders(dt_util.now())
        digest.assert_awaited_once()
        reminders.assert_awaited_once()


async def test_task_reopening_reminder_stages_and_mobile_actions(hass, loaded):
    from homeassistant.core import Event
    from custom_components.eltern_portal_schulmanager.const import ACTION_SNOOZE, ACTION_READ
    from custom_components.eltern_portal_schulmanager.manager import _day_label, _pdf_text
    await loaded.async_stop()
    today = dt_util.now().date()
    reopened = loaded.add_task("anna", "Reopen", due=today.isoformat())
    loaded.complete_task(reopened["id"])
    loaded.complete_task(reopened["id"], False)
    assert reopened["status"] == "offen" and reopened["completed"] is None
    reopened["reminded"] = ["d0"]
    reopened["snoozed_until"] = today.isoformat()
    loaded.update_task(reopened["id"], due=(today-timedelta(days=1)).isoformat())
    assert reopened["reminded"] == [] and reopened["snoozed_until"] is None
    snoozed = loaded.add_task("anna", "Snoozed")
    snoozed["snoozed_until"] = today.isoformat()
    future = loaded.add_task("anna", "Later")
    future["snoozed_until"] = (today+timedelta(days=1)).isoformat()
    done = loaded.add_task("anna", "Done")
    loaded.complete_task(done["id"])
    with patch.object(loaded, "opt", side_effect=lambda key, default=None: "invalid" if key == "reminder_days" else default), patch.object(loaded, "_notify", return_value=True), patch.object(loaded, "async_announce", return_value=None) as voice:
        assert await loaded.async_send_reminders() >= 2
        voice.assert_awaited_once()
        assert reopened["reminded"] == [f"over-{today.isoformat()}"]
        assert snoozed["reminded"] == [f"snooze-{today.isoformat()}"]
    await loaded._handle_mobile_action(Event("mobile_app_notification_action", {"action": f"{ACTION_SNOOZE}::{reopened['id']}"}))
    assert reopened["snoozed_until"] == (today+timedelta(days=1)).isoformat()
    item = next(iter(loaded.items.values()))
    item["read"] = False
    await loaded._handle_mobile_action(Event("mobile_app_notification_action", {"action": f"{ACTION_READ}::{item['uid']}"}))
    assert item["read"]
    await loaded._handle_mobile_action(Event("mobile_app_notification_action", {"action": "unrelated"}))
    await loaded.async_reanalyze(item["uid"])
    assert item["analysis"]["status"] == "pending"
    assert loaded.published({"sent": "invalid"}) is None
    assert loaded.date_prefix(None) == ""
    assert _day_label(today, today) == "Heute"
    assert loaded.media_content_id("file.pdf").endswith("/file.pdf")
    assert await hass.async_add_executor_job(_pdf_text, "/tmp/fictional-nonexistent.pdf") == ""


async def test_manual_digest_requires_destination(hass, loaded):
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, "send_digest", {}, blocking=True)
    assert error.value.translation_key == "notification_not_configured"


async def test_forced_dashboard_rebuild_is_idempotent(hass, loaded):
    from types import SimpleNamespace
    from custom_components.eltern_portal_schulmanager import dashboard as dash
    current = dash.build_config(hass, loaded, "tabs")
    fake = SimpleNamespace(mode="storage", async_load=AsyncMock(return_value=current), async_save=AsyncMock())
    with patch.object(loaded, "opt", return_value="tabs"), patch.object(dash, "_async_get_dashboard", return_value=fake):
        assert await dash.async_apply(hass, loaded, force=True)
        fake.async_save.assert_awaited_once()
        fake.async_save.side_effect = OSError("read only")
        with pytest.raises(HomeAssistantError) as err:
            await dash.async_apply(hass, loaded, force=True)
        assert err.value.translation_key == "dashboard_failed"


async def test_children_with_same_firstname_keep_distinct_stable_entities(hass, loaded):
    from custom_components.eltern_portal_schulmanager.manager import SchulManager
    await loaded.async_stop()
    second = _fake_result(dt_util.now().date(), with_pdf=False)
    second.school = "other"
    for item in second.children[0].items:
        item.uid = item.uid.replace("bspgym-", "other-")
    await loaded._merge(second)
    assert set(loaded.children) == {"anna", "anna_other_7"}
    assert loaded.children["anna"]["school"] == "bspgym"
    assert loaded.children["anna_other_7"]["school"] == "other"
    await loaded.async_stop()
    restored = SchulManager(hass, loaded.entry)
    await restored.async_load()
    second.children[0].firstname = "Anne"
    await restored._merge(second)
    assert set(restored.children) == {"anna", "anna_other_7"}
    assert restored.children["anna_other_7"]["name"] == "Anne"
    # A historical unrelated key must not be overwritten on a later import.
    restored.children["anna_other_8"] = {"school": "unrelated", "student_id": "0"}
    assert restored._child_key("other", "8", "Anna") == "anna_other_8_2"


async def test_background_reminders_retry_failed_delivery(hass, loaded):
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        hass.config_entries.async_update_entry(loaded.entry, options={"notify_services": ["missing"]})
        await hass.async_block_till_done()
    task = loaded.add_task("anna", "Reminder", due=dt_util.now().date().isoformat())
    assert await loaded.async_send_reminders() == 0
    assert task["reminded"] == []
    async def delivered(call):
        return None
    hass.services.async_register("notify", "missing", delivered)
    assert await loaded.async_send_reminders() >= 1
    assert task["reminded"] == ["d0"]
