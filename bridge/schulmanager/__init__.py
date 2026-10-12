"""Bridge release: moves "Schulmanager" (domain ``schulmanager``) to Eltern Portal Manager Bavaria.

Background (see the bridge issue on GitHub): 0.14.0 renamed the domain to
``eltern_portal_schulmanager``. HACS installed the new code next to the old folder, but
Home Assistant kept loading the old 0.13 code because the existing config entry belongs to
the old domain. The new integration had no entry and was never loaded, so nobody was told to
take over.

This package is released once more under the old domain, so HACS installs it over 0.13 as a
normal update. It carries the complete new integration in ``payload/`` and:

1. copies it to ``custom_components/eltern_portal_schulmanager`` (or updates an older copy),
2. starts the new integration's config flow with ``source=import`` and the old entry id.
   The new integration's ``async_migrate`` then takes everything over (data, entities,
   history, media, dashboards), removes the old entry and this folder, and asks for one
   restart.

Entries that are not ours (e.g. "Schulmanager Online", same domain) are never touched.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
from typing import Any

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType
import logging

DOMAIN = "schulmanager"
NEW_DOMAIN = "eltern_portal_schulmanager"
NEW_NAME = "Eltern Portal Manager Bavaria"
CONF_PORTALS = "portals"
CONF_MIGRATED_FROM = "migrated_from"
ISSUE_FAILED = "handover_failed"
PAYLOAD = os.path.join(os.path.dirname(__file__), "payload", NEW_DOMAIN)

LOGGER = logging.getLogger(__package__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def is_own_entry(entry: ConfigEntry) -> bool:
    """Is this ``schulmanager`` entry ours (and not Schulmanager Online)?"""
    portals = entry.data.get(CONF_PORTALS)
    return isinstance(portals, list) and bool(portals)


# ----------------------------------------------------------------------
# Payload
# ----------------------------------------------------------------------
def _version(manifest: str) -> str | None:
    try:
        with open(manifest, encoding="utf-8") as fh:
            return str(json.load(fh).get("version") or "") or None
    except (OSError, ValueError):
        return None


def _is_newer(candidate: str | None, installed: str | None) -> bool:
    from awesomeversion import AwesomeVersion

    if not candidate:
        return False
    if not installed:
        return True
    try:
        return AwesomeVersion(candidate) > AwesomeVersion(installed)
    except Exception:  # noqa: BLE001
        return candidate != installed


def install_payload(config_dir: str, payload: str = PAYLOAD) -> bool:
    """Copy the new integration to ``custom_components``. Returns True if files changed."""
    target = os.path.join(config_dir, "custom_components", NEW_DOMAIN)
    if not os.path.isfile(os.path.join(payload, "manifest.json")):
        raise FileNotFoundError(f"Payload missing: {payload}")
    if os.path.isdir(target) and not _is_newer(
        _version(os.path.join(payload, "manifest.json")),
        _version(os.path.join(target, "manifest.json")),
    ):
        return False
    tmp = target + ".bridge-new"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(payload, tmp, ignore=shutil.ignore_patterns("__pycache__"))
    old = target + ".bridge-old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(target):
        os.rename(target, old)
    os.rename(tmp, target)
    shutil.rmtree(old, ignore_errors=True)
    LOGGER.info("Installed %s into %s", NEW_NAME, target)
    return True


async def async_install_new_integration(hass: HomeAssistant) -> None:
    """Install the payload and make Home Assistant see the new integration."""
    from homeassistant import loader

    changed = await hass.async_add_executor_job(install_payload, hass.config.config_dir)
    if changed:
        importlib.invalidate_caches()
        # Same as HACS does after installing an integration
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await loader.async_get_custom_components(hass)
        cache = hass.data.get(loader.DATA_INTEGRATIONS)
        if isinstance(cache, dict):
            cache.pop(NEW_DOMAIN, None)


# ----------------------------------------------------------------------
# Handover
# ----------------------------------------------------------------------
async def async_handover(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Install the new integration and let it take over ``entry``."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        return
    try:
        await async_install_new_integration(hass)
        if hass.config_entries.async_entries(NEW_DOMAIN):
            LOGGER.warning(
                "%s is already set up – the old entry %s is left for manual removal",
                NEW_NAME,
                entry.entry_id,
            )
            _create_issue(hass, "already_set_up")
            return
        await hass.config_entries.flow.async_init(
            NEW_DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_MIGRATED_FROM: entry.entry_id},
        )
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FAILED)
    except Exception as err:  # noqa: BLE001
        LOGGER.exception("Automatic takeover by %s failed", NEW_NAME)
        _create_issue(hass, str(err) or type(err).__name__)


@callback
def _create_issue(hass: HomeAssistant, error: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_FAILED,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_FAILED,
        translation_placeholders={"error": error, "new_name": NEW_NAME},
        learn_more_url="https://github.com/FabusMingAI/ha-schulmanager#renamed-from-schulmanager",
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not is_own_entry(entry):
        LOGGER.error(
            "Entry %s does not belong to Eltern Portal Manager Bavaria – not touched", entry.title
        )
        return False

    @callback
    def _start(_: Event | None = None) -> None:
        # Run outside of setup: the takeover unloads and removes this entry.
        hass.async_create_background_task(
            async_handover(hass, entry), f"{DOMAIN}_handover", eager_start=False
        )

    if hass.state is CoreState.running:
        _start()
    else:
        entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _start))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
