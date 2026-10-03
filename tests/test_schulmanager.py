"""Tests für den Schulmanager in einer echten Home-Assistant-Testinstanz."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import io
import json
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

    async def fake_fetch(self, need_download=None):
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

    async def fake_fetch(self, need_download=None):
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
        {"notify_services": ["mobile_app_handy_2"], "reminder_days": "2,0", "digest_time": "07:00:00"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
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

    async def fake_fetch(self, need_download=None):
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

    async def fake_fetch(self, need_download=None):
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
