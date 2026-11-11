"""Migration recovery preserves user files when storage or old integrations fail."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.eltern_portal_schulmanager import migration as m
from custom_components.eltern_portal_schulmanager.const import DOMAIN
from tests.test_silver_behaviour import enable


async def test_missing_migration_data_and_broken_old_integration(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await m.async_migrate(hass, entry) is None
    old = MockConfigEntry(domain="schulmanager", data={"portals": [{"school": "demo"}]}, state=ConfigEntryState.LOADED)
    old.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={"migrated_from": old.entry_id})
    with patch.object(hass.config_entries, "async_unload", side_effect=ValueError("old unload failed")), patch.object(hass.config_entries, "async_remove", side_effect=ValueError("old removal failed")):
        assert await m.async_migrate(hass, entry) is None
    assert "migrated_from" not in entry.data
    assert hass.config_entries.async_get_entry(old.entry_id) is old


async def test_media_roots_and_failed_move_keep_original(hass, tmp_path):
    hass.config.media_dirs = {}
    assert m._media_base(hass) == hass.config.path("media")
    hass.config.media_dirs = {"other": str(tmp_path)}
    assert m._media_base(hass) == str(tmp_path)
    source = tmp_path / "schulmanager" / "test.pdf"
    source.parent.mkdir()
    source.write_bytes(b"fictional")
    data = {"items": {"x": {"files": [{"path": "schulmanager/test.pdf"}, {"path": "unrelated.pdf"}]}}}
    with patch.object(m.os, "renames", side_effect=PermissionError("read only")):
        await m._async_move_media(hass, data)
    assert source.exists()
    assert data["items"]["x"]["files"][0]["path"] == "schulmanager/test.pdf"


async def test_migrate_dashboard_variants(hass):
    from custom_components.eltern_portal_schulmanager.dashboard import _hash
    from custom_components.eltern_portal_schulmanager.const import DASHBOARD_URL
    old = {"views": [{"cards": [{"type": "custom:schulmanager-card"}]}]}
    good = SimpleNamespace(mode="storage", config={"title": "School"}, async_load=AsyncMock(return_value=old), async_save=AsyncMock())
    hass.data["lovelace"] = SimpleNamespace(dashboards={
        "yaml": SimpleNamespace(mode="yaml"),
        "broken": SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(side_effect=ValueError("empty"))),
        "empty": SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(return_value={})),
        "other": SimpleNamespace(mode="storage", async_save=AsyncMock(), async_load=AsyncMock(return_value={"views": []})),
        DASHBOARD_URL: good,
    })
    state = {"dashboard": {"hash": _hash(old)}}
    assert await m._async_rewrite_dashboards(hass, state) == ["School"]
    saved = good.async_save.call_args.args[0]
    assert state["dashboard"]["hash"] == _hash(saved)
    assert "eltern-portal" in str(saved)


async def test_frontend_cleanup_loads_resources_and_keeps_foreign_files(hass):
    resources = SimpleNamespace(loaded=False, async_load=AsyncMock(), async_items=Mock(return_value=[]), async_delete_item=AsyncMock())
    hass.data["lovelace"] = SimpleNamespace(resources=resources)
    folder = Path(hass.config.path("www", "schulmanager"))
    folder.mkdir(parents=True, exist_ok=True)
    (folder/"foreign.txt").write_text("keep")
    await m._async_cleanup_frontend(hass)
    resources.async_load.assert_awaited_once()
    assert (folder/"foreign.txt").exists()
    resources.loaded = False
    resources.async_load.side_effect = OSError("storage unavailable")
    await m._async_cleanup_frontend(hass)
    assert (folder/"foreign.txt").exists()
    static = Path(hass.config.path("www", DOMAIN))
    static.mkdir(exist_ok=True)
    with patch.object(m.os, "scandir", side_effect=PermissionError):
        assert not await m.async_cleanup_static_copies(hass)
    assert static.exists()


async def test_reload_rechecks_legacy_repairs_after_start(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    previous = hass.state
    hass.state = CoreState.not_running
    with patch.object(m, "async_check_legacy_references") as check:
        m.async_watch_legacy_references(hass, entry)
        hass.bus.async_fire("homeassistant_started")
        await hass.async_block_till_done()
        hass.bus.async_fire("call_service", {"domain": "script", "service": "reload"})
        await hass.async_block_till_done()
        async_fire_time_changed(hass, dt_util.now()+timedelta(seconds=3))
        await hass.async_block_till_done()
        assert check.called
    hass.state = previous
