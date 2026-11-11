"""Portal protocol failures, optional pages and malformed server responses."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from custom_components.eltern_portal_schulmanager import portal as p


class Response:
    def __init__(self, *, body=b"PDF", text="", status=200, headers=None, length=None):
        self.status = status
        self.headers = headers or {"Content-Type": "application/pdf"}
        self.content_length = length
        self.read = AsyncMock(return_value=body)
        self.text = AsyncMock(return_value=text)
        self.raise_for_status = Mock()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


def test_download_filename_encoding_and_school_links():
    assert p.school_from_input("bspgym.eltern-portal.org/login") == "bspgym"
    assert p._filename_from_response(Response(headers={"Content-Disposition": "attachment; filename*=UTF-8''Gr%C3%BCn.pdf"}), "fallback") == "Grün.pdf"
    assert p._filename_from_response(Response(headers={"Content-Disposition": 'attachment; filename="GrÃ¼n.pdf"'}), "fallback") == "Grün.pdf"
    assert p._filename_from_response(Response(headers={"Content-Disposition": 'attachment; filename="普通.pdf"'}), "fallback") == "普通.pdf"


@pytest.mark.parametrize("response,expected", [
    (Response(status=503), 0),
    (Response(headers={"Content-Type": "text/html"}), 0),
    (Response(length=p.MAX_FILE_SIZE+1), 0),
    (Response(body=b"oversize"), 0),
    (Response(), 1),
])
async def test_attachment_validation(response, expected):
    client = p.SchulPortal(Mock(get=Mock(return_value=response)), "bspgym", "x", "p")
    item = p.PortalItem("id", "nachricht", "Title", "", None, "https://example.invalid", attachments=[p.PortalAttachment(None, "download")])
    limit = 2 if response.read.return_value == b"oversize" else p.MAX_FILE_SIZE
    with patch.object(p, "MAX_FILE_SIZE", limit):
        await client._download_item(item)
    assert len(item.files) == expected
    if expected:
        assert item.files[0].name == "anhang_1.pdf"


async def test_download_connection_failure_and_optional_sections():
    client = p.SchulPortal(Mock(get=Mock(side_effect=aiohttp.ClientConnectionError("offline"))), "bspgym", "x", "p")
    item = p.PortalItem("id", "nachricht", "Title", "", None, "", attachments=[p.PortalAttachment("file.pdf", "download")])
    await client._download_item(item)
    assert not item.files
    assert "nicht verfügbar" in await client._section("lesson", AsyncMock(side_effect=aiohttp.ClientConnectionError()))
    assert "changed layout" in await client._section("letter", AsyncMock(side_effect=ValueError("changed layout")))
    with pytest.raises(aiohttp.ClientConnectionError):
        await client._section("letter", AsyncMock(side_effect=aiohttp.ClientConnectionError()))


async def test_message_detail_missing_rows_and_external_links():
    client = p.SchulPortal(Mock(), "bspgym", "x", "p")
    assert client._parse_message_detail("<html></html>") == (None, "", [])
    markup = '''<div id="message-thread-grid"><div class="row"><div>single</div></div>
    <div class="row"><div>Author</div><div>no segment</div></div>
    <div class="row"><div>Author</div><div><div class="ui segment">Hello
    <a href="mailto:x@example.invalid">mail</a><a href="https://example.invalid/info">external</a>
    <a href="download/1">file.pdf</a></div></div></div></div>'''
    _, body, attachments = client._parse_message_detail(markup)
    assert 'https://example.invalid/info' in body
    assert len(attachments) == 1
    # Unknown rows and broken dates do not abort reading other messages.
    client._student = SimpleNamespace(student_id="7", messages=[])
    html = '''<table id="messages-fachlehrer-table"><tbody><tr class="message-row"><td>x</td></tr>
    <tr class="message-row" onclick="showMessageFachlehrer(1, 2)"><td>Author</td><td></td><td>Title</td><td>undated</td></tr></tbody></table>'''
    client._session = Mock(get=Mock(return_value=Response(text=markup)))
    await client.async_message_parse(html)
    assert len(client._extra_messages) == 1
    assert client._extra_messages[0].sent is None


async def test_online_fetch_keeps_optional_errors_scoped():
    # Seed realistic student objects from the dependency's demo, then exercise
    # the online protocol with fully mocked HTTP; no live school is contacted.
    client = p.SchulPortal(Mock(), "demo", "x", "p")
    await client.async_base_demo()
    await client.async_login_demo()
    client._demo = False
    client.school = "bspgym"
    with patch.object(client, "async_base_online", new=AsyncMock()), patch.object(client, "async_login_online", new=AsyncMock()), patch.object(client, "async_set_child_online", new=AsyncMock()), patch.object(client, "async_teachers_online", new=AsyncMock(side_effect=ValueError("not enabled"))), patch.object(client, "async_course_registrations_online", new=AsyncMock(side_effect=ValueError("not enabled"))), patch.object(p.ElternPortalAPI, "async_logout_online", new=AsyncMock(side_effect=aiohttp.ClientError())):
        for section in ("appointment", "letter", "message", "blackboard", "poll", "lesson", "substitution", "sicknote"):
            setattr(client, f"async_{section}_online", AsyncMock(side_effect=ValueError("section unavailable")))
        result = await client.async_fetch(teachers=True)
    assert result.children
    assert result.errors and result.children[0].timetable is None
    assert not client._keep_session and client._student is None


async def test_teacher_and_registration_pages():
    session = Mock(get=Mock(return_value=Response(text="<html></html>")))
    client = p.SchulPortal(session, "bspgym", "x", "p")
    assert await client.async_teachers_online() == {}
    assert await client.async_course_registrations_online() is None
    assert session.get.call_count == 2


def test_teacher_table_and_missing_cells():
    html = '''<div><h3>Stundenplankürzel der Lehrkräfte</h3></div><div><span>empty row</span></div>
    <div><b>AB</b><span>Anna Example</span></div><h3>Other information</h3>'''
    result = p.parse_teachers(html)
    assert result.get("AB") == "Anna Example"


async def test_online_fetch_downloads_before_logout():
    client = p.SchulPortal(Mock(), "demo", "x", "p")
    await client.async_base_demo()
    await client.async_login_demo()
    client._demo = False
    client.school = "bspgym"
    with patch.object(client, "async_base_online", new=AsyncMock()), patch.object(client, "async_login_online", new=AsyncMock()), patch.object(client, "async_set_child_online", new=AsyncMock()), patch.object(client, "async_teachers_online", new=AsyncMock(return_value={"AB": "Example"})), patch.object(client, "async_course_registrations_online", new=AsyncMock(return_value=[])), patch.object(client, "_download_item", new=AsyncMock()) as download, patch.object(p.ElternPortalAPI, "async_logout_online", new=AsyncMock()) as logout:
        for section in ("appointment", "letter", "message", "blackboard", "poll", "lesson", "substitution", "sicknote"):
            setattr(client, f"async_{section}_online", getattr(client, f"async_{section}_demo"))
        result = await client.async_fetch(lambda _: True, teachers=True)
        assert result.children and result.teachers == {"AB": "Example"}
        assert download.called
        logout.assert_awaited_once()
        client._keep_session = True
        await client.async_logout_online()
        assert logout.await_count == 1
        client._keep_session = False
        await client.async_logout_online()
        assert logout.await_count == 2


async def test_blackboard_ignores_missing_heading_and_bad_dates():
    client = p.SchulPortal(Mock(), "demo", "x", "p")
    await client.async_base_demo()
    await client.async_login_demo()
    client._student = client.students[0]
    await client.async_blackboard_parse('''<div id="asam_content"><div class="grid">
    <div class="grid-item"><div class="well">no heading</div></div>
    <div class="grid-item"><div class="well"><h4>Old</h4>eingestellt am 01.01.2000</div></div>
    <div class="grid-item"><div class="well"><h4>Undated</h4>eingestellt am 31.02.2026<a href="https://external.example.invalid/file.pdf">link</a><a href="information">info</a></div></div>
    </div></div>''')
    assert len(client._blackboard_items) == 1
    assert client._blackboard_items[0].title == "Undated"
    assert client._blackboard_items[0].sent is None
