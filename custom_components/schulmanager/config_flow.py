"""Config flow of the bridge: new setups go to Eltern Portal Manager Bavaria."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import DOMAIN, LOGGER, NEW_NAME, async_install_new_integration


class SchulmanagerBridgeFlow(ConfigFlow, domain=DOMAIN):
    """No new setups under the old name – install the new integration instead."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        try:
            await async_install_new_integration(self.hass)
        except Exception:  # noqa: BLE001
            LOGGER.exception("Could not install %s", NEW_NAME)
            return self.async_abort(reason="install_failed", description_placeholders={"new_name": NEW_NAME})
        return self.async_abort(reason="moved", description_placeholders={"new_name": NEW_NAME})
