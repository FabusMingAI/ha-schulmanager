"""Persisted school records stay readable across an offline reload/restart."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import ssl

import pytest
from aiohttp import ClientConnectorCertificateError, ClientConnectionError
from homeassistant import config_entries
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.eltern_portal_schulmanager.const import DOMAIN, STORAGE_VERSION
from custom_components.eltern_portal_schulmanager import file_url
from tests.test_quality_runtime import setup_entry, MANAGER, PORTAL
from tests.test_eltern_portal_schulmanager import _fake_result


@pytest.fixture(autouse=True)
def custom(hass, enable_custom_integrations, tmp_path):
    hass.config.language = "de"
    hass.config.media_dirs = {"local": str(tmp_path / "media")}


def certificate_error():
    return ClientConnectorCertificateError(
        SimpleNamespace(host="demo.eltern-portal.org", port=443, is_ssl=True),
        ssl.CertificateError("certificate has expired"),
    )


@pytest.mark.parametrize("legacy_cache", [False, True])
async def test_persisted_content_ws_files_and_recovery_during_certificate_outage(hass, hass_ws_client, hass_client_no_auth, legacy_cache):
    entry = await setup_entry(hass)
    old = entry.runtime_data
    # Use an actual synthetic PDF and portal records, not a production account.
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date())):
        await old.async_refresh()
        await hass.async_block_till_done()
    notifications = async_capture_events(hass, f"{DOMAIN}_new_item")
    before = deepcopy(old.data)
    if legacy_cache:
        before.pop("portal_last_success")
    assert await hass.config_entries.async_unload(entry.entry_id)
    # Persist a complete snapshot and recreate the manager, as on restart.
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_save(before)
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=certificate_error()) as fetch:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    m = entry.runtime_data
    assert m is not old and entry.state is config_entries.ConfigEntryState.LOADED
    fetch.assert_awaited_once()
    for key in ("children", "items", "tasks", "events", "appointments", "timetable", "substitutions", "sicknotes", "portal_last_success"):
        assert m.data[key] == before.get(key, {})
    assert m.portal_status == {"bspgym": "connection_failed"}
    assert m.last_errors and m.last_update
    assert notifications == []
    assert hass.states.get("todo.schule_anna_aufgaben").state != "unavailable"
    assert hass.states.get("sensor.schule_anna_stundenplan").state == "unavailable"
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": f"{DOMAIN}/data"})
    result = (await ws.receive_json())["result"]
    child = result["children"][0]
    assert child["items"] and child["tasks"]
    assert child["portal_status"] == "connection_failed"
    assert child["last_success"] == before.get("portal_last_success", {}).get("bspgym")
    source = next(i for i in m.items.values() if i["files"])
    url = file_url(hass, source["uid"], 0)
    client = await hass_client_no_auth()
    response = await client.get(url)
    assert response.status == 200 and (await response.read()).startswith(b"%PDF")
    # Repeated failed retries keep the same content and source timestamp.
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=certificate_error()):
        await m.async_refresh()
    assert m.data["portal_last_success"] == before.get("portal_last_success", {})
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date(), with_pdf=False)):
        await m.async_refresh()
        await hass.async_block_till_done()
    assert m.last_errors == [] and m.portal_status == {"bspgym": "ok"}
    assert notifications == []
    assert m.data["portal_last_success"]["bspgym"]
    if child["last_success"]:
        assert m.data["portal_last_success"]["bspgym"] >= child["last_success"]
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("cache_kind", ["no_children", "not_initialized", "other_school"])
async def test_unvalidated_school_still_requires_live_setup(hass, cache_kind):
    entry = MockConfigEntry(domain=DOMAIN, data={"portals": [PORTAL]}, options={"dashboard": "off"})
    entry.add_to_hass(hass)
    cached = {"children": {"anna": {"school": "bspgym", "name": "Anna"}}, "initialized": ["bspgym"]}
    if cache_kind == "no_children":
        cached["children"] = {}
    elif cache_kind == "not_initialized":
        cached["initialized"] = []
    else:
        cached["children"]["anna"]["school"] = "other"
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_save(cached)
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=ClientConnectionError("offline")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_partial_fetch_does_not_claim_complete_success(hass):
    entry = await setup_entry(hass)
    m = entry.runtime_data
    before = deepcopy(m.data["portal_last_success"])
    partial = _fake_result(dt_util.now().date(), with_pdf=False)
    partial.errors = ["substitution: unavailable"]
    with patch(f"{MANAGER}._async_fetch_portal", return_value=partial):
        await m.async_refresh()
    assert m.data["portal_last_success"] == before and m.portal_status == {"bspgym": "partial"}
    m.remove_portal_data("bspgym")
    assert "bspgym" not in m.data["portal_last_success"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cached_authentication_error_still_requests_reauthentication(hass):
    from custom_components.eltern_portal_schulmanager.portal import PortalAuthError
    entry = await setup_entry(hass)
    before = deepcopy(entry.runtime_data.children)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=PortalAuthError("invalid")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    assert entry.async_get_active_flows(hass, {"reauth"})
    saved = await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_load()
    assert saved["children"] == before


async def test_cached_restart_isolates_schools_and_keeps_first_source_timestamp(hass):
    other = {**PORTAL, "school": "other"}
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"portals": [PORTAL, other]}, options={"dashboard": "off"})
    entry.add_to_hass(hass)
    first = _fake_result(dt_util.now().date(), with_pdf=False)
    second = deepcopy(first)
    second.school = "other"
    second.children[0].firstname = "Ben"
    second.children[0].student_id = "ben"
    # Distinct source records, as with two real schools.
    for item in second.children[0].items:
        item.uid = "other-" + item.uid
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=[first, second]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    before = deepcopy(entry.runtime_data.data)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_save(before)
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=[certificate_error(), second]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.portal_status == {"bspgym": "connection_failed", "other": "ok"}
    assert m.children == before["children"]
    assert all(uid in m.items for uid in before["items"])
    assert m.data["portal_last_success"]["bspgym"] == before["portal_last_success"]["bspgym"]
    assert m.data["portal_last_success"]["other"] >= before["portal_last_success"]["other"]
    await hass.config_entries.async_unload(entry.entry_id)
