"""Einrichtung des Schulmanagers in der Home-Assistant-Oberfläche."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_AI_ENTITY,
    CONF_ANALYZE_DAYS,
    CONF_AUTO_DOWNLOAD,
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_LOOKBACK_DAYS,
    CONF_NOTIFY,
    CONF_PORTALS,
    CONF_REMINDER_DAYS,
    CONF_REMINDER_TIME,
    CONF_SCAN_INTERVAL,
    CONF_SCHOOL,
    CONF_SCHOOL_NAME,
    CONF_TTS_END,
    CONF_TTS_ENGINE,
    CONF_TTS_START,
    CONF_TTS_TARGETS,
    DEFAULT_ANALYZE_DAYS,
    DEFAULT_AUTO_DOWNLOAD,
    DEFAULT_DIGEST_ENABLED,
    DEFAULT_DIGEST_TIME,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_REMINDER_DAYS,
    DEFAULT_REMINDER_TIME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TTS_END,
    DEFAULT_TTS_START,
    DOMAIN,
    LOGGER,
)
from .portal import (
    PortalAuthError,
    PortalConnectionError,
    async_validate,
    school_from_input,
)


def _portal_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_SCHOOL, default=d.get(CONF_SCHOOL, "")): str,
            vol.Required(CONF_USERNAME, default=d.get(CONF_USERNAME, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
            ),
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


async def _check_portal(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    school = school_from_input(user_input[CONF_SCHOOL])
    session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar())
    try:
        name = await async_validate(
            session, school, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
        )
    except PortalAuthError as err:
        LOGGER.debug("Anmeldung fehlgeschlagen: %s", err)
        if "school" in str(err):
            return None, {CONF_SCHOOL: "invalid_school"}
        return None, {"base": "invalid_auth"}
    except PortalConnectionError as err:
        LOGGER.debug("Portal nicht erreichbar: %s", err)
        return None, {CONF_SCHOOL: "cannot_connect"}
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unerwarteter Fehler bei der Anmeldung")
        return None, {"base": "unknown"}
    finally:
        await session.close()
    return {
        CONF_SCHOOL: school,
        CONF_SCHOOL_NAME: name,
        CONF_USERNAME: user_input[CONF_USERNAME].strip().lower(),
        CONF_PASSWORD: user_input[CONF_PASSWORD],
    }, {}


class SchulmanagerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Erst-Einrichtung: ein oder mehrere Eltern-Portale."""

    VERSION = 1

    def __init__(self) -> None:
        self._portals: list[dict[str, Any]] = []
        self._last: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            school = school_from_input(user_input[CONF_SCHOOL])
            if any(p[CONF_SCHOOL] == school for p in self._portals):
                errors[CONF_SCHOOL] = "already_added"
            else:
                portal, errors = await _check_portal(self.hass, user_input)
                if portal:
                    self._portals.append(portal)
                    self._last = {CONF_USERNAME: portal[CONF_USERNAME]}
                    return await self.async_step_more()
        return self.async_show_form(
            step_id="user",
            data_schema=_portal_schema(user_input or self._last),
            errors=errors,
            description_placeholders={
                "added": ", ".join(p[CONF_SCHOOL_NAME] for p in self._portals) or "–"
            },
        )

    async def async_step_more(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="more",
            menu_options=["user", "finish"],
            description_placeholders={
                "added": "\n".join(f"• {p[CONF_SCHOOL_NAME]}" for p in self._portals)
            },
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_create_entry(
            title="Schulmanager",
            data={CONF_PORTALS: self._portals},
            options={},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        portals = entry.data[CONF_PORTALS]
        errors: dict[str, str] = {}
        if user_input is not None:
            old = next(p for p in portals if p[CONF_SCHOOL] == user_input[CONF_SCHOOL])
            portal, errors = await _check_portal(
                self.hass,
                {
                    CONF_SCHOOL: old[CONF_SCHOOL],
                    CONF_USERNAME: user_input.get(CONF_USERNAME) or old[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                },
            )
            if portal:
                new = [portal if p[CONF_SCHOOL] == portal[CONF_SCHOOL] else p for p in portals]
                return self.async_update_reload_and_abort(entry, data={CONF_PORTALS: new})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHOOL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": p[CONF_SCHOOL], "label": p[CONF_SCHOOL_NAME]}
                                for p in portals
                            ]
                        )
                    ),
                    vol.Optional(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SchulmanagerOptionsFlow()


class SchulmanagerOptionsFlow(OptionsFlow):
    """Einstellungen sowie Schulen hinzufügen/entfernen."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["settings", "add_portal", "remove_portal"]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        notify_services = sorted(
            s
            for s in self.hass.services.async_services_for_domain("notify")
            if s not in ("send_message", "persistent_notification")
        )

        def opt(key: str, default: Any) -> dict[str, Any]:
            value = o.get(key, default)
            return {"default": value} if value not in (None, "") else {}

        schema = vol.Schema(
            {
                vol.Optional(CONF_AI_ENTITY, description={"suggested_value": o.get(CONF_AI_ENTITY)}): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="ai_task")
                ),
                vol.Optional(CONF_NOTIFY, **opt(CONF_NOTIFY, [])): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_services,
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_DIGEST_ENABLED, **opt(CONF_DIGEST_ENABLED, DEFAULT_DIGEST_ENABLED)): bool,
                vol.Optional(CONF_DIGEST_TIME, **opt(CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME)): selector.TimeSelector(),
                vol.Optional(CONF_REMINDER_TIME, **opt(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME)): selector.TimeSelector(),
                vol.Optional(CONF_REMINDER_DAYS, **opt(CONF_REMINDER_DAYS, DEFAULT_REMINDER_DAYS)): str,
                vol.Optional(CONF_TTS_TARGETS, **opt(CONF_TTS_TARGETS, [])): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["assist_satellite", "media_player"], multiple=True
                    )
                ),
                vol.Optional(CONF_TTS_ENGINE, description={"suggested_value": o.get(CONF_TTS_ENGINE)}): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="tts")
                ),
                vol.Optional(CONF_TTS_START, **opt(CONF_TTS_START, DEFAULT_TTS_START)): selector.TimeSelector(),
                vol.Optional(CONF_TTS_END, **opt(CONF_TTS_END, DEFAULT_TTS_END)): selector.TimeSelector(),
                vol.Optional(CONF_SCAN_INTERVAL, **opt(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=360, step=5, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_AUTO_DOWNLOAD, **opt(CONF_AUTO_DOWNLOAD, DEFAULT_AUTO_DOWNLOAD)): bool,
                vol.Optional(CONF_ANALYZE_DAYS, **opt(CONF_ANALYZE_DAYS, DEFAULT_ANALYZE_DAYS)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=365, unit_of_measurement="Tage", mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_LOOKBACK_DAYS, **opt(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS)): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=7, max=400, unit_of_measurement="Tage", mode=selector.NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_add_portal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        portals = list(self.config_entry.data.get(CONF_PORTALS, []))
        if user_input is not None:
            school = school_from_input(user_input[CONF_SCHOOL])
            if any(p[CONF_SCHOOL] == school for p in portals):
                errors[CONF_SCHOOL] = "already_added"
            else:
                portal, errors = await _check_portal(self.hass, user_input)
                if portal:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data={CONF_PORTALS: [*portals, portal]}
                    )
                    return self.async_abort(reason="portal_added")
        defaults = user_input or (
            {CONF_USERNAME: portals[0][CONF_USERNAME]} if portals else {}
        )
        return self.async_show_form(
            step_id="add_portal", data_schema=_portal_schema(defaults), errors=errors
        )

    async def async_step_remove_portal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        portals = list(self.config_entry.data.get(CONF_PORTALS, []))
        if user_input is not None:
            school = user_input[CONF_SCHOOL]
            if len(portals) <= 1:
                return self.async_abort(reason="last_portal")
            manager = getattr(self.config_entry, "runtime_data", None)
            if manager is not None:
                manager.remove_portal_data(school)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={CONF_PORTALS: [p for p in portals if p[CONF_SCHOOL] != school]},
            )
            return self.async_abort(reason="portal_removed")
        return self.async_show_form(
            step_id="remove_portal",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCHOOL): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": p[CONF_SCHOOL], "label": p[CONF_SCHOOL_NAME]}
                                for p in portals
                            ]
                        )
                    )
                }
            ),
        )
