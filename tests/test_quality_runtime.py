"""Runtime failure recovery and diagnostics without live portal access."""
from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eltern_portal_schulmanager.const import DOMAIN
from custom_components.eltern_portal_schulmanager.diagnostics import async_get_config_entry_diagnostics
from custom_components.eltern_portal_schulmanager.portal import PortalAuthError, PortalConnectionError
from tests.test_eltern_portal_schulmanager import _fake_result

MANAGER = "custom_components.eltern_portal_schulmanager.manager.SchulManager"
PORTAL = {"school": "bspgym", "school_name": "Example", "username": "private@example.invalid", "password": "private-secret"}


@pytest.fixture(autouse=True)
def custom_integrations(hass, enable_custom_integrations, tmp_path):
    hass.config.language = "de"
    hass.config.media_dirs = {"local": str(tmp_path)}


async def setup_entry(hass, portals=None):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"portals": portals or [dict(PORTAL)]}, options={"dashboard": "off"})
    entry.add_to_hass(hass)
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date(), with_pdf=False)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_auth_failure_starts_one_flow_and_recovers(hass):
    entry = await setup_entry(hass)
    manager = entry.runtime_data
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=PortalAuthError("invalid credentials")):
        await manager.async_refresh()
        await hass.async_block_till_done()
        await manager.async_refresh()
        await hass.async_block_till_done()
    flows = list(entry.async_get_active_flows(hass))
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert manager.portal_status == {"bspgym": "auth_failed"}
    assert hass.states.get("sensor.schule_anna_krankmeldungen").state == "unavailable"
    assert hass.states.get("todo.schule_anna_aufgaben").state != "unavailable"
    assert manager.children
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date(), with_pdf=False)):
        await manager.async_refresh()
        await hass.async_block_till_done()
    assert manager.portal_status == {"bspgym": "ok"}
    assert manager.last_errors == []
    assert hass.states.get("sensor.schule_anna_krankmeldungen").state != "unavailable"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_outage_does_not_block_other_school_and_logs_once(hass, caplog):
    entry = await setup_entry(hass, [PORTAL, {**PORTAL, "school": "other"}])
    manager = entry.runtime_data
    before = deepcopy(manager.data)
    other = _fake_result(dt_util.now().date(), with_pdf=False)
    other.school = "other"
    other.children[0].firstname = "Ben"
    other.children[0].fullname = "Ben Example"
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=[PortalConnectionError("offline"), other, PortalConnectionError("offline"), other]):
        await manager.async_refresh()
        await manager.async_refresh()
        await hass.async_block_till_done()
    assert manager.portal_status == {"bspgym": "connection_failed", "other": "ok"}
    assert "anna" in manager.children and "ben" in manager.children
    assert all(uid in manager.items for uid in before["items"])
    assert caplog.text.count("bspgym: Eltern-Portal unavailable or incomplete") == 1
    with patch(f"{MANAGER}._async_fetch_portal", return_value=_fake_result(dt_util.now().date(), with_pdf=False)):
        await manager.async_refresh()
    assert caplog.text.count("bspgym: Eltern-Portal available again") == 1
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(("error", "expected"), [(PortalAuthError("invalid"), ConfigEntryAuthFailed), (PortalConnectionError("offline"), ConfigEntryNotReady)])
async def test_initial_failure_has_home_assistant_retry_semantics(hass, error, expected):
    from custom_components.eltern_portal_schulmanager.manager import SchulManager
    entry = MockConfigEntry(domain=DOMAIN, data={"portals": [PORTAL]})
    entry.add_to_hass(hass)
    manager = SchulManager(hass, entry)
    await manager.async_load()
    with patch(f"{MANAGER}._async_fetch_portal", side_effect=error), pytest.raises(expected):
        await manager.async_refresh(initial=True)


async def test_diagnostics_contains_counts_never_content(hass):
    entry = await setup_entry(hass)
    manager = entry.runtime_data
    manager.last_errors = ["private-secret private@example.invalid Anna https://private.example.invalid"]
    manager.portal_status = {"bspgym": "connection_failed"}
    before = deepcopy(manager.data)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["portals"] == {"configured": 1, "not_checked": 0, "ok": 0, "partial": 0, "auth_failed": 0, "connection_failed": 1}
    assert report["stored"]["children"] == 1
    assert report["error_count"] == 1
    assert report["last_fetch"] == manager.last_update.isoformat()
    for private in ("private-secret", "private@example.invalid", "Anna", "anna", "bspgym", "Klassenfahrt", "IBAN", "https://"):
        assert private not in json.dumps(report)
    assert manager.data == before
    manager.last_update = None
    manager.portal_status.clear()
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["last_fetch"] is None
    assert report["portals"]["not_checked"] == 1
    await hass.config_entries.async_unload(entry.entry_id)
