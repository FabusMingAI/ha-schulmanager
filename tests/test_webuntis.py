"""Regression tests for WebUntis examples from issue #17."""

import json
from custom_components.eltern_portal_schulmanager.webuntis import parse_webuntis_event


def event(**fields):
    data = {"id": 42, "code": "None", "subjects": [{"name": "Math"}],
            "rooms": [{"name": "101"}], "original_rooms": [],
            "teachers": [{"name": "A"}], "original_teachers": []}
    data.update(fields)
    return {"start": "2026-10-15T08:00:00+02:00",
            "end": "2026-10-15T08:45:00+02:00",
            "summary": "Math", "description": json.dumps(data)}


def test_normal_lesson_ignored():
    assert parse_webuntis_event(event()) is None


def test_cancelled_lesson():
    result = parse_webuntis_event(event(code="cancelled"))
    assert result["kind"] == "entfall"


def test_room_and_teacher_change():
    result = parse_webuntis_event(event(
        original_rooms=[{"name": "102"}],
        original_teachers=[{"name": "B"}],
    ))
    assert result["kind"] == "vertretung"
    assert result["original_room"] == "102"


def test_missing_current_teacher_is_not_automatically_cancelled():
    lesson = event(original_teachers=[{"name": "B"}])
    data = json.loads(lesson["description"])
    del data["teachers"]
    lesson["description"] = json.dumps(data)
    assert parse_webuntis_event(lesson) is None


def test_invalid_description_ignored():
    assert parse_webuntis_event({"description": "not JSON"}) is None
