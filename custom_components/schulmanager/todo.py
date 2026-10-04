"""To-do-Liste „Schule <Kind>“ – erkannte und eigene Aufgaben."""

from __future__ import annotations

from datetime import date, datetime
import re

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SchulConfigEntry
from .const import STATUS_DONE, STATUS_OPEN, STATUS_PROGRESS, TASK_TYPE_ICONS
from .entity import SchulEntity
from .manager import SchulManager

_ICONS = "|".join(re.escape(i) for i in TASK_TYPE_ICONS.values())
_RE_DECOR = re.compile(
    rf"^(?:⏳\s*)?(?:(?:{_ICONS})\s*)?(?:\d{{2}}\.\d{{2}}\.(?:\d{{4}})?\s*·\s*)?|\s*\([\d.,]+\s*€\)$"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SchulConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    manager = entry.runtime_data
    async_add_entities(SchulTodo(manager, child) for child in manager.children)


class SchulTodo(SchulEntity, TodoListEntity):
    """Aufgabenliste eines Kindes."""

    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: SchulManager, child: str) -> None:
        super().__init__(manager, child, "aufgaben")
        self._attr_icon = "mdi:school"

    @property
    def todo_items(self) -> list[TodoItem]:
        m = self.manager
        out = []
        for t in m.child_tasks(self.child, include_done=True):
            out.append(
                TodoItem(
                    uid=t["id"],
                    summary=f"{'⏳ ' if t['status'] == STATUS_PROGRESS else ''}{TASK_TYPE_ICONS.get(t['type'], '✅')} {m.dated(m.task_label(t), t)}",
                    status=TodoItemStatus.COMPLETED
                    if t["status"] == STATUS_DONE
                    else TodoItemStatus.NEEDS_ACTION,
                    due=date.fromisoformat(t["due"]) if t.get("due") else None,
                    description=m.task_description(t) or None,
                    completed=datetime.fromisoformat(t["completed"]) if t.get("completed") else None,
                )
            )
        return out

    async def async_create_todo_item(self, item: TodoItem) -> None:
        self.manager.add_task(
            self.child,
            _RE_DECOR.sub("", item.summary or "Aufgabe").strip(),
            due=_due(item.due),
            details=item.description,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        task = self.manager.tasks.get(item.uid or "")
        if task is None:
            return
        changes = {
            "status": STATUS_DONE if item.status == TodoItemStatus.COMPLETED else STATUS_OPEN,
            "due": _due(item.due),
        }
        if item.description and "💬 Kommentar:" in item.description:
            item.description = None  # generierte Beschreibung nicht als Details übernehmen
        title = _RE_DECOR.sub("", item.summary or "").strip()
        if title and title != task["title"]:
            changes["title"] = title
        # Beschreibung wird generiert; nur übernehmen, wenn sie wirklich neu ist
        if item.description and item.description != self.manager.task_description(task):
            changes["details"] = item.description
        self.manager.update_task(task["id"], **changes)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        self.manager.delete_tasks(uids)


def _due(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()
