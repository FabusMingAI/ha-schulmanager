"""Exercise configuration, credential recovery and options through HA's flows."""
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientConnectionError
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eltern_portal_schulmanager.const import DOMAIN
from custom_components.eltern_portal_schulmanager.config_flow import _sectioned
from custom_components.eltern_portal_schulmanager.portal import PortalAuthError

FLOW = "custom_components.eltern_portal_schulmanager.config_flow"
PORTAL = {"school": "demo", "school_name": "Demo", "username": "parent@example.invalid", "password": "secret"}
INPUT = {key: PORTAL[key] for key in ("school", "username", "password")}


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow the custom domain in this module's flows."""


@pytest.fixture
def entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"portals": [dict(PORTAL)], "extra": "keep"}, options={"scan_interval": 30})
    entry.add_to_hass(hass)
    return entry


async def test_multiple_schools_and_duplicate_recovery(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(f"{FLOW}.async_validate", return_value="Demo"):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], INPUT)
        assert flow["type"] is FlowResultType.MENU
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": "user"})
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], INPUT)
        assert flow["errors"] == {"school": "already_added"}
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {**INPUT, "school": "other"})
        assert flow["type"] is FlowResultType.MENU
    with patch("custom_components.eltern_portal_schulmanager.async_setup_entry", return_value=True):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": "finish"})
        await hass.async_block_till_done()
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert flow["result"].unique_id == DOMAIN
    assert [p["school"] for p in flow["data"]["portals"]] == ["demo", "other"]


async def test_duplicate_entry(hass, entry):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["reason"] == "already_configured"


@pytest.mark.parametrize(("exception", "errors"), [
    (PortalAuthError("invalid school"), {"school": "invalid_school"}),
    (PortalAuthError("bad credentials"), {"base": "invalid_auth"}),
    (ClientConnectionError("offline"), {"school": "cannot_connect"}),
    (RuntimeError("unexpected"), {"base": "unknown"}),
])
async def test_setup_errors_and_recovery(hass, exception, errors):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(f"{FLOW}.async_validate", side_effect=exception):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], INPUT)
    assert flow["errors"] == errors
    with patch(f"{FLOW}.async_validate", return_value="Demo"):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], INPUT)
    with patch("custom_components.eltern_portal_schulmanager.async_setup_entry", return_value=True):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": "finish"})
        await hass.async_block_till_done()
    assert flow["result"].unique_id == DOMAIN


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
async def test_credentials_recovery_preserves_other_schools(hass, entry, source):
    second = {**PORTAL, "school": "other", "password": "other-secret"}
    hass.config_entries.async_update_entry(entry, data={**entry.data, "portals": [dict(PORTAL), second]})
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": source, "entry_id": entry.entry_id}, data=entry.data if source == "reauth" else None)
    expected_step = "reauth_confirm" if source == "reauth" else "reconfigure"
    assert flow["step_id"] == expected_step
    with patch(f"{FLOW}.async_validate", side_effect=PortalAuthError("bad credentials")):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"school": "demo", "password": "wrong"})
    assert flow["errors"] == {"base": "invalid_auth"}
    assert entry.data["portals"][0]["password"] == "secret"
    with patch(f"{FLOW}.async_validate", return_value="Demo"), patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"school": "demo", "password": "new-secret"})
        await hass.async_block_till_done()
    assert flow["reason"] == ("reauth_successful" if source == "reauth" else "reconfigure_successful")
    assert entry.data["portals"][0]["password"] == "new-secret"
    assert entry.data["portals"][0]["username"] == PORTAL["username"]
    assert entry.data["portals"][1] == second
    assert entry.data["extra"] == "keep"
    assert entry.options == {"scan_interval": 30}
    reload.assert_awaited_once_with(entry.entry_id)


async def test_credentials_new_username(hass, entry):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id})
    with patch(f"{FLOW}.async_validate", return_value="Demo"), patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {**INPUT, "username": "NEW@example.invalid"})
        await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["portals"][0]["username"] == "new@example.invalid"


async def test_migration_disappeared_while_form_open(hass):
    old = MockConfigEntry(domain="schulmanager", data={"portals": [PORTAL]}, options={"scan_interval": 60})
    old.add_to_hass(hass)
    with patch(f"{FLOW}.legacy_entries", return_value=[old]):
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert flow["step_id"] == "migrate"
    with patch(f"{FLOW}.legacy_entries", return_value=[]):
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["step_id"] == "user"


@pytest.mark.parametrize("source", ["user", "import"])
async def test_migration_keeps_options(hass, source):
    old = MockConfigEntry(domain="schulmanager", title="Old", data={"portals": [PORTAL]}, options={"scan_interval": 60})
    old.add_to_hass(hass)
    with patch(f"{FLOW}.legacy_entries", return_value=[old]), patch("custom_components.eltern_portal_schulmanager.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": source}, data={"migrated_from": old.entry_id} if source == "import" else None)
        if source == "user":
            assert result["step_id"] == "migrate"
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["result"].unique_id == DOMAIN
    assert result["options"] == old.options
    assert result["data"]["migrated_from"] == old.entry_id


async def test_import_without_legacy_entry(hass):
    flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "import"}, data={})
    assert flow["reason"] == "no_legacy_entry"


async def test_options_add_duplicate_error_and_recovery(hass, entry):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_portal"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], INPUT)
    assert flow["errors"] == {"school": "already_added"}
    with patch(f"{FLOW}.async_validate", side_effect=ClientConnectionError("offline")):
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**INPUT, "school": "other"})
    assert flow["errors"] == {"school": "cannot_connect"}
    with patch(f"{FLOW}.async_validate", return_value="Other"):
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**INPUT, "school": "other"})
    assert flow["reason"] == "portal_added"
    assert entry.data["extra"] == "keep"
    assert len(entry.data["portals"]) == 2


@pytest.mark.parametrize("runtime", [False, True])
async def test_options_remove_school(hass, entry, runtime):
    from unittest.mock import Mock
    hass.config_entries.async_update_entry(entry, data={**entry.data, "portals": [PORTAL, {**PORTAL, "school": "other"}]})
    if runtime:
        entry.runtime_data = Mock()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "remove_portal"})
    assert flow["step_id"] == "remove_portal"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"school": "other"})
    assert flow["reason"] == "portal_removed"
    assert entry.data["portals"] == [PORTAL]
    assert entry.data["extra"] == "keep"
    if runtime:
        entry.runtime_data.remove_portal_data.assert_called_once_with("other")


async def test_cannot_remove_last_school(hass, entry):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "remove_portal"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"school": "demo"})
    assert flow["reason"] == "last_portal"
    assert entry.data["portals"] == [PORTAL]


async def test_options_empty_initial_entry(hass, entry):
    hass.config_entries.async_update_entry(entry, data={"portals": []})
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_portal"})
    assert flow["step_id"] == "add_portal"


async def test_settings_sections_defaults_and_clearing(hass, entry):
    hass.config_entries.async_update_entry(entry, options={"ai_task_entity": "ai_task.test", "notify_services": ["old"], "scan_interval": 45})
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "settings"})
    assert flow["step_id"] == "settings"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"ki": {"summary_languages": []}, "benachrichtigungen": {"notify_services": []}})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert "ai_task_entity" not in entry.options
    assert entry.options["summary_languages"] == ["de", "en"]
    assert entry.options["notify_services"] == []
    assert entry.options["scan_interval"] == 45


def test_section_schema_keeps_unassigned_fields():
    schema = _sectioned(vol.Schema({vol.Optional("custom"): str}))
    assert schema({"custom": "value"}) == {"custom": "value"}
