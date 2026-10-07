"""Zugriff auf das Eltern-Portal (eltern-portal.org).

Baut auf der Bibliothek ``pyelternportal`` auf, ergänzt aber, was ein
Schulmanager braucht und die Bibliothek nicht liefert:

* stabile IDs für Nachrichten und Aushänge,
* Download-Links von Elternbrief-PDFs und Nachrichten-Anhängen,
* das Herunterladen der Dateien innerhalb derselben Portal-Sitzung,
* die Stundenplankürzel der Lehrkräfte (Service → Schulinformationen).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import re
from typing import Any
from urllib import parse

import aiohttp
import bs4
import pyelternportal
from pyelternportal import ElternPortalAPI
from pyelternportal.exception import (
    BadCredentialsException,
    CannotConnectException,
    ResolveHostnameException,
    StudentListException,
)

from .const import (
    KIND_BLACKBOARD,
    KIND_LETTER,
    KIND_MESSAGE,
    KIND_POLL,
    LOGGER,
)

MAX_FILE_SIZE = 25 * 1024 * 1024
# Seite mit den Stundenplankürzeln der Lehrkräfte (Abschnitt in den Schulinformationen)
TEACHERS_PATH = "service/schulinformationen"
# Bereiche, die nicht jede Schule anbietet: Netzwerkfehler dort brechen den Abruf nicht ab
OPTIONAL_SECTIONS = frozenset({"lesson", "substitution", "sicknote"})

PortalAuthError = BadCredentialsException
PortalConnectionError = (
    CannotConnectException,
    ResolveHostnameException,
    StudentListException,
    aiohttp.ClientError,
    TimeoutError,
)


@dataclass
class PortalFile:
    """Eine heruntergeladene Datei."""

    name: str
    content: bytes
    content_type: str | None = None


@dataclass
class PortalAttachment:
    """Verweis auf einen Anhang im Portal."""

    name: str | None
    href: str


@dataclass
class PortalItem:
    """Ein Eingang aus dem Portal (Brief, Nachricht, Aushang, Umfrage)."""

    uid: str
    kind: str
    title: str
    body: str
    sent: datetime | None
    url: str
    sender: str | None = None
    version: str | None = None
    attachments: list[PortalAttachment] = field(default_factory=list)
    files: list[PortalFile] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortalChild:
    """Ein Kind mit allen Daten aus einem Portal."""

    student_id: str
    fullname: str
    firstname: str
    classname: str | None
    items: list[PortalItem] = field(default_factory=list)
    appointments: list[dict[str, Any]] = field(default_factory=list)
    # Stundenplan: None = nicht gelesen (Fehler), sonst Liste der Stunden
    timetable: list[dict[str, Any]] | None = None
    # Vertretungsplan: None = nicht gelesen (Fehler), sonst Tage mit Einträgen
    substitutions: dict[str, Any] | None = None
    # Krankmeldungen: None = nicht gelesen (Fehler), sonst Liste {start, end, comment}
    sicknotes: list[dict[str, Any]] | None = None


@dataclass
class PortalResult:
    """Ergebnis eines Abrufs."""

    school: str
    school_name: str
    base_url: str
    children: list[PortalChild]
    errors: list[str] = field(default_factory=list)
    # Stundenplankürzel -> Name; None = nicht abgerufen oder Fehler
    teachers: dict[str, str] | None = None


def school_from_input(value: str) -> str:
    """Schulkennung aus Eingabe oder kompletter Portal-URL ermitteln.

    ``https://bspgym.eltern-portal.org?username=...`` -> ``bspgym``
    """
    value = value.strip().lower()
    if "eltern-portal.org" in value:
        if "://" not in value:
            value = "https://" + value
        host = parse.urlparse(value).hostname or ""
        return host.split(".")[0]
    return value


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _filename_from_response(resp: aiohttp.ClientResponse, fallback: str) -> str:
    disp = resp.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", disp, re.I)
    if match:
        return parse.unquote(match.group(1)).strip('"')
    match = re.search(r'filename\s*=\s*"?([^";]+)"?', disp, re.I)
    if match:
        name = match.group(1)
        try:  # Portale liefern Umlaute gerne als latin-1
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return name
    return fallback


class SchulPortal(ElternPortalAPI):
    """Erweiterter Portal-Client für genau ein Eltern-Portal."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        school: str,
        username: str,
        password: str,
        lookback_days: int = 120,
    ) -> None:
        super().__init__(session)
        self.set_config(school, username, password)
        self.set_option(
            appointment=True,
            blackboard=True,
            letter=True,
            message=True,
            poll=True,
            lesson=True,
            substitution=True,
            sicknote=True,
        )
        neg = -abs(int(lookback_days))
        self.set_option_threshold(
            blackboard_threshold=neg,
            letter_threshold=neg,
            message_threshold=neg,
            poll_threshold=neg,
        )
        self._letter_links: dict[str, str] = {}
        self._timetable: list[dict[str, Any]] = []
        self._subst: dict[str, Any] = {"days": [], "stand": None, "available": False}
        self._extra_messages: list[PortalItem] = []
        self._keep_session = False

    # ------------------------------------------------------------------
    # Sitzung
    # ------------------------------------------------------------------
    async def async_logout_online(self) -> None:
        """Logout erst nach den Downloads (siehe async_fetch)."""
        if self._keep_session:
            return
        await super().async_logout_online()

    # ------------------------------------------------------------------
    # Elternbriefe: zusätzlich den Download-Link merken
    # ------------------------------------------------------------------
    async def async_letter_parse(self, html: str) -> None:
        await super().async_letter_parse(html)
        self._letter_links = {}
        soup = bs4.BeautifulSoup(html, self._beautiful_soup_parser)
        for tag in soup.select(".link_nachrichten"):
            match = re.search(r"\d+", tag.get("onclick") or "")
            href = tag.get("href")
            if match and href:
                self._letter_links[match[0]] = href


    # ------------------------------------------------------------------
    # Stundenplan: eigene Auswertung mit Uhrzeiten und Mehrfach-Kursen
    # ------------------------------------------------------------------
    async def async_lesson_parse(self, html: str) -> None:
        self._timetable = parse_timetable(html, self._beautiful_soup_parser)
        self._student.lessons = []

    # ------------------------------------------------------------------
    # Vertretungsplan: eigene Auswertung (behält das ursprüngliche Fach,
    # erkennt Entfall und auch Tage ohne Vertretung)
    # ------------------------------------------------------------------
    async def async_substitution_parse(self, html: str) -> None:
        self._subst = parse_substitutions(html, self._beautiful_soup_parser)
        self._student.substitutions = []

    # ------------------------------------------------------------------
    # Nachrichten Eltern/Fachlehrer: eigene Auswertung mit ID + Anhängen
    # ------------------------------------------------------------------
    async def async_message_parse(self, html: str) -> None:
        self._student.messages = []
        self._extra_messages = []
        soup = bs4.BeautifulSoup(html, self._beautiful_soup_parser)
        rows = soup.select("#messages-fachlehrer-table tbody tr.message-row")
        for row in rows:
            cells = row.find_all("td", recursive=False)
            match = re.search(
                r"showMessageFachlehrer\((\d+),\s*(\d+)\)", row.get("onclick", "")
            )
            if len(cells) < 4 or match is None:
                continue
            sender = cells[0].get_text(strip=True)
            subject = cells[2].get_text(strip=True)
            text = cells[3].get_text()
            sent = None
            if md := re.search(r"\d{2}\.\d{2}\.\d{4}", text):
                mt = re.search(r"\d{2}:\d{2}", text)
                sent = datetime.strptime(
                    f"{md[0]} {mt[0] if mt else '00:00'}", "%d.%m.%Y %H:%M"
                )
            path = f"meldungen/kommunikation_fachlehrer/{match[1]}/{match[2]}"
            if self._demo:
                from pyelternportal.demo import DEMO_HTML_MESSAGE_DETAIL

                detail_html = DEMO_HTML_MESSAGE_DETAIL
            else:
                async with self._session.get(
                    parse.urljoin(self.base_url, path)
                ) as resp:
                    detail_html = await resp.text()
            d_subject, body, attachments = self._parse_message_detail(detail_html)
            native = f"{match[1]}_{match[2]}"
            self._extra_messages.append(
                PortalItem(
                    uid=self._uid(KIND_MESSAGE, native),
                    kind=KIND_MESSAGE,
                    title=d_subject or subject or "Nachricht",
                    body=body or "",
                    sent=sent,
                    sender=sender,
                    url=parse.urljoin(self.base_url, path),
                    version=_stable_id(sent, body),
                    attachments=attachments,
                )
            )

    def _parse_message_detail(
        self, html: str
    ) -> tuple[str | None, str, list[PortalAttachment]]:
        soup = bs4.BeautifulSoup(html, self._beautiful_soup_parser)
        subject = None
        parts: list[str] = []
        attachments: list[PortalAttachment] = []
        grid = soup.select_one("#message-thread-grid")
        if grid is None:
            return None, "", []
        for row in grid.select(":scope > div.row"):
            cols = row.find_all("div", recursive=False)
            if len(cols) < 2:
                continue
            head = cols[0].get_text(" ", strip=True)
            if head.startswith("Betreff"):
                subject = cols[1].get_text(strip=True)
                continue
            segment = cols[1].select_one("div.ui.segment")
            if segment is None:
                continue
            for link in segment.find_all("a", href=True):
                href = link["href"]
                if href.startswith(("mailto:", "#", "javascript")):
                    continue
                if href.startswith(("http://", "https://")) and "eltern-portal.org" not in href:
                    link.append(f" ({href})")  # externer Link: im Text behalten
                    continue
                attachments.append(
                    PortalAttachment(
                        name=link.get_text(strip=True) or link.get("title"), href=href
                    )
                )
            for node in segment.find_all(string=True):
                node.replace_with(re.sub(r"\s+", " ", node))
            for br in segment.find_all("br"):
                br.replace_with("\n")
            text = re.sub(r" *\n *", "\n", segment.get_text())
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            author = head.rstrip(":")
            parts.append(f"— {author}:\n{text}")
        # Anhänge außerhalb der Textblöcke (z.B. eigene Zeile "Anhang")
        for link in grid.select("a[href*='get_file'], a[href*='download']"):
            href = link["href"]
            if not any(a.href == href for a in attachments):
                attachments.append(
                    PortalAttachment(
                        name=link.get_text(strip=True) or link.get("title"), href=href
                    )
                )
        return subject, "\n\n".join(parts), attachments

    # ------------------------------------------------------------------
    # Abruf
    # ------------------------------------------------------------------
    def _uid(self, kind: str, native: str) -> str:
        return f"{self.school}-{self._student.student_id}-{kind}-{native}"

    async def _section(self, name: str, coro_factory: Callable[[], Any]) -> str | None:
        try:
            await coro_factory()
        except (aiohttp.ClientError, TimeoutError) as err:
            if name not in OPTIONAL_SECTIONS:
                raise
            # Zusatzbereiche (Stundenplan, Vertretungen, Krankmeldungen) sind nicht
            # bei jeder Schule freigeschaltet; manche Portale trennen dann die
            # Verbindung. Das darf den Abruf der übrigen Bereiche nicht abbrechen.
            LOGGER.info("%s: Bereich '%s' nicht verfügbar: %s", self.school, name, err)
            return f"{name}: nicht verfügbar ({err or type(err).__name__})"
        except Exception as err:  # noqa: BLE001 - Portal-HTML ändert sich gern
            LOGGER.warning(
                "%s: Bereich '%s' konnte nicht gelesen werden: %s",
                self.school,
                name,
                err,
            )
            return f"{name}: {err}"
        return None

    async def async_teachers_online(self) -> dict[str, str]:
        """Stundenplankürzel der Lehrkräfte (leer, wenn die Schule sie nicht zeigt)."""
        async with self._session.get(parse.urljoin(self.base_url, TEACHERS_PATH)) as resp:
            resp.raise_for_status()
            html = await resp.text()
        return parse_teachers(html, self._beautiful_soup_parser) or {}

    async def async_fetch(
        self,
        need_download: Callable[[PortalItem], bool] | None = None,
        teachers: bool = False,
    ) -> PortalResult:
        """Alles abrufen und gewünschte Anhänge in derselben Sitzung laden.

        ``teachers`` liest zusätzlich die Stundenplankürzel der Lehrkräfte.
        """
        errors: list[str] = []
        children: list[PortalChild] = []
        teacher_list: dict[str, str] | None = None
        self._keep_session = True
        try:
            if self._demo:
                await self.async_base_demo()
                await self.async_login_demo()
            else:
                await self.async_base_online()
                await self.async_login_online()
                if teachers:
                    try:
                        teacher_list = await self.async_teachers_online()
                    except Exception as err:  # noqa: BLE001 - optional, Abruf läuft weiter
                        LOGGER.info(
                            "%s: Lehrkräfte-Kürzel nicht lesbar: %s", self.school, err
                        )
                        errors.append(
                            f"lehrkraefte: {err or type(err).__name__}"
                        )

            for self._student in self.students:
                st = self._student
                if not self._demo:
                    await self.async_set_child_online()
                sfx = "demo" if self._demo else "online"
                failed: set[str] = set()
                self._timetable = []
                self._subst = {"days": [], "stand": None, "available": False}
                for name in (
                    "appointment",
                    "letter",
                    "message",
                    "blackboard",
                    "poll",
                    "lesson",
                    "substitution",
                    "sicknote",
                ):
                    method = getattr(self, f"async_{name}_{sfx}")
                    if err := await self._section(name, method):
                        errors.append(err)
                        failed.add(name)

                child = PortalChild(
                    student_id=st.student_id,
                    fullname=st.fullname,
                    firstname=st.firstname,
                    classname=st.classname,
                )
                child.items = self._collect_items()
                if "lesson" not in failed:
                    child.timetable = list(self._timetable)
                if "substitution" not in failed:
                    child.substitutions = dict(self._subst)
                if "sicknote" not in failed:
                    child.sicknotes = [
                        {
                            "start": n.start.isoformat(),
                            "end": (n.end or n.start).isoformat(),
                            "comment": n.comment,
                        }
                        for n in getattr(st, "sicknotes", [])
                        if n.start
                    ]
                child.appointments = [
                    {
                        "uid": f"{self.school}-{st.student_id}-termin-{a.appointment_id}",
                        "title": a.short or a.title,
                        "detail": a.title if a.short and a.title != a.short else None,
                        "kind": appointment_kind(a.classname, a.short or a.title),
                        "start": a.start,
                        "end": a.end,
                    }
                    for a in st.appointments
                ]
                if need_download and not self._demo:
                    for item in child.items:
                        if item.attachments and need_download(item):
                            await self._download_item(item)
                children.append(child)
        finally:
            self._keep_session = False
            self._student = None
            if not self._demo:
                try:
                    await super().async_logout_online()
                except Exception:  # noqa: BLE001
                    LOGGER.debug("Logout fehlgeschlagen", exc_info=True)

        return PortalResult(
            school=self.school,
            school_name=self.school_name or self.school,
            base_url=self.base_url,
            children=children,
            errors=errors,
            teachers=teacher_list,
        )

    def _collect_items(self) -> list[PortalItem]:
        st = self._student
        items: list[PortalItem] = []
        for letter in st.letters:
            href = self._letter_links.get(letter.letter_id)
            items.append(
                PortalItem(
                    uid=self._uid(KIND_LETTER, letter.letter_id),
                    kind=KIND_LETTER,
                    title=letter.subject or f"Elternbrief {letter.number}",
                    body=letter.body or "",
                    sent=letter.sent,
                    url=parse.urljoin(self.base_url, "aktuelles/elternbriefe"),
                    version=_stable_id(letter.sent, letter.subject, letter.body),
                    attachments=[PortalAttachment(letter.subject, href)] if href else [],
                    meta={
                        "nummer": letter.number,
                        "empfang_bestaetigt": not letter.new,
                        "verteiler": letter.distribution,
                    },
                )
            )
        items.extend(self._extra_messages)
        for bb in st.blackboards:
            native = _stable_id(bb.sent, bb.subject)
            atts = []
            if bb.attachment and bb.attachment.href:
                atts.append(PortalAttachment(bb.attachment.name, bb.attachment.href))
            items.append(
                PortalItem(
                    uid=self._uid(KIND_BLACKBOARD, native),
                    kind=KIND_BLACKBOARD,
                    title=bb.subject or "Aushang",
                    body=bb.body or "",
                    sent=datetime.combine(bb.sent, datetime.min.time())
                    if bb.sent
                    else None,
                    url=parse.urljoin(self.base_url, "aktuelles/schwarzes_brett"),
                    version=_stable_id(bb.body),
                    attachments=atts,
                )
            )
        for poll in st.polls:
            native = (poll.href or poll.title or "").rsplit("/", 1)[-1]
            atts = []
            if poll.attachment and poll.attachment.href:
                atts.append(PortalAttachment(poll.attachment.name, poll.attachment.href))
            items.append(
                PortalItem(
                    uid=self._uid(KIND_POLL, native or _stable_id(poll.title)),
                    kind=KIND_POLL,
                    title=poll.title or "Umfrage",
                    body=(poll.detail or "").strip(),
                    sent=None,
                    url=parse.urljoin(self.base_url, (poll.href or "").lstrip("/"))
                    if poll.href
                    else parse.urljoin(self.base_url, "aktuelles/umfragen"),
                    version=_stable_id(poll.title, poll.detail),
                    attachments=atts,
                    meta={
                        "ende": poll.end.isoformat() if poll.end else None,
                        "abgestimmt": poll.vote.isoformat() if poll.vote else None,
                    },
                )
            )
        return items

    async def _download_item(self, item: PortalItem) -> None:
        for idx, att in enumerate(item.attachments, start=1):
            url = parse.urljoin(self.base_url, att.href.lstrip("/"))
            try:
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        LOGGER.warning("Download %s: HTTP %s", url, resp.status)
                        continue
                    ctype = resp.headers.get("Content-Type", "").split(";")[0]
                    if ctype == "text/html":
                        LOGGER.warning("Download %s lieferte HTML statt Datei", url)
                        continue
                    if (resp.content_length or 0) > MAX_FILE_SIZE:
                        LOGGER.warning("Anhang zu groß, übersprungen: %s", url)
                        continue
                    content = await resp.read()
                    if len(content) > MAX_FILE_SIZE:
                        LOGGER.warning("Anhang zu groß, übersprungen: %s", url)
                        continue
                    fallback = att.name or f"anhang_{idx}"
                    if "." not in fallback[-6:] and ctype == "application/pdf":
                        fallback += ".pdf"
                    item.files.append(
                        PortalFile(
                            name=_filename_from_response(resp, fallback),
                            content=content,
                            content_type=ctype or None,
                        )
                    )
            except (aiohttp.ClientError, TimeoutError) as err:
                LOGGER.warning("Download %s fehlgeschlagen: %s", url, err)


# ----------------------------------------------------------------------
# Stundenplan und Vertretungsplan (reine HTML-Auswertung, gut testbar)
# ----------------------------------------------------------------------
_TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*-\s*(\d{1,2})[.:](\d{2})")
_ENTFALL_RE = re.compile(r"entf[aä]ll|ausfall|f[aä]llt\s+aus|\bfrei\b|unterrichtsfrei", re.I)


_TEST_RE = re.compile(r"^(kLN|KA|StA|Ex|Test|Kurzarbeit|Stegreif)", re.I)


def appointment_kind(classname: str | None, title: str | None = None) -> str:
    """Art eines Portal-Termins laut Legende: 'schulaufgabe', 'test' oder 'schule'."""
    cls = (classname or "").lower()
    if "important" in cls:
        return "schulaufgabe"
    if "warning" in cls:
        return "test"
    if "info" in cls:
        return "schule"
    title = (title or "").strip()
    if re.match(r"^(SA|Schulaufgabe)\b", title):
        return "schulaufgabe"
    if _TEST_RE.match(title):
        return "test"
    return "schule"


def appointment_subject(title: str | None) -> str | None:
    """Fach aus 'SA in Deutsch (Mü)' oder 'kLN in Französisch (8_F_8B_Ab) (Ab)'."""
    if m := re.search(r"\bin\s+([^()]+?)\s*(\(|$)", title or ""):
        return m[1].strip()
    return None


def _lines(tag: Any) -> list[str]:
    return [t.strip() for t in tag.find_all(string=True) if t.strip()]


def parse_timetable(html: str, parser: str = "html.parser") -> list[dict[str, Any]]:
    """Stundenplan der Klasse: eine Zeile je Stunde und Wochentag (1 = Montag)."""
    soup = bs4.BeautifulSoup(html, parser)
    out: list[dict[str, Any]] = []
    for row in soup.select("#asam_content div.table-responsive table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue
        head = _lines(cells[0])
        if not head:
            continue
        number = head[0].rstrip(".").strip()
        start = end = None
        if m := _TIME_RE.search(" ".join(head)):
            start = f"{int(m[1]):02d}:{m[2]}"
            end = f"{int(m[3]):02d}:{m[4]}"
        for weekday, cell in enumerate(cells[1:7], start=1):
            inner = cell.select_one("span span") or cell
            parts = _lines(inner)
            if not parts:
                continue
            subject = parts[0]
            room = parts[1] if len(parts) > 1 else ""
            if not subject.strip(" /"):
                continue
            out.append(
                {
                    "weekday": weekday,
                    "lesson": number,
                    "start": start,
                    "end": end,
                    "subject": subject,
                    "room": room.strip(" /") and room,
                }
            )
    out.sort(key=lambda x: (x["weekday"], _lesson_sort(x["lesson"])))
    return out


def _lesson_sort(value: str) -> tuple[int, str]:
    m = re.match(r"\d+", value or "")
    return (int(m[0]) if m else 99, value or "")


def substitution_kind(entry: dict[str, Any]) -> str:
    """'entfall', 'raum' oder 'vertretung'."""
    text = " ".join(
        str(entry.get(k) or "") for k in ("substitute", "subject", "room", "info")
    )
    if _ENTFALL_RE.search(text) or entry.get("substitute") in ("---", "–", "-") and not entry.get("room"):
        return "entfall"
    info = (entry.get("info") or "").lower()
    if "raum" in info and entry.get("substitute") in ("", None, entry.get("teacher")):
        return "raum"
    return "vertretung"


def parse_substitutions(html: str, parser: str = "html.parser") -> dict[str, Any]:
    """Vertretungsplan: {'available', 'stand', 'days': [{'date', 'entries'}]}."""
    soup = bs4.BeautifulSoup(html, parser)
    center = soup.select_one("#asam_content .main_center")
    result: dict[str, Any] = {"available": center is not None, "stand": None, "days": []}
    if center is None:
        return result
    if m := re.search(r"Stand:?\s*([\d.]+\s*[\d:]*)", center.get_text(" ")):
        result["stand"] = m[1].strip()
    day: dict[str, Any] | None = None
    for tag in center.find_all(["div", "table"], recursive=False):
        if tag.name == "div" and "list" in (tag.get("class") or []):
            if m := re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tag.get_text()):
                iso = f"{m[3]}-{m[2]}-{m[1]}"
                day = next((d for d in result["days"] if d["date"] == iso), None)
                if day is None:
                    day = {"date": iso, "entries": []}
                    result["days"].append(day)
            continue
        if tag.name != "table" or day is None:
            continue
        for row in tag.select("tr"):
            if "vp_plan_head" in (row.get("class") or []):
                continue
            cells = row.find_all("td", recursive=False)
            if len(cells) < 6:
                continue
            old = [
                s.get_text(strip=True)
                for s in cells[3].select("span[style*='line-through']")
            ]
            for span in cells[3].select("span[style*='line-through']"):
                span.decompose()
            entry = {
                "lesson": re.sub(
                    r"\.(?=\s*[-–])", "", cells[0].get_text(strip=True)
                ).removesuffix("."),
                "teacher": cells[1].get_text(strip=True),
                "substitute": cells[2].get_text(strip=True),
                "subject": cells[3].get_text(" ", strip=True),
                "old_subject": " ".join(o for o in old if o) or None,
                "room": cells[4].get_text(strip=True),
                "info": cells[5].get_text(" ", strip=True),
            }
            if entry["old_subject"] == entry["subject"]:
                entry["old_subject"] = None
            entry["kind"] = substitution_kind(entry)
            day["entries"].append(entry)
    return result


_HEADINGS = ("h1", "h2", "h3", "h4", "h5")


def parse_teachers(html: str, parser: str = "html.parser") -> dict[str, str] | None:
    """Stundenplankürzel der Lehrkräfte aus den Schulinformationen.

    Aufbau im Portal: Überschrift "Stundenplankürzel der Lehrkräfte", danach je
    Lehrkraft eine ``div.row`` mit dem Kürzel in ``<b>`` (doppelt, für breite und
    schmale Bildschirme) und dem Namen in ``div.col-md-6``. Gibt ``None`` zurück,
    wenn die Seite keinen solchen Abschnitt hat.
    """
    soup = bs4.BeautifulSoup(html, parser)
    head = next(
        (
            h
            for h in soup.find_all(_HEADINGS)
            if re.search(r"k[uü]e?rzel", h.get_text(), re.I)
            and re.search(r"lehr", h.get_text(), re.I)
        ),
        None,
    )
    if head is None:
        return None
    out: dict[str, str] = {}

    def add(abbr: str, name: str) -> None:
        abbr = re.sub(r"\s+", " ", abbr).strip().rstrip(":")
        name = re.sub(r"\s+", " ", name).strip(" :-–")
        if abbr and name and name != abbr and abbr not in out:
            out[abbr] = name

    # Tabellen-Variante (falls ein Portal die Liste als Tabelle zeigt)
    table = head.find_next("table")
    container = head.find_parent(class_="row") or head.parent
    if container is not None and container.name != "body":
        for row in container.find_next_siblings():
            if row.find(_HEADINGS) or row.name in _HEADINGS:
                break
            bold = row.find("b")
            if bold is None:
                continue
            abbr = bold.get_text()
            value = row.select_one(".col-md-6, .col-md-8, .col-sm-8, .col-xs-8")
            if value is not None:
                name = value.get_text(" ")
            else:
                for b in row.find_all("b"):
                    b.decompose()
                name = row.get_text(" ")
            add(abbr, name)
    if not out and table is not None:
        nxt = table.find_previous(_HEADINGS)
        if nxt is head:
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ") for c in tr.find_all(["td", "th"])]
                if len(cells) >= 2 and not re.search(r"k[uü]rzel", cells[0], re.I):
                    add(cells[0], cells[1])
    return out


async def async_validate(
    session: aiohttp.ClientSession, school: str, username: str, password: str
) -> str:
    """Zugangsdaten prüfen; gibt den Schulnamen zurück."""
    api = SchulPortal(session, school, username, password)
    await api.async_validate_config()
    return (api.school_name or school).strip()


__all__ = [
    "PortalAuthError",
    "PortalConnectionError",
    "PortalChild",
    "PortalItem",
    "PortalResult",
    "SchulPortal",
    "async_validate",
    "appointment_kind",
    "appointment_subject",
    "parse_substitutions",
    "parse_teachers",
    "parse_timetable",
    "school_from_input",
    "pyelternportal",
]
