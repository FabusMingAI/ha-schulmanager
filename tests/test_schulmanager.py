"""Tests für den Schulmanager in einer echten Home-Assistant-Testinstanz."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import asyncio
import io
import json
import pathlib
from unittest.mock import patch

import pytest
from pypdf import PdfWriter
from pypdf.generic import NameObject

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.schulmanager.const import DOMAIN
from custom_components.schulmanager.portal import (
    PortalAttachment,
    PortalChild,
    PortalFile,
    PortalItem,
    PortalResult,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass, enable_custom_integrations):
    # Entity-IDs in den Tests sind deutsch (z. B. todo.schule_anna_aufgaben)
    hass.config.language = "de"
    yield


@pytest.fixture
def media_dir(hass: HomeAssistant, tmp_path):
    hass.config.media_dirs = {"local": str(tmp_path)}
    return tmp_path


def _pdf_bytes(text: str) -> bytes:
    """Kleines PDF mit Text erzeugen (reportlab-frei)."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    lines = "".join(
        f"BT /F1 11 Tf 50 {800 - 16 * n} Td ({line}) Tj ET\n"
        for n, line in enumerate(text.split("\n"))
    )
    stream.set_data(lines.encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _fake_result(today: date, with_pdf: bool = True) -> PortalResult:
    sent = datetime.combine(today - timedelta(days=1), datetime.min.time())
    letter = PortalItem(
        uid="bspgym-7-elternbrief-501",
        kind="elternbrief",
        title="Klassenfahrt Berchtesgaden 8b",
        body="Bitte beachten Sie den angehängten Brief.",
        sent=sent,
        url="https://bspgym.eltern-portal.org/aktuelles/elternbriefe",
        version="v1",
        attachments=[PortalAttachment("Klassenfahrt", "aktuelles/get_file/?repo=501&csrf=x")],
        meta={"nummer": "#12", "empfang_bestaetigt": False, "verteiler": "8b"},
    )
    if with_pdf:
        due = (today + timedelta(days=3)).strftime("%d.%m.%Y")
        letter.files = [
            PortalFile(
                "Klassenfahrt.pdf",
                _pdf_bytes(
                    "Liebe Eltern,\nbitte ueberweisen Sie 185,00 EUR\n"
                    f"bis spaetestens {due} auf das Schulkonto."
                ),
                "application/pdf",
            )
        ]
    message = PortalItem(
        uid="bspgym-7-nachricht-11_3",
        kind="nachricht",
        title="Mathe-Hausaufgaben",
        body="— Frau Huber:\nAnna hat dreimal die Hausaufgaben vergessen.",
        sent=sent,
        sender="Huber, StRin",
        url="https://bspgym.eltern-portal.org/meldungen/kommunikation_fachlehrer/11/3",
        version="m1",
    )
    old = PortalItem(
        uid="bspgym-7-elternbrief-100",
        kind="elternbrief",
        title="Alter Brief",
        body="Info vom letzten Schuljahr",
        sent=sent - timedelta(days=90),
        url="https://bspgym.eltern-portal.org/aktuelles/elternbriefe",
        version="o1",
        meta={"empfang_bestaetigt": True},
    )
    child = PortalChild(
        student_id="7",
        fullname="Anna Muster (8b)",
        firstname="Anna",
        classname="8b",
        items=[letter, message, old],
        appointments=[
            {
                "uid": "bspgym-7-termin-1",
                "title": "SA Mathematik",
                "start": dt_util.start_of_local_day(today + timedelta(days=5)),
                "end": dt_util.start_of_local_day(today + timedelta(days=5)) + timedelta(hours=2),
            }
        ],
    )
    return PortalResult(
        school="bspgym",
        school_name="Beispiel-Gymnasium",
        base_url="https://bspgym.eltern-portal.org/",
        children=[child],
    )


async def test_config_flow_demo(hass: HomeAssistant) -> None:
    """Einrichtung mit der Demo-Schule (kein Netz nötig) inkl. Link-Erkennung."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"school": "https://demo.eltern-portal.org?username=a%40b.de", "username": "A@b.de", "password": "x"},
    )
    assert result["type"] is FlowResultType.MENU
    with patch("custom_components.schulmanager.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "finish"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    portal = result["data"]["portals"][0]
    assert portal["school"] == "demo"
    assert portal["school_name"] == "Gymnasium Demo"
    assert portal["username"] == "a@b.de"


async def test_demo_setup_rules(hass: HomeAssistant, media_dir) -> None:
    """Komplette Einrichtung gegen das Demo-Portal, Auswertung ohne KI."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    m = entry.runtime_data
    for _ in range(20):
        if not m._pending():
            break
        await hass.async_block_till_done()
    assert "erika" in m.children
    assert hass.states.get("sensor.schule_erika_status") is not None
    assert hass.states.get("todo.schule_erika_aufgaben") is not None
    assert hass.states.get("calendar.schule_erika_kalender") is not None
    assert all(i["analysis"]["status"] == "fertig" for i in m.items.values())
    print({k: (v["kind"], v["analysis"]) for k, v in m.items.items()})
    await hass.config_entries.async_unload(entry.entry_id)


async def test_full_flow_ai_files_reminders(hass: HomeAssistant, media_dir) -> None:
    """Neue Mitteilung mit PDF -> Ablage -> KI -> Aufgaben -> Push -> Erinnerung -> Erledigt."""
    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()
    due = (today + timedelta(days=3)).isoformat()

    notified: list[dict] = []

    async def fake_notify(call: ServiceCall) -> None:
        notified.append(dict(call.data))

    hass.services.async_register("notify", "mobile_app_handy_1", fake_notify)

    prompts: list[str] = []

    async def fake_ai(call: ServiceCall):
        prompts.append(call.data["instructions"])
        if "Klassenfahrt" in call.data["instructions"]:
            data = {
                "zusammenfassung": "Klassenfahrt nach Berchtesgaden, 185 € bis zum Termin überweisen.",
                "kategorie": "zahlung",
                "dringlichkeit": "hoch",
                "aufgaben": [
                    {"titel": "Klassenfahrt bezahlen", "typ": "zahlung", "faellig": due,
                     "betrag": "185,00", "empfaenger": "Förderverein", "iban": "DE02 1203 0000 0000 2020 51",
                     "verwendungszweck": "KF 8b Anna", "details": None},
                ],
                "termine": [{"titel": "Abfahrt Klassenfahrt", "datum": (today + timedelta(days=20)).isoformat(),
                             "uhrzeit": "7:30", "ort": "Schulhof"}],
            }
            return {"data": "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"}
        return {"data": {"zusammenfassung": "Hausaufgaben fehlen.", "kategorie": "info",
                         "dringlichkeit": "mittel", "aufgaben": [], "termine": []}}

    hass.services.async_register(
        "ai_task", "generate_data", fake_ai, supports_response=SupportsResponse.ONLY
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "Beispiel", "username": "x@y.de", "password": "p"}]},
        options={"ai_task_entity": "ai_task.claude", "notify_services": ["mobile_app_handy_1"], "reminder_days": "3,1,0"},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    # Erster Abruf: Erst-Import (keine Einzel-Pushes); zweiter Abruf liefert den neuen Brief
    first = _fake_result(today)
    first.children[0].items = [first.children[0].items[2]]  # nur alter Brief
    calls = {"n": 0}

    async def fake_fetch(self, need_download=None, teachers=False):
        calls["n"] += 1
        res = first if calls["n"] == 1 else _fake_result(today)
        if need_download:
            for c in res.children:
                for it in c.items:
                    if not need_download(it):
                        it.files = []
        return res

    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        assert m.items["bspgym-7-elternbrief-100"]["analysis"]["status"] == "archiv"
        await m.async_refresh()
        await hass.async_block_till_done()
        for _ in range(20):
            if not m._pending():
                break
            await hass.async_block_till_done()

    letter = m.items["bspgym-7-elternbrief-501"]
    # Datei abgelegt + Text gelesen
    assert letter["files"], letter
    path = letter["files"][0]["path"]
    assert path.startswith("schulmanager/Anna/")
    assert (media_dir / path).exists()
    assert "185,00 EUR" in letter["text"]
    assert any("185,00 EUR" in p for p in prompts)
    # Aufgabe aus KI
    task = next(t for t in m.tasks.values() if t["type"] == "zahlung")
    assert task["amount"] == 185.0 and task["due"] == due and task["iban"] == "DE02120300000000202051"
    # Sensoren
    st = hass.states.get("sensor.schule_anna_status")
    assert st.state == "rot"  # dringende ungelesene Mitteilung
    assert float(hass.states.get("sensor.schule_anna_offene_zahlungen").state) == 185.0
    assert hass.states.get("sensor.schule_anna_nachste_frist").state == due
    assert hass.states.get("todo.schule_anna_aufgaben").state == "1"
    url = st.attributes["mitteilungen"][0]["dateien"][0]["url"]
    assert "authSig=" in url
    # Kalender: Frist, Termin aus Brief (mit Uhrzeit), Schulaufgabe aus Portal
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.schule_anna_kalender", "duration": {"days": 30}},
        blocking=True, return_response=True,
    )
    summaries = [e["summary"] for e in resp["calendar.schule_anna_kalender"]["events"]]
    assert any("Frist: Klassenfahrt bezahlen" in s for s in summaries), summaries
    assert any("Abfahrt Klassenfahrt" in s for s in summaries)
    assert any("SA Mathematik" in s for s in summaries)
    # Push für neue Mitteilungen (nicht für den Erst-Import des alten Briefs)
    titles = [n["title"] for n in notified]
    assert any("Anna · Elternbrief" in t for t in titles), titles
    assert not any("Alter Brief" in n["message"] for n in notified)
    push = next(n for n in notified if "Elternbrief" in n["title"])
    assert "185,00 €" in push["message"]
    # Erinnerung 3 Tage vorher, nur einmal
    notified.clear()
    assert await m.async_send_reminders() == 1
    assert await m.async_send_reminders() == 0
    assert "Fällig in 3 Tagen" in notified[0]["message"]
    action = notified[0]["data"]["actions"][0]["action"]
    # "Erledigt" aus der Handy-Benachrichtigung
    hass.bus.async_fire("mobile_app_notification_action", {"action": action})
    await hass.async_block_till_done()
    assert m.tasks[task["id"]]["status"] == "erledigt"
    assert float(hass.states.get("sensor.schule_anna_offene_zahlungen").state) == 0
    # Gelesen markieren -> Ampel
    await hass.services.async_call(DOMAIN, "mark_read", {"child": "anna"}, blocking=True)
    assert hass.states.get("sensor.schule_anna_status").state in ("gruen", "gelb")
    # Datei über die gesicherte Ansicht abrufbar, ohne Signatur nicht
    from custom_components.schulmanager import SchulFileView

    # Übersicht für Sprachassistent / Skripte
    ov = await hass.services.async_call(DOMAIN, "get_overview", {}, blocking=True, return_response=True)
    assert "Anna" in ov["digest"]
    # Todo: eigene Aufgabe über die To-do-Liste anlegen und abhaken
    await hass.services.async_call(
        "todo", "add_item",
        {"entity_id": "todo.schule_anna_aufgaben", "item": "Turnbeutel kaufen", "due_date": due},
        blocking=True,
    )
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": "todo.schule_anna_aufgaben"},
        blocking=True, return_response=True,
    )
    names = [i["summary"] for i in items["todo.schule_anna_aufgaben"]["items"]]
    assert any("Turnbeutel kaufen" in n for n in names), names
    await hass.services.async_call(
        "todo", "update_item",
        {"entity_id": "todo.schule_anna_aufgaben", "item": next(n for n in names if "Turnbeutel" in n), "status": "completed"},
        blocking=True,
    )
    assert any(t["title"] == "Turnbeutel kaufen" and t["status"] == "erledigt" for t in m.tasks.values())
    # Digest
    notified.clear()
    await hass.services.async_call(DOMAIN, "send_digest", {}, blocking=True)
    assert notified and "Anna" in notified[0]["message"]
    print(notified[0]["message"])
    # Neustart: Daten bleiben erhalten
    await hass.config_entries.async_unload(entry.entry_id)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.runtime_data.tasks[task["id"]]["status"] == "erledigt"
    await hass.config_entries.async_unload(entry.entry_id)
    _ = (SchulFileView, PdfWriter, NameObject)


async def test_rules_without_ai(hass: HomeAssistant) -> None:
    from custom_components.schulmanager.analyzer import analyze_rules

    r = analyze_rules(
        {
            "title": "Wandertag",
            "body": "Bitte geben Sie die Einverständniserklärung bis Freitag, 10.10. zurück. "
            "Kosten: 12,50 € in bar.",
            "sent_date": date(2026, 10, 1),
        }
    )
    assert r["tasks"][0]["amount"] == 12.5
    assert r["tasks"][0]["due"] == "2026-10-10"


async def test_file_view_signed(hass: HomeAssistant, media_dir, hass_client_no_auth) -> None:
    """Abgelegte PDFs sind nur über signierte Links erreichbar."""
    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    st = hass.states.get("sensor.schule_anna_status")
    letter = next(i for i in st.attributes["mitteilungen"] if i["dateien"])
    url = letter["dateien"][0]["url"]
    client = await hass_client_no_auth()
    resp = await client.get(url)
    assert resp.status == 200
    assert (await resp.read()).startswith(b"%PDF")
    resp = await client.get(url.split("?")[0])
    assert resp.status == 401
    # Regel-Erkennung (ohne KI) hat Betrag + Frist aus dem PDF gelesen
    m = entry.runtime_data
    pay = [t for t in m.tasks.values() if t["type"] == "zahlung"]
    assert pay and pay[0]["amount"] == 185.0, m.tasks
    await hass.config_entries.async_unload(entry.entry_id)


async def test_portal_parsing_links() -> None:
    """Download-Links von Briefen und Nachrichten-Anhänge werden erkannt."""
    import aiohttp
    from custom_components.schulmanager.portal import SchulPortal
    from pyelternportal.student import Student

    async with aiohttp.ClientSession() as s:
        p = SchulPortal(s, "demo", "", "")
        p._student = Student("1", "Max Muster (6c)")
        html = (
            "<table><tr><td>#7</td><td id='empf_77'>Empfang noch nicht bestätigt.</td></tr>"
            "<tr><td colspan='2'><a href='aktuelles/get_file/?repo=77&csrf=abc' onclick='eb_bestaetigung(77);' "
            "class='link_nachrichten' target='_blank'><h4>Wandertag</h4> 30.09.2026 12:01</a>"
            "<br /><span style='font-size: 8pt;'>Klasse/n: 6c</span><br />Bitte Rückmeldung.</td></tr></table>"
        )
        await p.async_letter_parse(html)
        assert p._letter_links == {"77": "aktuelles/get_file/?repo=77&csrf=abc"}
        assert p._student.letters[0].new is True
        detail = (
            '<div class="ui grid" id="message-thread-grid">'
            '<div class="row"><div><strong>Betreff:</strong></div><div><strong>Schulaufgabe</strong></div></div>'
            '<div class="row"><div><strong>Frau Huber:</strong><br/>(30.09.2026)</div>'
            '<div><div class="ui segment">Anbei die Ergebnisse.<br/>'
            '<a href="meldungen/get_file/?f=55&amp;csrf=x">Ergebnis.pdf</a></div></div></div></div>'
        )
        subj, body, atts = p._parse_message_detail(detail)
        assert subj == "Schulaufgabe"
        assert "Anbei die Ergebnisse" in body and "Frau Huber" in body
        assert atts[0].name == "Ergebnis.pdf" and "f=55" in atts[0].href


async def test_options_flow(hass: HomeAssistant, media_dir) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"benachrichtigungen": {"notify_services": ["mobile_app_handy_2"], "reminder_days": "2,0", "digest_time": "07:00:00"}},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # gespeichert wird weiterhin flach, nicht nach Abschnitten
    assert "benachrichtigungen" not in entry.options and entry.options["digest_time"] == "07:00:00"
    await hass.async_block_till_done()
    assert entry.options["notify_services"] == ["mobile_app_handy_2"]
    assert entry.runtime_data.opt("reminder_days") == "2,0"
    # Schule hinzufügen (zweites Demo-Portal ist dieselbe Kennung -> Fehler)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_portal"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"school": "demo", "username": "a@b.de", "password": "x"}
    )
    assert result["errors"] == {"school": "already_added"}
    await hass.config_entries.async_unload(entry.entry_id)


async def test_dashboard_templates_render(hass: HomeAssistant, media_dir) -> None:
    """Die Markdown-Vorlagen des Dashboards rendern mit echten Zuständen."""
    import pathlib
    import yaml
    from homeassistant.helpers.template import Template

    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    dash = yaml.safe_load(pathlib.Path("dashboard/schulmanager_dashboard.yaml").read_text())
    cards = dash["views"][0]["sections"][0]["cards"]
    for card in cards:
        if card["type"] == "markdown":
            out = Template(card["content"], hass).async_render(parse_result=False)
            print(out)
            assert "Klassenfahrt" in out
    await hass.config_entries.async_unload(entry.entry_id)


async def test_websocket_and_task_status(hass: HomeAssistant, media_dir, hass_ws_client, hass_client) -> None:
    """Karte: Daten, Details mit PDF, Status in Arbeit, Kommentar."""
    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "schulmanager/subscribe"})
    assert (await ws.receive_json())["success"]
    await ws.send_json({"id": 2, "type": "schulmanager/data"})
    res = (await ws.receive_json())["result"]
    child = res["children"][0]
    assert child["name"] == "Anna" and child["tasks"]
    # Kopfzeile: Version und letzter Abruf; kein Tagesüberblick mehr (seit 0.10.1)
    manifest = json.loads(pathlib.Path("custom_components/schulmanager/manifest.json").read_text())
    assert res["version"] == manifest["version"] and res["repo_url"].startswith("https://github.com/")
    assert res["last_update"]
    assert "day" not in child
    task = next(t for t in child["tasks"] if t["amount"])
    await ws.send_json({"id": 3, "type": "schulmanager/task", "task_id": task["id"]})
    detail = (await ws.receive_json())["result"]
    assert detail["item"]["files"][0]["url"].startswith("/api/schulmanager/datei/")
    assert "185,00 EUR" in detail["item"]["text"]
    # Status „in Arbeit“ + Kommentar
    await hass.services.async_call(
        DOMAIN, "update_task",
        {"task_id": task["id"], "status": "in_arbeit", "comment": "Überweisung vorbereitet"},
        blocking=True,
    )
    ev = await ws.receive_json()
    assert ev["type"] == "event" and ev["event"]["changed"]
    m = entry.runtime_data
    assert m.tasks[task["id"]]["status"] == "in_arbeit"
    assert m.tasks[task["id"]]["comment"] == "Überweisung vorbereitet"
    # bleibt offen (zählt mit, wird weiter erinnert) und erscheint in der To-do-Liste mit ⏳
    assert hass.states.get("sensor.schule_anna_offene_aufgaben").state == "1"
    items = await hass.services.async_call(
        "todo", "get_items", {"entity_id": "todo.schule_anna_aufgaben"}, blocking=True, return_response=True
    )
    it = items["todo.schule_anna_aufgaben"]["items"][0]
    assert it["summary"].startswith("⏳") and "Überweisung vorbereitet" in it["description"]
    # Abhaken in der To-do-Liste -> erledigt; wieder öffnen -> offen
    await hass.services.async_call(
        "todo", "update_item", {"entity_id": "todo.schule_anna_aufgaben", "item": it["uid"], "status": "completed"}, blocking=True
    )
    assert m.tasks[task["id"]]["status"] == "erledigt"
    await hass.services.async_call(DOMAIN, "update_task", {"task_id": task["id"], "status": "offen"}, blocking=True)
    assert m.tasks[task["id"]]["status"] == "offen"
    # Karte wird ausgeliefert
    client = await hass_client()
    resp = await client.get("/schulmanager_static/schulmanager-card.js")
    assert resp.status == 200 and "schulmanager-card" in await resp.text()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_card_registered_as_lovelace_resource(hass: HomeAssistant) -> None:
    """Die Karte liegt unter /local und steht in den Dashboard-Ressourcen."""
    import os

    from homeassistant.setup import async_setup_component

    os.makedirs(hass.config.path("www"), exist_ok=True)
    assert await async_setup_component(hass, "lovelace", {})
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    res = hass.data["lovelace"].resources
    urls = [i["url"] for i in res.async_items()]
    assert len(urls) == 1 and urls[0].startswith("/local/schulmanager/schulmanager-card.js?v="), urls
    assert os.path.isfile(hass.config.path("www", "schulmanager", "schulmanager-card.js"))
    # zweiter Start: kein Duplikat
    from custom_components.schulmanager import _async_register_resource, _card_path

    await _async_register_resource(hass, _card_path())
    assert len(res.async_items()) == 1


async def test_dashboard_tabs_single_and_protection(hass: HomeAssistant, media_dir) -> None:
    """Dashboard „Schule“: Reiter je Kind, Umschalten, Schutz eigener Änderungen."""
    import os

    from homeassistant.setup import async_setup_component

    from custom_components.schulmanager import dashboard as dash_mod

    os.makedirs(hass.config.path("www"), exist_ok=True)
    assert await async_setup_component(hass, "lovelace", {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await asyncio.sleep(2.2)  # Dashboard wird kurz nach dem Start erzeugt
    for _ in range(5):
        await hass.async_block_till_done()
    m = entry.runtime_data
    dashes = hass.data["lovelace"].dashboards
    assert "dashboard-schule" in dashes
    cfg = await dashes["dashboard-schule"].async_load(False)
    titles = [v["title"] for v in cfg["views"]]
    assert titles[0] == "Übersicht" and len(titles) == 1 + len(m.children), titles
    overview = json.dumps(cfg["views"][0])
    assert "custom:schulmanager-termine" in overview
    # rechte Spalte: Stundenplan je Kind statt der Schulmanager-Karte (seit 0.7.1)
    right = cfg["views"][0]["sections"][1]["cards"]
    plans = [c["child"] for c in right if c["type"] == "custom:schulmanager-stundenplan"]
    assert plans == list(m.children), right
    assert all(c.get("view") == "week" for c in right if c["type"] == "custom:schulmanager-stundenplan")
    assert all(c["type"] != "entities" for c in right)
    assert "sensor.schule_erika_status" not in overview
    assert cfg["views"][1]["sections"][0]["cards"][0] == {
        "type": "custom:schulmanager-card", "child": "erika", "grid_options": {"columns": 12}
    }
    child_view = json.dumps(cfg["views"][1])
    assert "custom:schulmanager-stundenplan" in child_view and '"child": "erika"' in child_view
    assert '"view": "week"' in child_view
    assert os.path.isfile(hass.config.path("www", "schulmanager", "icon.png"))

    # eigene Änderung bleibt erhalten
    cfg["views"].append({"title": "Eigene Ansicht", "cards": []})
    await dashes["dashboard-schule"].async_save(cfg)
    assert not await dash_mod.async_apply(hass, m)
    assert len((await dashes["dashboard-schule"].async_load(False))["views"]) == len(titles) + 1

    # bewusste Wahl „Eine Seite“ in den Einstellungen überschreibt
    hass.config_entries.async_update_entry(entry, options={**entry.options, "dashboard": "single"})
    await asyncio.sleep(2.2)  # Dashboard wird kurz nach dem Start erzeugt
    for _ in range(5):
        await hass.async_block_till_done()
    m = entry.runtime_data
    cfg = await dashes["dashboard-schule"].async_load(False)
    assert len(cfg["views"]) == 1 and "schulmanager-card" in json.dumps(cfg)

    # „Nicht verwalten“ fasst nichts an
    hass.config_entries.async_update_entry(entry, options={**entry.options, "dashboard": "off"})
    await asyncio.sleep(2.2)  # Dashboard wird kurz nach dem Start erzeugt
    for _ in range(5):
        await hass.async_block_till_done()
    assert not await dash_mod.async_apply(hass, entry.runtime_data, force=True)
    await hass.config_entries.async_unload(entry.entry_id)


_SUBST_HTML = """
<div id="asam_content"><div class="main_center">
<div class="list bold full_width text_center">Mo., {d0} - KW 41</div>
<table class="table"><tbody>
<tr class="vp_plan_head"><td>Std.</td><td>Betrifft</td><td>Vertretung</td><td>Fach</td><td>Raum</td><td>Info</td></tr>
<tr><td>3.</td><td>Huber</td><td>Maier</td><td><span style="text-decoration: line-through;">&nbsp;M&nbsp;</span> D</td><td>104</td><td></td></tr>
<tr><td>5.-6.</td><td>Huber</td><td>---</td><td>E</td><td></td><td>entfällt</td></tr>
<tr><td>2.</td><td>Kurz</td><td></td><td>B</td><td>N12</td><td>Raumänderung</td></tr>
</tbody></table>
<div class="list bold full_width text_center">Di., {d1} - KW 41</div>
<table class="table"><tbody>
<tr class="vp_plan_head"><td>Std.</td><td>Betrifft</td><td>Vertretung</td><td>Fach</td><td>Raum</td><td>Info</td></tr>
<tr><td colspan="6">Keine Vertretungen</td></tr>
</tbody></table>
<div>Stand: 05.10.2026 07:15</div>
</div></div>
"""


async def test_portal_parsing_timetable_substitutions() -> None:
    """Stundenplan mit Uhrzeiten, Vertretungsplan mit Entfall, Raumänderung, altem Fach."""
    from pyelternportal.demo import DEMO_HTML_LESSON

    from custom_components.schulmanager.portal import parse_substitutions, parse_timetable

    plan = parse_timetable(DEMO_HTML_LESSON)
    first = plan[0]
    assert first == {
        "weekday": 1, "lesson": "1", "start": "08:10", "end": "08:55", "subject": "Ku", "room": "OG2_24"
    }
    assert {x["weekday"] for x in plan} == {1, 2, 3, 4, 5}
    res = parse_substitutions(_SUBST_HTML.format(d0="05.10.2026", d1="06.10.2026"))
    assert res["available"] and len(res["days"]) == 2
    e1, e2, e3 = res["days"][0]["entries"]
    assert e1["subject"] == "D" and e1["old_subject"] == "M" and e1["kind"] == "vertretung"
    assert e2["lesson"] == "5-6"
    assert e2["kind"] == "entfall"
    assert e3["kind"] == "raum"
    assert res["days"][1] == {"date": "2026-10-06", "entries": []}
    assert parse_substitutions("<html><body>Login</body></html>")["available"] is False


async def test_timetable_substitutions_flow(
    hass: HomeAssistant, media_dir, hass_ws_client
) -> None:
    """Stundenplan + Vertretungen: Sensoren, Kalender, Push nur bei Neuem, Karte-Daten."""
    from custom_components.schulmanager.portal import parse_substitutions, parse_timetable
    from pyelternportal.demo import DEMO_HTML_LESSON

    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)
    html = _SUBST_HTML.format(d0=today.strftime("%d.%m.%Y"), d1=tomorrow.strftime("%d.%m.%Y"))
    state = {"subst": parse_substitutions(html)}

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today)
        res.children[0].timetable = state.get("timetable", parse_timetable(DEMO_HTML_LESSON))
        res.children[0].substitutions = state["subst"]
        return res

    notified: list[dict] = []

    async def fake_notify(call: ServiceCall) -> None:
        notified.append(dict(call.data))

    hass.services.async_register("notify", "handy", fake_notify)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        options={"notify_services": ["notify.handy"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        # erster Abruf: keine Vertretungs-Push (nur Einrichtung)
        assert not any("Vertretungsplan" in n.get("title", "") for n in notified)
        st = hass.states.get("sensor.schule_anna_vertretungen")
        assert st.state == "3", st
        assert any("entfällt" in t for t in st.attributes["heute"])
        assert st.attributes["morgen"] == []
        tt = hass.states.get("sensor.schule_anna_stundenplan")
        assert tt is not None and tt.attributes["woche"]["Montag"][0].startswith("1. 08:10 Ku")

        # neue Vertretung für morgen -> genau eine Push
        state["subst"]["days"][1]["entries"].append(
            {"lesson": "1", "teacher": "Kurz", "substitute": "Lang", "subject": "Ph",
             "old_subject": None, "room": "P1", "info": "", "kind": "vertretung"}
        )
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        pushes = [n for n in notified if "Vertretungsplan" in n.get("title", "")]
        assert len(pushes) == 1 and "Morgen: 1. Std. Ph: Vertretung Lang, Raum P1" in pushes[0]["message"]
        # unverändert -> keine weitere Push
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert len([n for n in notified if "Vertretungsplan" in n.get("title", "")]) == 1
        # geteilte Klasse: zweite Zeile, nur andere Lehrkraft -> ein Eintrag, keine Push
        state["subst"]["days"][1]["entries"].append(
            {"lesson": "1", "teacher": "Breit", "substitute": "Lang", "subject": "Ph",
             "old_subject": None, "room": "P1", "info": "", "kind": "vertretung"}
        )
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert len([n for n in notified if "Vertretungsplan" in n.get("title", "")]) == 1
        st = hass.states.get("sensor.schule_anna_vertretungen")
        assert st.state == "4" and len(st.attributes["morgen"]) == 1
        day1 = m.data["substitutions"]["anna"]["days"][1]["entries"]
        assert len(day1) == 1 and day1[0]["teacher"] == "Kurz, Breit"
        evs = [x for x in m.child_events("anna") if x["uid"].startswith("vertretung-")]
        assert len({x["uid"] for x in evs}) == len(evs)
        assert any("Lehrkräfte laut Plan: Kurz, Breit" in x["hover"] for x in evs)
        # Portal liefert kurzzeitig nichts (z. B. Seite weg) -> alte Daten bleiben
        good = state["subst"]
        state["subst"] = {"available": False, "stand": None, "days": []}
        state["timetable"] = []
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.schule_anna_vertretungen").state == "4"
        assert m.data["timetable"]["anna"]["lessons"]
        state["subst"] = good
        state.pop("timetable")

    # Kalender: Vertretung mit Uhrzeit aus dem Stundenplan, Entfall als Eintrag
    events = m.child_events("anna")
    subs = [e for e in events if e["uid"].startswith("vertretung-")]
    assert any(e["category"] == "entfall" and "entfällt" in e["summary"] for e in subs)
    ph = next(e for e in subs if "Ph" in e["title"])
    if tomorrow.isoweekday() <= 5:
        assert ph["start"].strftime("%H:%M") == "08:10"
    # Tagesübersicht nennt heutige Änderungen
    assert "entfällt" in m.digest_text()

    # Kartendaten: Termine mit Kategorie + Kurzbeschreibung, Legende, Stundenplan
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "schulmanager/data"})
    res = (await ws.receive_json())["result"]
    child = res["children"][0]
    cats = {e["category"] for e in child["events"]}
    assert {"schulaufgabe", "entfall", "raum"} <= cats and any(c.startswith("frist_") for c in cats)
    frist = next(e for e in child["events"] if e["task_id"])
    assert frist["hover"] and frist["item_uid"]
    assert res["legend"]["entfall"][0] == "❌" and res["legend"]["frist_zahlung"][0] == "💶"
    assert child["timetable"][0]["start"] == "08:10"
    assert child["substitutions"]["days"][0]["entries"][0]["text"].startswith("3. Std. D")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_sicknotes(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """Krankmeldungen: Demo-Portal, Sensor, Kalender (Kategorie krank), leerer Abruf behält Daten."""
    # Demo-Schule liefert eine Krankmeldung für heute
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.data["sicknotes"]["erika"], m.data["sicknotes"]
    assert hass.states.get("sensor.schule_erika_krankmeldungen") is not None
    await hass.config_entries.async_unload(entry.entry_id)


async def test_sicknotes_fake_portal(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()
    # Montag bis Mittwoch einer Woche im laufenden Schuljahr
    monday = today - timedelta(days=today.weekday())
    state = {
        "notes": [
            {"start": monday.isoformat(), "end": (monday + timedelta(days=2)).isoformat(), "comment": "Fieber"},
            {"start": "2020-01-13", "end": "2020-01-14", "comment": None},
        ]
    }

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today)
        res.children[0].sicknotes = state["notes"]
        return res

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        st = hass.states.get("sensor.schule_anna_krankmeldungen")
        # nur das laufende Schuljahr zählt: 3 Schultage
        assert st.state == "3", st
        assert st.attributes["letzte"]["kommentar"] == "Fieber"
        assert len(st.attributes["krankmeldungen"]) == 2
        ev = [e for e in m.child_events("anna") if e["category"] == "krank"]
        assert len(ev) == 2 and ev[0]["icon"] == "🤒" and "Fieber" in ev[0]["hover"] + ev[1]["hover"]
        # leerer Abruf (Seite gerade weg) löscht nichts
        state["notes"] = []
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.schule_anna_krankmeldungen").state == "3"
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "schulmanager/data"})
    res = (await ws.receive_json())["result"]
    assert res["legend"]["krank"][0] == "🤒"
    child = res["children"][0]
    assert child["sicknotes"][0]["comment"] == "Fieber"
    # in der Terminliste stehen nur aktuelle Krankmeldungen (ab gestern)
    assert all(e["date"] >= (today - timedelta(days=1)).isoformat() or e.get("until") for e in child["events"] if e["category"] == "krank")
    m.data["sicknotes"]["anna"].append({"start": today.isoformat(), "end": today.isoformat(), "comment": "Arzttermin"})
    await ws.send_json({"id": 2, "type": "schulmanager/data"})
    res = (await ws.receive_json())["result"]
    assert any(e["category"] == "krank" and "Arzttermin" in e["hover"] for e in res["children"][0]["events"])
    await hass.config_entries.async_unload(entry.entry_id)


async def test_optional_section_disconnect_keeps_fetch(hass: HomeAssistant, media_dir) -> None:
    """Trennt das Portal bei einem Zusatzbereich die Verbindung, laufen die übrigen Bereiche weiter."""
    import aiohttp

    async def boom(self):
        raise aiohttp.ServerDisconnectedError()

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "", "password": ""}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_sicknote_demo", boom):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    m = entry.runtime_data
    assert "erika" in m.children and m.items, "Abruf darf nicht abbrechen"
    assert m.data["timetable"]["erika"]["lessons"]
    assert any("sicknote" in e for e in m.last_errors), m.last_errors
    await hass.config_entries.async_unload(entry.entry_id)


async def test_appointment_kinds_and_setting(hass: HomeAssistant, media_dir) -> None:
    """Portal-Termine: Standard nur Schulaufgaben und Tests, Termine der Schule per Einstellung."""
    from custom_components.schulmanager.portal import appointment_kind, appointment_subject

    assert appointment_kind("event-important", "x") == "schulaufgabe"
    assert appointment_kind("event-warning", "x") == "test"
    assert appointment_kind("event-info", "Sommerferien") == "schule"
    assert appointment_kind(None, "kLN in Chemie (Sch)") == "test"
    assert appointment_subject("kLN in Französisch (8_F_8B_Ab) (Ab)") == "Französisch"
    assert appointment_subject("SA in Deutsch (Mü)") == "Deutsch"

    today = dt_util.now().date()
    tomorrow = dt_util.start_of_local_day(today + timedelta(days=1))

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today)
        res.children[0].appointments = [
            {"uid": "a1", "title": "SA in Deutsch (Mü)", "kind": "schulaufgabe", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
            {"uid": "a2", "title": "kLN in Chemie (Sch)", "kind": "test", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
            {"uid": "a3", "title": "Sommerferien", "kind": "schule", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
        ]
        return res

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        ev = {e["uid"]: e for e in m.child_events("anna")}
        assert ev["a1"]["category"] == "schulaufgabe" and ev["a1"]["icon"] == "📝" and ev["a1"]["subject"] == "Deutsch"
        assert ev["a2"]["category"] == "test" and ev["a2"]["icon"] == "✏️"
        assert "a3" not in ev  # Termine der Schule standardmäßig aus
        assert "📝 Morgen: SA in Deutsch (Mü)" in m.digest_text()

        # Einstellung: auch Termine der Schule, aber keine Tests
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"termine": {"appointment_kinds": ["schulaufgabe", "schule"]}}
        )
        await hass.async_block_till_done()
        m = entry.runtime_data
        ev = {e["uid"]: e for e in m.child_events("anna")}
        assert "a3" in ev and ev["a3"]["category"] == "portal" and "a2" not in ev
    await hass.config_entries.async_unload(entry.entry_id)


def test_concerns_class() -> None:
    """Termine anderer Klassen/Jahrgangsstufen erkennen (Beispiele aus echten Portalen, anonymisiert)."""
    from custom_components.schulmanager.classes import concerns_class

    nine_d = {
        "Grundwissenstest Chemie Jgst. 10": False,
        "1. Wandertag": None,
        "kLN in Französisch (9_F_9D_Ab) (Ab)": True,
        "kLN in Evang. Religionslehre (9_Ev_9ABCDEF_Xy) (Xy)": True,
        "SA in Englisch (9_E_9ABC_Xy)": False,
        "Schullandheim 5b+5c": False,
        "Projekt Bauernhof 8A": False,
        "Wissenschaftswoche 11. Klassen": False,
        "18:00 - 20:00<br />Elternsprechabend 5. Klassen": False,
        "17:00 - 20:00<br />Elternsprechabend 6-13": True,
        "Berufsinformationsmesse für die Jgst. 11 und 12": False,
        "Theater 09:00 - 13:15<br>9Uhr: Jahrgangsstufe 6 – 10:30: Jahrgangsstufe 9": True,
        "Wandertag Klasse 9d – Schloss": True,
        "SA in Deutsch (Mü)": None,
        "3D-Druck AG": None,
    }
    for text, expected in nine_d.items():
        assert concerns_class(text, "9D") is expected, text
    six_a = {
        "Klassenelternabend der Klassen 6 bis 11": True,
        "Modell Europaparlament Jgst. 10": False,
        "Tage der Orientierung 8a+8b": False,
        "Bundesjugendspiele Geräteturnen (6. Klassen)": True,
        "Berufsinformationsabend 11-13": False,
        "Klassenfotos für den Jahresbericht": None,
    }
    for text, expected in six_a.items():
        assert concerns_class(text, "6A") is expected, text
    assert concerns_class("Schullandheim 5b", None) is None
    assert concerns_class("Q11 Kursfahrt Jgst. 11", "11") is True


def test_normalize_summaries() -> None:
    """KI-Zusammenfassung in mehreren Sprachen; erste gewählte Sprache ist die Haupt-Zusammenfassung."""
    from custom_components.schulmanager.analyzer import normalize, summary_languages

    assert summary_languages(None) == ["de", "en"]
    assert summary_languages(["ca", "de"]) == ["de", "ca"]
    raw = {
        "zusammenfassung": "Wandertag am Freitag.",
        "zusammenfassungen": {"de": "Wandertag am Freitag.", "en": "Hiking day on Friday.", "es": "Excursión el viernes.", "fr": "x"},
    }
    out = normalize(raw, ["de", "en", "es"])
    assert out["summary"] == "Wandertag am Freitag."
    assert out["summaries"] == {"de": "Wandertag am Freitag.", "en": "Hiking day on Friday.", "es": "Excursión el viernes."}
    # ohne Übersetzungen: Haupt-Zusammenfassung landet unter der ersten Sprache
    out = normalize({"zusammenfassung": "Nur Deutsch."}, ["de", "en"])
    assert out["summaries"] == {"de": "Nur Deutsch."}
    out = normalize({"zusammenfassungen": {"en": "Only English."}}, ["en", "ca"])
    assert out["summary"] == "Only English."


async def test_item_status_languages_class_filter(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """Status für Mitteilungen, Sprachen der KI-Zusammenfassung, Termine anderer Klassen, Einstellungs-Link."""
    from custom_components.schulmanager import dashboard as dash_mod

    today = dt_util.now().date()
    tomorrow = dt_util.start_of_local_day(today + timedelta(days=1))
    prompts: list[str] = []

    async def fake_ai(call: ServiceCall):
        prompts.append(call.data["instructions"])
        return {"data": {
            "zusammenfassung": "Hausaufgaben fehlen.",
            "zusammenfassungen": {"de": "Hausaufgaben fehlen.", "en": "Homework missing.", "ca": "Falten deures."},
            "kategorie": "info", "dringlichkeit": "mittel", "aufgaben": [],
            "termine": [
                {"titel": "Elternabend 8b", "datum": (today + timedelta(days=4)).isoformat()},
                {"titel": "Schullandheim 5a+5b", "datum": (today + timedelta(days=5)).isoformat()},
            ],
        }}

    hass.services.async_register("ai_task", "generate_data", fake_ai, supports_response=SupportsResponse.ONLY)

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today, with_pdf=False)
        res.children[0].appointments = [
            {"uid": "a1", "title": "SA in Deutsch (Mü)", "kind": "schulaufgabe", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
            {"uid": "a2", "title": "kLN in Chemie (8_C_8ABC_Sch) (Sch)", "kind": "test", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
            {"uid": "a3", "title": "Grundwissenstest Chemie Jgst. 10", "kind": "test", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
            {"uid": "a4", "title": "SA in Englisch", "detail": "SA in Englisch (7_E_7C_Hu)", "kind": "schulaufgabe", "start": tomorrow, "end": tomorrow + timedelta(hours=2)},
        ]
        return res

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        options={"ai_task_entity": "ai_task.claude", "summary_languages": ["de", "en", "ca"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        uid = "bspgym-7-nachricht-11_3"
        for _ in range(20):
            if m.items[uid]["analysis"].get("status") == "fertig":
                break
            await asyncio.sleep(0.05)

        # Sprachen im Prompt und in der Auswertung
        assert prompts and '"ca": "Zusammenfassung auf Katalanisch"' in prompts[0]
        assert "nicht Klasse 8b" in prompts[0]
        assert m.items[uid]["analysis"]["summaries"] == {
            "de": "Hausaufgaben fehlen.", "en": "Homework missing.", "ca": "Falten deures."
        }

        # Termine anderer Klassen ausgeblendet (Portal und KI)
        ev = {e["uid"]: e for e in m.child_events("anna")}
        assert "a1" in ev and "a2" in ev
        assert "a3" not in ev and "a4" not in ev
        titles = {e["title"] for e in m.child_events("anna")}
        assert "Elternabend 8b" in titles and "Schullandheim 5a+5b" not in titles

        # Status einer Mitteilung
        assert m.items[uid].get("status") in (None, "offen")
        await hass.services.async_call(DOMAIN, "update_item", {"item_id": uid, "status": "in_arbeit"}, blocking=True)
        assert m.items[uid]["status"] == "in_arbeit"
        await hass.services.async_call(DOMAIN, "update_item", {"item_id": uid, "status": "erledigt"}, blocking=True)
        assert m.items[uid]["status"] == "erledigt" and m.items[uid]["read"] is True and m.items[uid]["done_at"]

        client = await hass_ws_client(hass)
        await client.send_json({"id": 1, "type": "schulmanager/data"})
        res = (await client.receive_json())["result"]
        assert res["languages"] == [["de", "Deutsch"], ["en", "English"], ["ca", "Català"]]
        item = next(i for i in res["children"][0]["items"] if i["uid"] == uid)
        assert item["status"] == "erledigt" and item["status_label"] == "Erledigt"
        assert item["summaries"]["en"] == "Homework missing."

        await hass.services.async_call(DOMAIN, "update_item", {"item_id": uid, "status": "offen"}, blocking=True)
        assert m.items[uid]["status"] == "offen" and "done_at" not in m.items[uid]

        # Einstellung aus: alle Termine wieder sichtbar
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"ki": {"ai_task_entity": "ai_task.claude", "summary_languages": []}, "termine": {"own_class_only": False}},
        )
        await hass.async_block_till_done()
        m = entry.runtime_data
        assert m.summary_languages == ["de", "en"]  # leer -> Standard
        ev = {e["uid"]: e for e in m.child_events("anna")}
        assert "a3" in ev and "a4" in ev

        # Einstellungen von der Startseite erreichbar
        cfg = dash_mod.build_config(hass, m, "tabs")
        head = cfg["views"][0]["header"]["card"]
        assert head["type"] == "custom:schulmanager-header"
        assert head["settings_path"] == "/config/integrations/integration/schulmanager"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_translate_missing_summaries(hass: HomeAssistant, media_dir) -> None:
    """Fehlende Sprachen werden nur übersetzt – Aufgaben, Status und Kommentare bleiben unberührt."""
    today = dt_util.now().date()
    calls: list[str] = []

    async def fake_ai(call: ServiceCall):
        text = call.data["instructions"]
        calls.append(text)
        if text.startswith("Übersetze"):
            return {"data": {"en": "Class trip, transfer 185 €.", "es": "Viaje escolar, transferir 185 €."}}
        # Auswertung wie vor 0.8.0: nur deutsche Zusammenfassung
        return {"data": {
            "zusammenfassung": "Klassenfahrt, 185 € überweisen.", "kategorie": "zahlung", "dringlichkeit": "mittel",
            "aufgaben": [{"titel": "Klassenfahrt bezahlen", "typ": "zahlung", "betrag": 185}], "termine": [],
        }}

    hass.services.async_register("ai_task", "generate_data", fake_ai, supports_response=SupportsResponse.ONLY)

    async def fake_fetch(self, need_download=None, teachers=False):
        res = _fake_result(today, with_pdf=False)
        res.children[0].items = [res.children[0].items[0]]
        return res

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        options={"ai_task_entity": "ai_task.claude", "summary_languages": ["de"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    uid = "bspgym-7-elternbrief-501"
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        for _ in range(40):
            if m.items[uid]["analysis"].get("status") == "fertig":
                break
            await asyncio.sleep(0.05)
        tid = next(t for t, task in m.tasks.items() if task.get("item_uid") == uid and task.get("source") == "ki")
        before = {t: dict(task) for t, task in m.tasks.items()}
        m.update_task(tid, status="erledigt", comment="überwiesen")
        m.items[uid]["analysis"].pop("summaries", None)  # Stand vor 0.8.0
        analyses = sum(1 for c in calls if not c.startswith("Übersetze"))

        # Sprachen erweitern -> nur Übersetzung, keine neue Auswertung
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
        await hass.config_entries.options.async_configure(result["flow_id"], {"ki": {"ai_task_entity": "ai_task.claude", "summary_languages": ["de", "en", "es"]}})
        await hass.async_block_till_done()
        m = entry.runtime_data
        for _ in range(60):
            if len(m.items[uid]["analysis"].get("summaries") or {}) == 3:
                break
            await asyncio.sleep(0.05)
        a = m.items[uid]["analysis"]
        assert a["summaries"] == {
            "de": "Klassenfahrt, 185 € überweisen.",
            "en": "Class trip, transfer 185 €.",
            "es": "Viaje escolar, transferir 185 €.",
        }
        assert sum(1 for c in calls if not c.startswith("Übersetze")) == analyses
        assert any(c.startswith("Übersetze") and "Englisch (en)" in c for c in calls)
        assert set(m.tasks) == set(before)  # keine neuen oder doppelten Aufgaben
        assert m.tasks[tid]["status"] == "erledigt" and m.tasks[tid]["comment"] == "überwiesen"
        # kein zweiter Versuch, wenn schon alles da ist
        assert m._missing_translations() == []
    await hass.config_entries.async_unload(entry.entry_id)


async def test_translation_retry_and_progress(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """#2: fehlgeschlagene Übersetzungen erneut versuchen; #3: Fortschritt und Benachrichtigung."""
    from unittest.mock import MagicMock

    today = dt_util.now().date()
    state = {"fail_next": 0}

    async def fake_ai(call: ServiceCall):
        text = call.data["instructions"]
        if text.startswith("Übersetze"):
            if state["fail_next"]:
                state["fail_next"] -= 1
                return {"data": "keine JSON-Antwort"}
            return {"data": {"en": "English summary."}}
        return {"data": {"zusammenfassung": "Deutsche Zusammenfassung.", "kategorie": "info",
                         "dringlichkeit": "niedrig", "aufgaben": [], "termine": []}}

    hass.services.async_register("ai_task", "generate_data", fake_ai, supports_response=SupportsResponse.ONLY)

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today, with_pdf=False)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        options={"ai_task_entity": "ai_task.claude", "summary_languages": ["de"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    notices = MagicMock()
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch), \
         patch("custom_components.schulmanager.manager.TRANSLATE_NOTIFY_MIN", 1), \
         patch("custom_components.schulmanager.manager.persistent_notification.async_create", notices):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        analysed = [i for i in m.items.values() if i["analysis"].get("summary")]
        for _ in range(40):
            analysed = [i for i in m.items.values() if i["analysis"].get("status") == "fertig"]
            if len(analysed) >= 2:
                break
            await asyncio.sleep(0.05)
        assert len(analysed) >= 2

        # Fortschritt für Karte und Sensor
        m._translate_batch = {"total": 4, "done": 1, "failed": 1, "new_langs": ["ca"]}
        assert m.translation_progress == {"done": 2, "total": 4, "languages": ["Català"]}
        client = await hass_ws_client(hass)
        await client.send_json({"id": 1, "type": "schulmanager/data"})
        assert (await client.receive_json())["result"]["translation"]["total"] == 4
        m._translate_batch = None

        # Englisch dazu: eine Übersetzung schlägt fehl
        state["fail_next"] = 1
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"ki": {"ai_task_entity": "ai_task.claude", "summary_languages": ["de", "en"]}}
        )
        await hass.async_block_till_done()
        m = entry.runtime_data
        items = [i for i in m.items.values() if i["analysis"].get("summary")]
        for _ in range(80):
            if m._translate_batch is None and all(
                "en" in (i["analysis"].get("summaries") or {}) or i["analysis"].get("translate_failed") for i in items
            ):
                break
            await asyncio.sleep(0.05)
        failed = [i for i in items if i["analysis"].get("translate_failed")]
        assert len(failed) == 1 and failed[0]["analysis"]["translate_failed"]["count"] == 1
        assert m._missing_translations() == []  # Wartezeit läuft
        texts = [c.args[1] for c in notices.call_args_list]
        assert any("übersetzt (ca." in t and "English" in t for t in texts)
        assert any(t.startswith("Fertig:") and "1 fehlgeschlagen" in t for t in texts)
        sensor = hass.states.get("sensor.schulmanager_letzter_abruf")
        assert sensor.attributes["uebersetzung_ausstehend"] == 0

        # nach der Wartezeit: neuer Versuch klappt
        item = failed[0]
        item["analysis"]["translate_failed"]["at"] = (dt_util.now() - timedelta(hours=7)).isoformat()
        assert m._missing_translations() == [item]
        m._queue_event.set()
        for _ in range(60):
            if "en" in (item["analysis"].get("summaries") or {}):
                break
            await asyncio.sleep(0.05)
        assert item["analysis"]["summaries"]["en"] == "English summary."
        assert "translate_failed" not in item["analysis"]

        # nach 3 Fehlschlägen kein weiterer Versuch – außer die Sprachauswahl ändert sich
        item["analysis"]["summaries"].pop("en")
        item["analysis"]["translate_failed"] = {"langs": ["de", "en"], "count": 3, "at": (dt_util.now() - timedelta(days=2)).isoformat()}
        assert m._missing_translations() == []
        item["analysis"]["translate_failed"]["langs"] = ["de"]
        assert m._missing_translations() == [item]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_settings_sections(hass: HomeAssistant, media_dir) -> None:
    """#4: Einstellungen in einklappbaren Abschnitten, gespeichert wird flach."""
    from custom_components.schulmanager.config_flow import SETTINGS_SECTIONS

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "demo", "school_name": "Demo", "username": "x", "password": "p"}]},
        options={"reminder_days": "1,0", "summary_languages": ["de", "ca"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    schema = result["data_schema"].schema
    names = [str(k) for k in schema]
    assert names == [n for n, _keys, _c in SETTINGS_SECTIONS]
    sec = {str(k): v for k, v in schema.items()}
    assert sec["sprachansagen"].options["collapsed"] is True and sec["ki"].options["collapsed"] is False
    # gespeicherte Werte erscheinen als Vorgabe im richtigen Abschnitt
    bell = {str(k): k for k in sec["benachrichtigungen"].schema.schema}
    assert bell["reminder_days"].default() == "1,0"
    # so, wie die Oberfläche das Formular bekommt: Abschnitte ohne eigenen Vorgabewert,
    # die gespeicherten Werte stecken in den Feldern (sonst bleiben die Felder leer)
    import voluptuous_serialize
    from homeassistant.helpers import config_validation as cv

    ui = voluptuous_serialize.convert(result["data_schema"], custom_serializer=cv.custom_serializer)
    by_name = {f["name"]: f for f in ui}
    assert all("default" not in f for f in ui)
    fields = {f["name"]: f for f in by_name["benachrichtigungen"]["schema"]}
    assert fields["reminder_days"]["default"] == "1,0"
    langs = {f["name"]: f for f in by_name["ki"]["schema"]}["summary_languages"]
    assert langs["default"] == ["de", "ca"]
    # jede Option steckt in genau einem Abschnitt und hat Texte in beiden Sprachen
    all_keys = [k for _n, keys, _c in SETTINGS_SECTIONS for k in keys]
    assert len(all_keys) == len(set(all_keys))
    for lang in ("de", "en"):
        tr = json.load(open(f"custom_components/schulmanager/translations/{lang}.json"))
        sections = tr["options"]["step"]["settings"]["sections"]
        for name, keys, _c in SETTINGS_SECTIONS:
            assert sections[name]["name"]
            assert set(keys) <= set(sections[name]["data"]) and set(keys) <= set(sections[name]["data_description"])
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"dashboard": {"dashboard": "single"}, "abruf": {"scan_interval": 60}}
    )
    await hass.async_block_till_done()
    assert entry.options["dashboard"] == "single" and entry.options["scan_interval"] == 60
    assert entry.options["reminder_days"] == "1,0" and entry.options["summary_languages"] == ["de", "ca"]
    assert not any(n in entry.options for n, _k, _c in SETTINGS_SECTIONS if n != "dashboard")
    # in einem mitgeschickten Abschnitt lässt sich ein Feld leeren (KI-Dienst entfernen)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "ai_task_entity": "ai_task.x"})
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "settings"})
    await hass.config_entries.options.async_configure(result["flow_id"], {"ki": {"summary_languages": ["de"]}})
    await hass.async_block_till_done()
    assert "ai_task_entity" not in entry.options and entry.options["reminder_days"] == "1,0"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_published_date_prefix(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """#5: Erscheinungsdatum im Portal vor dem Betreff (Tagesübersicht, Aufgaben, To-do-Liste)."""
    today = dt_util.now().date()
    sent = today - timedelta(days=1)
    prefix = sent.strftime("%d.%m.")

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        for _ in range(40):
            if any(t.get("type") == "zahlung" for t in m.tasks.values()):
                break
            await asyncio.sleep(0.05)
        pay = next(t for t in m.tasks.values() if t.get("type") == "zahlung")
        title_before, ids_before = pay["title"], set(m.tasks)

        # Tagesübersicht
        assert f"{prefix} · {m.task_label(pay)}" in m.digest_text()

        # eigene Aufgabe: Anlagedatum
        own = m.add_task("anna", "Turnbeutel mitgeben")
        assert m.dated("x", own) == f"{today.strftime('%d.%m.')} · x"
        # früheres Schuljahr mit Jahr
        assert m.date_prefix(today - timedelta(days=400)).count(".") == 2

        # Karte
        client = await hass_ws_client(hass)
        await client.send_json({"id": 1, "type": "schulmanager/data"})
        res = (await client.receive_json())["result"]
        t = next(x for x in res["children"][0]["tasks"] if x["id"] == pay["id"])
        assert t["published"] == sent.isoformat() and t["title"] == title_before

        # To-do-Liste mit Datum; Umbenennen übernimmt den Titel ohne Datum
        items = await hass.services.async_call(
            "todo", "get_items", {"entity_id": "todo.schule_anna_aufgaben"}, blocking=True, return_response=True
        )
        summary = next(i["summary"] for i in items["todo.schule_anna_aufgaben"]["items"] if i["uid"] == pay["id"])
        assert f"{prefix} · " in summary
        await hass.services.async_call(
            "todo", "update_item",
            {"entity_id": "todo.schule_anna_aufgaben", "item": pay["id"], "rename": summary.replace("bezahlen", "überweisen")},
            blocking=True,
        )
        assert prefix not in m.tasks[pay["id"]]["title"] and "überweisen" in m.tasks[pay["id"]]["title"]
        assert set(m.tasks) >= ids_before
    await hass.config_entries.async_unload(entry.entry_id)


async def test_archive_events(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """Termine & Fristen: archivieren, reaktivieren, bleibt gespeichert, wird aufgeräumt."""
    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()

    async def fake_fetch(self, need_download=None, teachers=False):
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        ws = await hass_ws_client(hass)

        async def events() -> list[dict]:
            await ws.send_json({"id": events.n, "type": "schulmanager/data"})
            events.n += 1
            return (await ws.receive_json())["result"]["children"][0]["events"]

        events.n = 1
        evs = await events()
        assert evs and not any(e["archived"] for e in evs)
        uid = evs[0]["uid"]
        child = "anna"

        await hass.services.async_call(DOMAIN, "archive_event", {"child": child, "event_id": uid}, blocking=True)
        evs = await events()
        assert next(e for e in evs if e["uid"] == uid)["archived"]
        assert sum(e["archived"] for e in evs) == 1
        m = entry.runtime_data
        assert uid in m.data["archived"][child]

        # bleibt nach einem Abruf erhalten, weil es den Termin noch gibt
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert uid in m.archived_events(child)

        # unbekanntes Kind -> Fehler
        with pytest.raises(Exception):
            await hass.services.async_call(DOMAIN, "archive_event", {"child": "nobody", "event_id": uid}, blocking=True)

        # Reaktivieren
        await hass.services.async_call(DOMAIN, "unarchive_event", {"child": child, "event_id": uid}, blocking=True)
        assert not any(e["archived"] for e in await events())
        assert child not in m.data["archived"]

        # verschwundene Termine werden beim nächsten fehlerfreien Abruf aus dem Archiv entfernt
        await hass.services.async_call(DOMAIN, "archive_event", {"child": child, "event_id": "gibt-es-nicht"}, blocking=True)
        assert "gibt-es-nicht" in m.archived_events(child)
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        assert "gibt-es-nicht" not in m.archived_events(child)
    await hass.config_entries.async_unload(entry.entry_id)


# Aufbau wie im Eltern-Portal unter Service → Schulinformationen (erfundene Namen)
_TEACHERS_HTML = """<div id="asam_content">
<div class="row m_bot"><div class="col-md-4"></div><div class="col-md-8"><h3>Wer macht Was</h3></div></div>
<div class="row m_bot"><div class="col-md-4"><b>Schulkürzel</b></div><div class="col-md-6">BSP</div></div>
<div class="row m_bot"><div class="col-md-4"></div><div class="col-md-8"><h3>Stundenplankürzel der Lehrkräfte</h3></div></div>
<div class="row m_bot"><div class="col-md-4"><div class="text-right hidden-xs hidden-sm"><b>Kurz</b></div><div class="hidden-md hidden-lg"><b>Kurz</b></div></div><div class="col-md-6">Karla   Kurzweil</div></div>
<div class="row m_bot"><div class="col-md-4"><div class="text-right hidden-xs hidden-sm"><b>Lang</b></div><div class="hidden-md hidden-lg"><b>Lang</b></div></div><div class="col-md-6">Lena Lang-Weilig</div></div>
<div class="row m_bot"><div class="col-md-4"></div><div class="col-md-8"><h3>Sonstiges</h3></div></div>
<div class="row m_bot"><div class="col-md-4"><b>X</b></div><div class="col-md-6">gehört nicht dazu</div></div>
</div>"""


def test_parse_teachers() -> None:
    """Stundenplankürzel aus den Schulinformationen; Seite ohne Abschnitt -> None."""
    from custom_components.schulmanager.portal import parse_teachers

    assert parse_teachers(_TEACHERS_HTML) == {"Kurz": "Karla Kurzweil", "Lang": "Lena Lang-Weilig"}
    assert parse_teachers("<div id='asam_content'><h3>Wer macht Was</h3></div>") is None
    table = "<h3>Stundenplankürzel der Lehrkräfte</h3><table><tr><th>Kürzel</th><th>Name</th></tr><tr><td>Mü</td><td>Maria Müller</td></tr></table>"
    assert parse_teachers(table) == {"Mü": "Maria Müller"}


async def test_teacher_names(hass: HomeAssistant, media_dir, hass_ws_client) -> None:
    """Kürzel werden je Schule zu Namen; Liste höchstens täglich, Einstellung wirkt."""
    from custom_components.schulmanager.portal import parse_substitutions, parse_teachers

    await async_setup_component(hass, "http", {})
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)
    html = _SUBST_HTML.format(d0=today.strftime("%d.%m.%Y"), d1=tomorrow.strftime("%d.%m.%Y"))
    state = {"subst": parse_substitutions(html), "teacher_calls": [], "list": parse_teachers(_TEACHERS_HTML)}

    async def fake_fetch(self, need_download=None, teachers=False):
        state["teacher_calls"].append(teachers)
        res = _fake_result(today)
        res.children[0].substitutions = state["subst"]
        res.teachers = state["list"] if teachers else None
        return res

    notified: list[dict] = []

    async def fake_notify(call: ServiceCall) -> None:
        notified.append(dict(call.data))

    hass.services.async_register("notify", "handy", fake_notify)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        options={"notify_services": ["notify.handy"]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        assert state["teacher_calls"] == [True]
        assert m.data["teachers"]["bspgym"]["list"]["Kurz"] == "Karla Kurzweil"
        # neue Vertretung -> Push nennt Kürzel und Namen
        state["subst"]["days"][1]["entries"].append(
            {"lesson": "1", "teacher": "Kurz", "substitute": "Lang", "subject": "Ph",
             "old_subject": None, "room": "P1", "info": "", "kind": "vertretung"}
        )
        state["subst"]["days"][1]["entries"].append(
            {"lesson": "1", "teacher": "Unbek", "substitute": "Lang", "subject": "Ph",
             "old_subject": None, "room": "P1", "info": "", "kind": "vertretung"}
        )
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
        # Liste nur einmal am Tag
        assert state["teacher_calls"] == [True, False]
        push = [n for n in notified if "Vertretungsplan" in n.get("title", "")][-1]
        assert "Vertretung Lang (Lena Lang-Weilig), Raum P1" in push["message"]

    st = hass.states.get("sensor.schule_anna_vertretungen")
    e = next(x for x in st.attributes["eintraege"] if x["vertretung"] == "Lang")
    assert e["vertretung_name"] == "Lena Lang-Weilig" and e["lehrkraft_name"] == "Karla Kurzweil"
    assert "Lang (Lena Lang-Weilig)" in e["text"]
    ev = next(x for x in m.child_events("anna") if x["uid"].startswith("vertretung-") and "Ph" in x["title"])
    # unbekanntes Kürzel bleibt stehen
    assert "Lehrkräfte laut Plan: Kurz (Karla Kurzweil), Unbek" in ev["hover"]
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "schulmanager/data"})
    res = (await ws.receive_json())["result"]
    ent = next(x for d in res["children"][0]["substitutions"]["days"] for x in d["entries"] if x["substitute"] == "Lang")
    assert ent["substitute_label"] == "Lang (Lena Lang-Weilig)"

    # nur Name
    hass.config_entries.async_update_entry(entry, options={**entry.options, "teacher_names": "name"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.teacher_label("anna", "Kurz, Lang") == "Karla Kurzweil, Lena Lang-Weilig"
    # nur Kürzel: keine Auflösung, Liste wird nicht mehr abgerufen
    hass.config_entries.async_update_entry(entry, options={**entry.options, "teacher_names": "kuerzel"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    assert m.teacher_label("anna", "Kurz") == "Kurz"
    assert m._teachers_due("bspgym") is False
    # Liste ist älter als ein Tag -> wieder fällig; leere Antwort überschreibt nichts
    hass.config_entries.async_update_entry(entry, options={**entry.options, "teacher_names": "beide"})
    await hass.async_block_till_done()
    m = entry.runtime_data
    m.data["teachers"]["bspgym"]["updated"] = (dt_util.now() - timedelta(days=2)).isoformat()
    assert m._teachers_due("bspgym") is True
    state["list"] = {}
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", fake_fetch):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
    assert m.data["teachers"]["bspgym"]["list"]["Lang"] == "Lena Lang-Weilig"
    assert m._teachers_due("bspgym") is False
    await hass.config_entries.async_unload(entry.entry_id)


async def test_fetch_retries_after_disconnect(hass: HomeAssistant, media_dir) -> None:
    """Trennt das Portal die Verbindung, wird einmal neu versucht – mit frischer Sitzung (#8)."""
    import aiohttp

    today = dt_util.now().date()
    calls: list[int] = []

    async def flaky(self, need_download=None, teachers=False):
        calls.append(id(self._session))
        if len(calls) == 1:
            raise aiohttp.ServerDisconnectedError()
        return _fake_result(today)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"portals": [{"school": "bspgym", "school_name": "M", "username": "x", "password": "p"}]},
        unique_id=DOMAIN,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", flaky), \
         patch("custom_components.schulmanager.manager.FETCH_RETRY_DELAY", 0):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        m = entry.runtime_data
        assert len(calls) == 2 and m.last_errors == [], m.last_errors
        assert m.items

    async def always_down(self, need_download=None, teachers=False):
        calls.append(1)
        raise aiohttp.ServerDisconnectedError()

    calls.clear()
    with patch("custom_components.schulmanager.portal.SchulPortal.async_fetch", always_down), \
         patch("custom_components.schulmanager.manager.FETCH_RETRY_DELAY", 0):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        await hass.async_block_till_done()
    assert len(calls) == 2
    assert any("Portal nicht erreichbar" in e for e in m.last_errors), m.last_errors
    await hass.config_entries.async_unload(entry.entry_id)
