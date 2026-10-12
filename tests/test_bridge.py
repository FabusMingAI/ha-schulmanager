"""Tests for the bridge release 0.14.1 (old domain ``schulmanager``).

The bridge is built from ``bridge/schulmanager`` with ``scripts/build_bridge.py`` into the
config folder of the test instance, exactly as HACS would install it.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest

from homeassistant import config_entries, loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components
from custom_components.eltern_portal_schulmanager.const import DOMAIN, LEGACY_DOMAIN

from .test_eltern_portal_schulmanager import _fake_result

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORTALS = [{"school": "bspgym", "school_name": "Beispiel-Gymnasium", "username": "x@y.de", "password": "p"}]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass, enable_custom_integrations):
    hass.config.language = "de"
    yield


@pytest.fixture
def bridge(hass: HomeAssistant, tmp_path):
    """Build the bridge into <config>/custom_components/schulmanager and make it loadable."""
    config = tmp_path / "config"
    target = config / "custom_components"
    target.mkdir(parents=True)
    hass.config.config_dir = str(config)
    hass.config.media_dirs = {"local": str(tmp_path / "media")}
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_bridge.py"), "--out", str(target)],
        check=True,
        capture_output=True,
    )
    custom_components.__path__.append(str(target))
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield target / "schulmanager"
    custom_components.__path__.remove(str(target))
    for name in [m for m in sys.modules if m.startswith("custom_components.schulmanager")]:
        del sys.modules[name]


async def _settle(hass: HomeAssistant) -> None:
    """Let the bridge's background handover finish (the new integration keeps own tasks running)."""
    import asyncio

    for _ in range(100):
        await hass.async_block_till_done()
        tasks = [t for t in hass._background_tasks if "schulmanager_handover" in getattr(t, "get_name", lambda: "")()]
        if not tasks:
            break
        await asyncio.sleep(0.02)
    await hass.async_block_till_done()


def _patch_fetch():
    today = dt_util.now().date()

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today, with_pdf=False)

    return patch("custom_components.eltern_portal_schulmanager.portal.SchulPortal.async_fetch", fake_fetch)


async def test_bridge_takes_over_automatically(hass: HomeAssistant, bridge) -> None:
    """0.13 setup + bridge from HACS: the takeover happens without any click."""
    old = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Schulmanager",
        data={"portals": PORTALS},
        options={"reminder_days": "2,0"},
        unique_id=LEGACY_DOMAIN,
        entry_id="old01",
    )
    old.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    status = ent_reg.async_get_or_create(
        "sensor", LEGACY_DOMAIN, "old01_anna_ampel", config_entry=old,
        suggested_object_id="schule_anna_status",
    )
    await Store(hass, 1, f"{LEGACY_DOMAIN}.old01").async_save({
        "tasks": {"t1": {"id": "t1", "child": "anna", "title": "Eigene Aufgabe", "type": "aufgabe",
                         "status": "in_arbeit", "source": "manuell", "created": dt_util.now().isoformat()}},
        "children": {"anna": {"name": "Anna", "school": "bspgym", "school_name": "Beispiel-Gymnasium",
                              "classname": "8b", "student_id": "7"}},
        "initialized": ["bspgym"],
    })

    with _patch_fetch():
        assert await hass.config_entries.async_setup(old.entry_id)
        await _settle(hass)
        await _settle(hass)

    # the new integration was installed next to the bridge …
    installed = pathlib.Path(hass.config.path("custom_components", DOMAIN))
    assert json.loads((installed / "manifest.json").read_text())["version"] == "0.14.1"
    # … took over the old setup …
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    new = entries[0]
    assert new.state is ConfigEntryState.LOADED
    assert new.data["portals"] == PORTALS and "migrated_from" not in new.data
    assert new.options["reminder_days"] == "2,0"
    assert new.runtime_data.tasks["t1"]["status"] == "in_arbeit"
    moved = ent_reg.async_get(status.entity_id)
    assert moved.platform == DOMAIN and moved.config_entry_id == new.entry_id
    # … removed the old entry and the bridge folder, and told the user
    assert hass.config_entries.async_get_entry("old01") is None
    assert not bridge.exists()
    from homeassistant.components.persistent_notification import _async_get_or_create_notifications

    assert f"{DOMAIN}_migration" in _async_get_or_create_notifications(hass)
    assert ir.async_get(hass).async_get_issue(LEGACY_DOMAIN, "handover_failed") is None
    await hass.config_entries.async_unload(new.entry_id)


async def test_bridge_never_touches_schulmanager_online(hass: HomeAssistant, bridge) -> None:
    """An entry of Schulmanager Online (same domain, no portals) is left alone."""
    other = MockConfigEntry(
        domain=LEGACY_DOMAIN, title="Schulmanager Online", data={"username": "z@y.de"}, entry_id="other1"
    )
    other.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(other.entry_id)
    await _settle(hass)
    assert hass.config_entries.async_get_entry("other1") is not None
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not os.path.exists(hass.config.path("custom_components", DOMAIN))


async def test_bridge_new_setup_points_to_new_name(hass: HomeAssistant, bridge) -> None:
    """Adding "Schulmanager" during the bridge period installs the new integration and explains."""
    result = await hass.config_entries.flow.async_init(
        LEGACY_DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "moved"
    assert os.path.isfile(hass.config.path("custom_components", DOMAIN, "manifest.json"))
    assert not hass.config_entries.async_entries(LEGACY_DOMAIN)


async def test_bridge_with_existing_new_setup(hass: HomeAssistant, bridge) -> None:
    """Already taken over by hand (0.14.0): no second entry, a repair notice instead."""
    new = MockConfigEntry(domain=DOMAIN, data={"portals": PORTALS}, unique_id=DOMAIN)
    new.add_to_hass(hass)
    old = MockConfigEntry(
        domain=LEGACY_DOMAIN, title="Schulmanager", data={"portals": PORTALS}, entry_id="old01"
    )
    old.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old.entry_id)
    await _settle(hass)
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert ir.async_get(hass).async_get_issue(LEGACY_DOMAIN, "handover_failed") is not None


async def test_leftover_bridge_removed_on_start(hass: HomeAssistant, bridge) -> None:
    """Bridge installed by HACS after the takeover: the new integration removes the folder."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert bridge.is_dir()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await _settle(hass)
    assert not bridge.exists()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_leftover_bridge_kept_while_old_setup_exists(hass: HomeAssistant, bridge) -> None:
    from custom_components.eltern_portal_schulmanager.migration import async_remove_leftover_bridge

    MockConfigEntry(domain=LEGACY_DOMAIN, data={"portals": PORTALS}).add_to_hass(hass)
    assert not await async_remove_leftover_bridge(hass)
    assert bridge.is_dir()


def test_install_payload_versions(tmp_path) -> None:
    """Payload is copied when missing or newer, never downgraded."""
    import importlib.util

    out = tmp_path / "build"
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_bridge.py"), "--out", str(out)],
        check=True, capture_output=True,
    )
    spec = importlib.util.spec_from_file_location(
        "bridge_under_test", out / "schulmanager" / "__init__.py",
        submodule_search_locations=[str(out / "schulmanager")],
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    config = tmp_path / "config"
    target = config / "custom_components" / "eltern_portal_schulmanager"
    assert mod.install_payload(str(config))
    assert json.loads((target / "manifest.json").read_text())["version"] == "0.14.1"
    assert not mod.install_payload(str(config))  # same version: nothing to do
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["version"] = "0.15.0"
    (target / "manifest.json").write_text(json.dumps(manifest))
    assert not mod.install_payload(str(config))  # newer one installed: keep it
    manifest["version"] = "0.13.9"
    (target / "manifest.json").write_text(json.dumps(manifest))
    assert mod.install_payload(str(config))
    assert not list(target.parent.glob("*.bridge-*"))
