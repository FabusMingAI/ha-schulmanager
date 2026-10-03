"""WebSocket-API für die Schulmanager-Karte im Dashboard."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .analyzer import fmt_eur
from .const import (
    DOMAIN,
    KIND_LABELS,
    SIGNAL_UPDATED,
    STATUS_DONE,
    STATUS_LABELS,
    TASK_TYPE_ICONS,
)

MAX_DONE_DAYS = 45


def _manager(hass: HomeAssistant):
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data
    return None


def _task_light(m, t: dict[str, Any]) -> dict[str, Any]:
    today = dt_util.now().date()
    item = m.items.get(t.get("item_uid") or "")
    return {
        "id": t["id"],
        "title": t["title"],
        "type": t.get("type"),
        "icon": TASK_TYPE_ICONS.get(t.get("type"), "✅"),
        "status": t["status"],
        "status_label": STATUS_LABELS.get(t["status"], t["status"]),
        "due": t.get("due"),
        "days": (date.fromisoformat(t["due"]) - today).days if t.get("due") else None,
        "amount": t.get("amount"),
        "amount_text": fmt_eur(t.get("amount")) if t.get("amount") else None,
        "comment": t.get("comment"),
        "source": t.get("source"),
        "completed": t.get("completed"),
        "item_uid": t.get("item_uid"),
        "item_title": item.get("title") if item else None,
        "has_files": bool(item and item.get("files")),
    }


def _item_light(m, i: dict[str, Any]) -> dict[str, Any]:
    a = i.get("analysis", {})
    return {
        "uid": i["uid"],
        "kind": i["kind"],
        "kind_label": KIND_LABELS.get(i["kind"], i["kind"]),
        "title": i["title"],
        "sent": i.get("sent"),
        "sender": i.get("sender"),
        "summary": a.get("summary"),
        "urgency": a.get("urgency"),
        "analysis": a.get("status"),
        "read": bool(i.get("read")),
        "files": len(i.get("files", [])),
        "tasks_open": sum(
            1
            for t in m.tasks.values()
            if t.get("item_uid") == i["uid"] and t["status"] != STATUS_DONE
        ),
    }


def _item_full(hass: HomeAssistant, m, i: dict[str, Any]) -> dict[str, Any]:
    from . import file_url

    out = _item_light(m, i)
    out.update(
        body=i.get("body") or "",
        text=i.get("text") or "",
        url=i.get("url"),
        school=i.get("school_name"),
        analysis_method=i.get("analysis", {}).get("method"),
        files=[
            {
                "name": f["path"].rsplit("/", 1)[-1],
                "url": file_url(hass, i["uid"], n),
                "content_type": f.get("content_type"),
                "size": f.get("size"),
            }
            for n, f in enumerate(i.get("files", []))
        ],
        tasks=[
            _task_light(m, t)
            for t in m.tasks.values()
            if t.get("item_uid") == i["uid"]
        ],
    )
    return out


@websocket_api.websocket_command(
    {vol.Required("type"): "schulmanager/data", vol.Optional("child"): str}
)
@callback
def ws_data(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    m = _manager(hass)
    if m is None:
        connection.send_error(msg["id"], "not_loaded", "Schulmanager ist nicht geladen")
        return
    today = dt_util.now().date()
    children = []
    for key, info in sorted(m.children.items()):
        if msg.get("child") and key != msg["child"]:
            continue
        s = m.child_summary(key)
        tasks = []
        for t in m.child_tasks(key, include_done=True):
            if t["status"] == STATUS_DONE and t.get("completed"):
                done_day = dt_util.parse_datetime(t["completed"])
                if done_day and (today - done_day.date()).days > MAX_DONE_DAYS:
                    continue
            tasks.append(_task_light(m, t))
        children.append(
            {
                "key": key,
                "name": info["name"],
                "classname": info.get("classname"),
                "school": info.get("school_name"),
                "portal_url": info.get("portal_url"),
                "ampel": s["ampel"],
                "overdue": len(s["overdue"]),
                "unread": len(s["unread"]),
                "payments_total": s["payments_total"],
                "payments_text": fmt_eur(s["payments_total"]) if s["payments_total"] else None,
                "tasks": tasks,
                "items": [_item_light(m, i) for i in m.child_items(key)[:60]],
            }
        )
    connection.send_result(
        msg["id"],
        {
            "children": children,
            "last_update": m.last_update.isoformat() if m.last_update else None,
            "errors": m.last_errors,
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "schulmanager/item", vol.Required("item_id"): str}
)
@callback
def ws_item(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    m = _manager(hass)
    item = m.items.get(msg["item_id"]) if m else None
    if item is None:
        connection.send_error(msg["id"], "not_found", "Mitteilung nicht gefunden")
        return
    connection.send_result(msg["id"], _item_full(hass, m, item))


@websocket_api.websocket_command(
    {vol.Required("type"): "schulmanager/task", vol.Required("task_id"): str}
)
@callback
def ws_task(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    m = _manager(hass)
    task = m.tasks.get(msg["task_id"]) if m else None
    if task is None:
        connection.send_error(msg["id"], "not_found", "Aufgabe nicht gefunden")
        return
    out = _task_light(m, task)
    out.update(
        details=task.get("details"),
        payee=task.get("payee"),
        iban=task.get("iban"),
        reference=task.get("reference"),
        comment_at=task.get("comment_at"),
        created=task.get("created"),
        child=task.get("child"),
        child_name=m.children.get(task.get("child") or "", {}).get("name"),
    )
    item = m.items.get(task.get("item_uid") or "")
    out["item"] = _item_full(hass, m, item) if item else None
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({vol.Required("type"): "schulmanager/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    m = _manager(hass)
    if m is None:
        connection.send_error(msg["id"], "not_loaded", "Schulmanager ist nicht geladen")
        return

    @callback
    def forward() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"changed": True}))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, f"{SIGNAL_UPDATED}_{m.entry.entry_id}", forward
    )
    connection.send_result(msg["id"])


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (ws_data, ws_item, ws_task, ws_subscribe):
        websocket_api.async_register_command(hass, handler)
