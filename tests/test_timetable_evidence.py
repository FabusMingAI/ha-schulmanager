"""Course evidence must match class, slot, year and an explicit teacher code."""
from datetime import date
from copy import deepcopy

from custom_components.eltern_portal_schulmanager.timetable import (
    course_evidence, enrich_timetable, parse_course_registrations,
)

TODAY = date(2026, 11, 6)
TEACHERS = {"KUR": "Karla Kurzweil", "LAN": "Lena Lang", "BRE": "Bruno Breit"}


def evidence(text=None, **overrides):
    return {"uid": "school-child-letter", "title": "Förderangebote 2026/2027",
            "sent": "2026-09-15T19:08:00", "url": "https://example.org/letter",
            "text": text or "Freiwillige Intensivierungen\nInt_M_6a Mathe Kl. 6a Mo 7.\nStd. in M101 KUR 1\nInt_L_6ab Latein Mi 7. Std. in M103 LAN 1\nInt_F_6b Französisch Di 7. Std. in F111 BRE 1", **overrides}


def test_evidence_scopes_class_slot_year_and_resolves_codes():
    rows = course_evidence([evidence()], "6A", TEACHERS, TODAY)
    assert [(r["subject"], r["weekday"], r["lesson"], r["teacher"]) for r in rows] == [
        ("MInt", 1, "7", "Karla Kurzweil"), ("LInt", 3, "7", "Lena Lang")]
    assert rows[0]["source"]["item_uid"] == "school-child-letter"
    for item in (evidence(title="2025/2026"), evidence(sent="2025-09-15"),
                 evidence(sent="2026-12-01"), evidence(sent=None)):
        assert not course_evidence([item], "6A", TEACHERS, TODAY)
    assert not course_evidence([evidence()], "16A", TEACHERS, TODAY)
    assert not course_evidence([evidence()], "6A", {}, TODAY)
    assert not course_evidence([evidence("Die Lehrerin schreibt über Mathe", sender="Karla Kurzweil")], "6A", TEACHERS, TODAY)


def test_enrichment_keeps_raw_plan_and_handles_conflicts_and_participation():
    plan = [{"subject": "MInt", "weekday": 1, "lesson": "7", "room": "NEW"},
            {"subject": "LInt", "weekday": 3, "lesson": "7"},
            {"subject": "MInt", "weekday": 2, "lesson": "7"}]
    raw = deepcopy(plan)
    result = enrich_timetable(plan, [evidence()], "6A", TEACHERS, TODAY, ["Int_L_6ab"])
    assert result[0]["teacher"] == "Karla Kurzweil"
    assert result[0]["room"] == "NEW"  # never import an old document's room
    assert result[0]["participation"] == "not_registered"
    assert result[1]["participation"] == "registered"
    assert "teacher" not in result[2]
    assert plan == raw
    assert enrich_timetable(plan, [evidence()], "6A", TEACHERS, TODAY)[0]["participation"] == "unknown"
    conflicting = evidence(text="Int_M_6a Mathe Mo 7. Std. in M101 BRE 1")
    assert "teacher" not in enrich_timetable(plan, [evidence(), conflicting], "6A", TEACHERS, TODAY)[0]
    assert "teacher" not in enrich_timetable(plan, [evidence()], "6A", TEACHERS, date(2027, 9, 1))[0]
    plan[0]["teacher"] = "Explicit timetable teacher"
    assert enrich_timetable(plan, [evidence()], "6A", TEACHERS, TODAY)[0]["teacher"] == "Explicit timetable teacher"


def test_registrations_distinguish_unavailable_from_empty():
    head = '<header><h2>Example school</h2></header><h2>Voranmeldung Intensivierungskurse</h2>'
    assert parse_course_registrations('<h2>Login</h2>') is None
    assert parse_course_registrations(head + '<form>Bitte anmelden</form>') is None
    assert parse_course_registrations(head + '<p>Keine Anmeldungen vorhanden</p>') == []
    html = head + '<p>Für folgende Intensivierungskurse besteht eine Anmeldung:</p><h4 class="link_buchungen">Int_M_6a</h4>'
    assert parse_course_registrations(html) == ['Int_M_6a']
