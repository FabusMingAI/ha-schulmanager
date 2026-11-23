"""Klassenbuch: Hausaufgaben lesen, speichern, melden (#53). Nur erfundene Daten."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eltern_portal_schulmanager.const import DOMAIN, EVENT_NEW_HOMEWORK
from custom_components.eltern_portal_schulmanager.portal import (
    HOMEWORK_DAYS_AHEAD,
    HOMEWORK_DAYS_BACK,
    HOMEWORK_FIRST_DAYS_BACK,
    SchulPortal,
    parse_klassenbuch,
)

from .test_eltern_portal_schulmanager import (  # noqa: F401 - Fixtures
    _fake_result,
    auto_enable_custom_integrations,
    media_dir,
)

# Aufbau wie die Portalseite service/klassenbuch?cur_date=TT.MM.JJJJ (gekürzt, erfunden)
_PAGE = """<html><body><div id="asam_content"><h2>Klassenbuch</h2>
<div id='ktb_datepicker'><input type='text' name='cur_date' value='{date}' /></div>
<table class='table table-bordered'><thead><tr><th scope='col'></th>
<th scope='col'>Mathematik - Lehrkraft: Frau Huber (Doppelstunde)</th></tr></thead>
<tbody><tr><td>Hausaufgabe</td><td>Buch S. 12 Nr. 3a-c
AH S. 4 <br />- <i>Zu Erledigen bis: {due}</i></td></tr></tbody></table>
<table class='table table-bordered'><thead><tr><th scope='col'></th>
<th scope='col'>Englisch - Lehrkraft: Herr Klein (Einzelstunde, Vertretung)</th></tr></thead>
<tbody><tr><td>Hausaufgabe</td><td><i>Keine Hausaufgabe eingetragen.</i></td></tr>
<tr><td>Thema</td><td>Unit 2 &quot;at the zoo&quot;</td></tr></tbody></table>
<table class='table table-bordered'><thead><tr><th scope='col'></th>
<th scope='col'>Sport</th></tr></thead>
<tbody><tr><td>Hausaufgabe</td><td>Turnschuhe mitbringen</td></tr></tbody></table>
<table><thead><tr><th>ohne Zeilen</th></tr></thead><tbody></tbody></table>
</div></body></html>"""


def _page(day: date, due: date) -> str:
    return _PAGE.format(date=day.strftime("%d.%m.%Y"), due=due.strftime("%d.%m.%Y"))


def test_parse_klassenbuch() -> None:
    res = parse_klassenbuch(_page(date(2026, 3, 9), date(2026, 3, 11)))
    assert res["date"] == "2026-03-09"
    math, english, sport = res["entries"]
    assert math == {
        "subject": "Mathematik",
        "teacher": "Frau Huber",
        "info": ["Doppelstunde"],
        "substitute": False,
        "homework": "Buch S. 12 Nr. 3a-c\nAH S. 4",
        "due": "2026-03-11",
        "details": {},
    }
    # keine Hausaufgabe; weitere Zeilen als Details; Vertretung erkannt
    assert english["homework"] is None and english["due"] is None
    assert english["substitute"] is True and english["teacher"] == "Herr Klein"
    assert english["details"] == {"Thema": 'Unit 2 "at the zoo"'}
    # Kopfzeile ohne Lehrkraft, Hausaufgabe ohne Datum
    assert sport["subject"] == "Sport" and sport["teacher"] is None
    assert sport["homework"] == "Turnschuhe mitbringen" and sport["due"] is None


def test_parse_klassenbuch_without_entries() -> None:
    assert parse_klassenbuch("<html><body>Login</body></html>") == {"date": None, "entries": []}
    broken = "<input name='cur_date' value='31.02.2026'>"
    assert parse_klassenbuch(broken)["date"] is None


def test_homework_days_skip_sundays_and_known_days() -> None:
    api = SchulPortal.__new__(SchulPortal)
    api._student = SimpleNamespace(student_id=7)
    api.homework_known = {}
    wednesday = date(2026, 3, 11)
    ahead = [wednesday + timedelta(days=n) for n in range(HOMEWORK_DAYS_AHEAD, 0, -1)]
    ahead = [d for d in ahead if d.isoweekday() != 7]
    # erster Abruf (nichts gespeichert): die nächsten Tage und der letzte Monat, ohne Sonntage
    first = api.homework_days(wednesday)
    assert first[:len(ahead) + 1] == [*ahead, wednesday]
    assert first[-1] == wednesday - timedelta(days=HOMEWORK_FIRST_DAYS_BACK)
    sundays_back = sum(1 for n in range(HOMEWORK_FIRST_DAYS_BACK + 1)
                       if (wednesday - timedelta(days=n)).isoweekday() == 7)
    assert len(first) == len(ahead) + HOMEWORK_FIRST_DAYS_BACK + 1 - sundays_back
    assert all(d.isoweekday() != 7 for d in first)
    # danach: heute und gestern immer, ältere Tage der letzten Woche nur, wenn sie fehlen
    saturday = wednesday - timedelta(days=4)
    api.homework_known = {"7": {saturday.isoformat()}}
    days = api.homework_days(wednesday)
    assert days[-1] == wednesday - timedelta(days=HOMEWORK_DAYS_BACK)
    # 8 Tage zurück ohne Sonntag und den gespeicherten Samstag, dazu die Tage voraus
    assert saturday not in days and len(days) == len(ahead) + HOMEWORK_DAYS_BACK - 1
    # Tage voraus, heute und gestern werden immer gelesen, auch wenn gespeichert
    api.homework_known = {"7": {d.isoformat() for d in first}}
    assert api.homework_days(wednesday) == [*ahead, wednesday, wednesday - timedelta(days=1)]


async def test_homework_online_reads_each_day(hass: HomeAssistant, aioclient_mock) -> None:
    api = SchulPortal(async_get_clientsession(hass), "bspgym", "x", "p")
    api._student = SimpleNamespace(student_id=7)
    today = date.today()
    api.homework_known = {
        "7": {(today - timedelta(days=n)).isoformat() for n in range(2, HOMEWORK_DAYS_BACK + 1)}
    }
    candidates = [today - timedelta(days=n) for n in range(-HOMEWORK_DAYS_AHEAD, 2)]
    for day in candidates:
        aioclient_mock.get(
            f"{api.base_url}service/klassenbuch?cur_date={day:%d.%m.%Y}",
            text=_page(day, day + timedelta(days=2)),
        )
    await api.async_homework_online()
    read = {d for d in candidates if d.isoweekday() != 7}
    assert set(api._homework) == {d.isoformat() for d in read}
    assert aioclient_mock.call_count == len(read)
    await api.async_homework_demo()
    assert api._homework == {}
    # unerwartete Seite (z. B. Anmeldung): Fehler statt eines leeren Tags
    aioclient_mock.clear_requests()
    for day in candidates:
        aioclient_mock.get(f"{api.base_url}service/klassenbuch?cur_date={day:%d.%m.%Y}", text="<html>Login</html>")
    with pytest.raises(ValueError, match="unerwartete Seite"):
        await api.async_homework_online()


async def test_homework_flow(hass: HomeAssistant, media_dir) -> None:
    """Sensor, Kalender und Ereignis: neu nur, was nach dem ersten Abruf dazukommt."""
    today = dt_util.now().date()
    two_weeks_ago = today - timedelta(days=14)
    state: dict = {"homework": {
        today.isoformat(): parse_klassenbuch(_page(today, today + timedelta(days=2)))["entries"],
        # längst erledigt: weder im Sensor noch im Kalender
        two_weeks_ago.isoformat(): parse_klassenbuch(_page(two_weeks_ago, two_weeks_ago + timedelta(days=1)))["entries"],
    }}

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today)
        res.children[0].homework = state["homework"]
        return res

    events: list[dict] = []
    hass.bus.async_listen(EVENT_NEW_HOMEWORK, lambda e: events.append(dict(e.data)))
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.eltern_portal_schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        # erster Abruf: gespeichert, aber nichts als neu gemeldet
        assert events == []
        st = hass.states.get("sensor.schule_anna_hausaufgaben")
        assert st.state == "2", st  # Mathematik (mit Datum) + Sport (ohne)
        rows = {r["fach"]: r for r in st.attributes["hausaufgaben"]}
        assert rows["Mathematik"]["faellig"] == (today + timedelta(days=2)).isoformat()
        assert rows["Sport"]["faellig"] is None
        cal = [e for e in m.child_events("anna") if e["category"] == "hausaufgabe"]
        assert {e["title"] for e in cal} == {"Mathematik: Buch S. 12 Nr. 3a-c", "Sport: Turnschuhe mitbringen"}
        assert all(e["summary"].startswith("📚 ") for e in cal)

        # neue Hausaufgabe am nächsten Abruf -> genau ein Ereignis, Wiederholung -> keins
        tomorrow = today + timedelta(days=1)
        state["homework"] = {
            today.isoformat(): state["homework"][today.isoformat()]
            + [{"subject": "Biologie", "teacher": None, "info": [], "substitute": False,
                "homework": "Plakat fertig", "due": tomorrow.isoformat(), "details": {}},
               # ohne Fach (Kopfzeile nicht lesbar): nur der Text
               {"subject": None, "teacher": None, "info": [], "substitute": False,
                "homework": "Elternbrief unterschreiben", "due": tomorrow.isoformat(), "details": {}}],
        }
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert len(events) == 2
        bio = next(e for e in events if e["subject"] == "Biologie")
        assert bio["child"] == "anna" and bio["due"] == tomorrow.isoformat() and bio["text"] == "Plakat fertig"
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert len(events) == 2
        st = hass.states.get("sensor.schule_anna_hausaufgaben")
        assert st.state == "4"
        assert sorted(st.attributes["morgen"]) == ["Biologie: Plakat fertig", "Elternbrief unterschreiben"]
        assert "📚 Elternbrief unterschreiben" in {e["summary"] for e in m.child_events("anna")}

        # Klassenbuch nicht lesbar -> Sensor nicht verfügbar, gespeicherte Tage bleiben
        state["homework"] = None
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.schule_anna_hausaufgaben").state == "unavailable"
        assert m.data["homework"]["anna"]["days"]


def test_child_homework_dates(hass: HomeAssistant) -> None:
    """Fällig bis zum Datum; ohne Datum bis zum nächsten Schultag; alte Tage fallen weg."""
    from custom_components.eltern_portal_schulmanager.manager import SchulManager

    m = SchulManager.__new__(SchulManager)
    today = dt_util.now().date()
    friday = today - timedelta(days=(today.isoweekday() - 5) % 7 or 7)
    m.data = {"homework": {}, "homework_seen": {}}
    old = (today - timedelta(days=40)).isoformat()
    item = {"subject": "Kunst", "teacher": None, "homework": "Skizze", "due": None, "substitute": False}
    assert m._merge_homework("anna", {old: [item], friday.isoformat(): [item]}) == []
    assert list(m.data["homework"]["anna"]["days"]) == [friday.isoformat()]  # 40 Tage alt: weg
    # schon für die nächste Stunde eingetragen (Seite eines kommenden Tages): offen
    soon = today + timedelta(days=1)
    entered_ahead = dict(item, subject="Mathematik", homework="Heft", due=(soon + timedelta(days=2)).isoformat())
    m._merge_homework("anna", {soon.isoformat(): [entered_ahead]})
    assert any(h["subject"] == "Mathematik" and h["given"] == soon.isoformat() for h in m.child_homework("anna"))
    # Freitag ohne Datum: offen bis Montag
    art = [h for h in m.child_homework("anna", include_done=True) if h["subject"] == "Kunst"]
    monday = friday + timedelta(days=3)
    assert art[0]["overdue"] == (today > monday)
    assert any(h["subject"] == "Kunst" for h in m.child_homework("anna")) == (today <= monday)
