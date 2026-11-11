"""Companion payloads must navigate to the notified content on both platforms."""
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from homeassistant.util import dt as dt_util
from tests.test_quality_runtime import setup_entry


@pytest.fixture(autouse=True)
def custom(hass, enable_custom_integrations, tmp_path):
    hass.config.language = "de"
    hass.config.media_dirs = {"local": str(tmp_path)}


async def test_item_and_task_notifications_link_to_content(hass):
    entry = await setup_entry(hass)
    manager = entry.runtime_data
    item = next(iter(manager.items.values()))
    with patch.object(manager, "_notify", new=AsyncMock(return_value=True)) as notify:
        await manager._notify_item(item)
        payload = notify.call_args.args[2]
        assert payload["url"] == payload["clickAction"]
        link = urlsplit(payload["url"])
        assert link.path == f"/dashboard-schule/{item['child']}"
        assert parse_qs(link.query) == {"sm_child": [item["child"]], "sm_item": [item["uid"]]}
        assert payload["actions"][-1]["uri"] == item["url"]
        task = {"id": "task/&?# ä", "child": item["child"], "title": "Bring a book", "type": "mitbringen", "status": "offen"}
        await manager._remind(task, dt_util.now().date())
        payload = notify.call_args.args[2]
        assert payload["url"] == payload["clickAction"]
        assert parse_qs(urlsplit(payload["url"]).query)["sm_task"] == [task["id"]]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_single_dashboard_and_generic_notification_defaults(hass):
    entry = await setup_entry(hass)
    manager = entry.runtime_data
    manager.data["dashboard"] = {"mode": "single"}
    assert manager.notification_url("anna", item="letter").startswith("/dashboard-schule/0?")
    # Remember the layout that was actually generated, even if options later differ.
    assert manager.notification_url() == "/dashboard-schule/0"
    notified = []
    async def notify(call):
        notified.append(dict(call.data))
    hass.services.async_register("notify", "mobile_app_test", notify)
    with patch.object(manager, "opt", return_value=["mobile_app_test"]):
        await manager._notify("School", "Summary", {"tag": "summary"})
    payload = notified[-1]["data"]
    assert payload["url"] == payload["clickAction"] == "/dashboard-schule/0"
    assert payload["tag"] == "summary"
    await hass.config_entries.async_unload(entry.entry_id)
