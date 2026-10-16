# Changelog

## Unreleased – WebUntis (draft #26)

- Optional per-child calendar assignment under **Configure → WebUntis calendar**. Users install and configure WebUntis themselves (JSON descriptions, cancelled lessons and room changes enabled). No selection means no WebUntis queries. / Optionale Zuordnung eines vorhandenen WebUntis-Kalenders pro Kind; ohne Auswahl bleibt alles wie bisher.
- Selected calendars are read for the next 14 days and combined with the Eltern-Portal substitution plan. Changes reach sensors, calendar, dashboard and substitution notifications; exact duplicates are suppressed. Failed/unavailable sources retain their last data and appear in diagnostics; successful empty results remove obsolete entries. / Beide Quellen werden zusammengeführt; Fehler löschen keine bekannten Daten.

## 0.14.1 – 2026-10-12 (bridge release)

- **Existing setups are now taken over automatically.** With 0.14.0, HACS installed the renamed integration next to the old folder, but Home Assistant kept running the old 0.13 code and nothing told users to click *Take over* – they stayed on 0.13 without noticing. 0.14.1 is released once more under the old domain `schulmanager`: HACS installs it over 0.13 as a normal update, it installs *Eltern Portal Manager Bavaria*, starts the takeover by itself and asks for one more restart. Entries of Schulmanager Online are never touched. If the automatic takeover fails, a repair notice explains the manual way. / **Bestehende Einrichtungen werden jetzt automatisch übernommen.** Mit 0.14.0 lief nach dem Update unbemerkt weiter 0.13. 0.14.1 kommt noch einmal unter der alten Domain, installiert Eltern Portal Manager Bavaria und übernimmt die Einrichtung selbst; danach einmal neu starten.
- Adding *Schulmanager* during this period installs *Eltern Portal Manager Bavaria* and points to it. / Wer jetzt „Schulmanager“ hinzufügt, bekommt Eltern Portal Manager Bavaria installiert und den Hinweis darauf.
- A leftover `custom_components/schulmanager` of this project is removed at startup once no old setup is left, so it never stands in the way of Schulmanager Online. / Ein übrig gebliebener Ordner `custom_components/schulmanager` dieses Projekts wird beim Start entfernt.
- **Note for users of Schulmanager Online:** if you already took over by hand with 0.14.0 and installed Schulmanager Online afterwards, skip 0.14.1 and wait for 0.14.2 (same folder). / **Hinweis für Nutzer von Schulmanager Online:** wer schon von Hand übernommen und danach Schulmanager Online installiert hat, überspringt 0.14.1.

## 0.14.0 – 2026-10-11

- **Renamed: Schulmanager is now "Eltern Portal Manager Bavaria"** (domain `eltern_portal_schulmanager`). The old domain `schulmanager` is also used by [Schulmanager Online](https://github.com/MrIcemanLE/Schulmanager-homeassistant), so the two could not be installed side by side; now they can. Closes #18. / **Umbenannt: Der Schulmanager heißt jetzt „Eltern Portal Manager Bavaria“** (Domain `eltern_portal_schulmanager`) und lässt sich neben Schulmanager Online installieren.
- **Taking over an existing setup:** update in HACS, restart, then *Settings → Devices & services → Add integration → Eltern Portal Manager Bavaria* and click **Take over** – credentials, settings, tasks, messages, archive, AI summaries, stored files (moved to `Media › eltern_portal_schulmanager`), entity IDs and history are kept; dashboards are switched to the new card types; the old entry, dashboard resource and folder `custom_components/schulmanager` (only if it is ours) are removed. Restart once more afterwards. / **Übernahme:** in HACS aktualisieren, neu starten, Integration „Eltern Portal Manager Bavaria“ hinzufügen und **Übernehmen** klicken – alles bleibt erhalten, danach noch einmal neu starten.
- **Breaking – automations and scripts:** actions are now `eltern_portal_schulmanager.*`, events `eltern_portal_schulmanager_new_item` / `_task_reminder` / `_substitution`, cards `custom:eltern-portal-schulmanager-*`. Automations and scripts are not changed automatically; a **repair notice** ("Automations still use the old Schulmanager names", *Settings → Repairs*) lists every automation and script that still uses an old name and disappears once they are changed. / **Achtung Automationen und Skripte:** neue Namen für Aktionen, Events und Karten; ein **Reparatur-Hinweis** unter *Einstellungen → Reparaturen* listet alles auf, was noch alte Namen nutzt.
- New installations name the diagnostics sensor `sensor.eltern_portal_manager_bavaria_letzter_abruf`; taken-over setups keep `sensor.schulmanager_letzter_abruf`. Buttons in push notifications sent before the update keep working; PDF and calendar links in them no longer open. / Neuinstallationen: neuer Name des Diagnose-Sensors; übernommene Einrichtungen behalten den alten. Buttons alter Push-Nachrichten funktionieren weiter, Links darin nicht mehr.
- Fix: **substitution plan empty at some schools.** Eltern-Portal shows the plan with 5 columns (no subject) at some schools and with 6 columns at others; only the 6-column layout was read. Columns are now taken from the header row; without a subject column the subject comes from the timetable when it is unambiguous. `pyelternportal` updated to 0.0.27. Closes #19. / Behoben: **Vertretungsplan an manchen Schulen leer** – jetzt werden beide Layouts (5 und 6 Spalten) gelesen; `pyelternportal` 0.0.27.

## 0.13.0 – 2026-10-10

- New: **📅 add a single entry to your own calendar** (iPhone, Android, Outlook). In "Termine & Fristen", in the day view of the timetable (exams, tests, substitutions) and in the task dialog of deadlines there is **📅 In Kalender eintragen** (signed `.ics` file, valid 24 h) and **Google Kalender**. You decide which entries go into your calendar; adding one again updates it instead of creating a duplicate. Closes #12 and #11. / Neu: Einzelnen Termin per `.ics` oder Google Kalender in den eigenen Kalender übernehmen.
- New: **change a task's status by tapping its icon** – circle or ⏳ → done, green check → open again; only tapping the text opens the details. Done tasks are no longer struck through. Closes #10. / Neu: Status per Antippen des Icons umschalten, kein Durchstreichen mehr.
- New: **"Alle als erledigt markieren"** below the messages (with confirmation), next to "Alle als gelesen markieren" – the old link only marked messages as read, so nothing moved to "Erledigt". `schulmanager.update_item` now accepts `child` instead of `item_id` for all messages. / Neu: Alle Mitteilungen auf einmal als erledigt markieren.
- Fix: **entries in "Termine & Fristen" can be expanded and collapsed by tapping**, including 📅 appointments from messages, which stayed open and could not be closed on phones. All entries behave the same now; the expanded state survives card updates, the hover tooltip only appears with a mouse. Closes #15. / Behoben: Termine aus Mitteilungen ließen sich am Handy nicht auf- und zuklappen.
- Fix: **messages no longer become unread again after an update** when they only look different (spaces/line breaks) or when most known messages change at once (e.g. different rendering in the portal); real edits by a teacher still mark them unread and are logged. Refs #14. / Behoben: Nach einem Update waren alle Mitteilungen wieder ungelesen.

## 0.12.1 – 2026-10-08

- Fix: **the `schulmanager_new_item` event was never fired**, and the first new message with a push stopped the background analysis. Since 0.5.3 the event call in `_notify_item()` passed three constants instead of one event name, which raised a `TypeError` after the push had been sent. As a result there was no voice announcement for urgent messages, no event for automations, and all further messages stayed unanalysed until Home Assistant was restarted. The event is fired correctly again, and an error in push/event/announcement can no longer stop the analysis worker. / Behoben: Das Event `schulmanager_new_item` kam nie an, und die erste neue Mitteilung mit Push hat die Auswertung angehalten (keine Sprachansage, keine weiteren Auswertungen bis zum Neustart).

## 0.12.0 – 2026-10-07

- New: **week navigation in the timetable's week view** – ‹ / › go one week back or forward, "Heute" jumps back; the header shows calendar week, dates and "diese/nächste Woche". The week view now always shows Monday to Friday of one calendar week (on weekends the next week). Exams and tests of the shown week are marked; substitutions are only available from today on. / Neu: In der Wochenansicht des Stundenplans wochenweise vor- und zurückblättern, mit KW und „Heute“.
- New: the **legend** in "Termine & Fristen" and in the week view is **collapsible and collapsed by default**; the open/closed state is kept while the card refreshes. / Neu: Legende ein- und ausklappbar, standardmäßig eingeklappt.
- New: **teacher names instead of bare abbreviations**. Schulmanager reads "Stundenplankürzel der Lehrkräfte" (*Service → Schulinformationen*) per school once a day and shows the names in the timetable, substitution plan, calendar, hover texts and push notifications. New setting in *Termine & Klassen*: abbreviation and name (default, e.g. "Mü (Maria Müller)"), name only or abbreviation only. Unknown abbreviations stay as they are; names are not sent to the AI service. New attributes `lehrkraft_name` and `vertretung_name` in `sensor.schule_<child>_vertretungen`. Closes #9. / Neu: Namen der Lehrkräfte statt nur Kürzel, mit Einstellung nur Kürzel / Kürzel + Name / nur Name.
- Fix: **"Server disconnected" on every fetch** – one of the two portals regularly failed. All schools shared Home Assistant's connection pool, and idle keep-alive connections closed by the portal were reused on the next fetch. Every fetch now uses its own fresh connection per school, and a dropped connection is retried once after 5 seconds. Closes #8. / Behoben: Bei jedem Abruf fiel ein Portal mit „Server disconnected“ aus; jetzt eigene Verbindung je Abruf und ein Wiederholversuch.

## 0.11.1 – 2026-10-07

- Fix: **substitutions no longer appear twice** in "Termine & Fristen", the calendar and the timetable. For split classes Eltern-Portal lists one row per group/teacher that differs only in the teacher; these rows are now merged into one entry and all teachers are shown in the hover text ("Lehrkräfte laut Plan: …"). Calendar UIDs are unique again; no new push for the merged rows. / Behoben: Vertretungen erschienen bei geteilten Klassen doppelt; gleiche Zeilen werden zusammengefasst, alle Lehrkräfte stehen im Hover-Text.

## 0.11.0 – 2026-10-06

- New: **archive in "Termine & Fristen"**. Every entry gets a **📦** button (on hover, always visible on phones); archived entries move to the new **📦 Archiv** view right of "Alle", where **↩️** brings them back. Works on the overview and on each child's tab, stored in Home Assistant (same on all devices). Deadlines stay open tasks with reminders; the calendar is unchanged. New actions `schulmanager.archive_event` and `schulmanager.unarchive_event`. Closes #6. / Neu: Archiv für Termine & Fristen mit Archivieren und Reaktivieren, auf der Übersicht und in den Kinder-Reitern.

## 0.10.1 – 2026-10-05

- Removed: the daily overview per child from 0.10.0 (new messages, deadlines, timetable changes … above the cards) is gone again. The header keeps the last fetch, the version with its GitHub link and "⚙️ Einstellungen"; the card is now called `custom:schulmanager-header` (the old name `custom:schulmanager-heute` still works). / Entfernt: der Tagesüberblick je Kind aus 0.10.0. Die Kopfzeile mit letztem Abruf, Version und Einstellungen bleibt.

## 0.10.0 – 2026-10-05

- New: **"Today" header** on the overview of the "Schule" dashboard (card `custom:schulmanager-heute`): per child the new messages, deadlines until the next school day, new tasks, timetable changes for today and the next school day, exams/tests and appointments – each entry opens its message, task or the list of changes. Children with nothing new show "✓ Nichts Neues". / Neu: Tagesüberblick je Kind oben auf der Übersicht, alle Einträge anklickbar.
- New: the header shows, right-aligned next to "⚙️ Einstellungen", **when Eltern-Portal was last fetched** (with ↻ to fetch now and a warning on fetch errors) and the **installed version** with a link to its release on GitHub. / Neu: letzter Abruf und Version mit Link zu GitHub in der Kopfzeile.
- Fix: text in the message and task dialogs can be **selected and copied** again. The dialog is no longer redrawn while text is selected or when nothing changed, releasing the mouse outside the dialog no longer closes it, and new "📋 kopieren" buttons copy the summary or the text (also without HTTPS). / Behoben: Text in den Dialogen lässt sich wieder markieren und kopieren; neue Kopieren-Knöpfe.

## 0.9.1 – 2026-10-04

- Fix: the settings dialog (sections, new in 0.9.0) showed empty fields instead of the stored settings, so saving it could overwrite them. Stored values are shown again; sections that are not sent keep their values. / Behoben: Das Einstellungsfenster zeigte in 0.9.0 leere Felder statt der gespeicherten Einstellungen – Speichern hätte sie überschrieben.

## 0.9.0 – 2026-10-04

- New: the **date a message appeared in Eltern-Portal** is shown in front of every task title – in the card lists, the message and task dialogs (with year), the morning summary and the to-do lists. Own tasks show the day they were added. Display only; stored titles stay unchanged. Closes #5. / Neu: Erscheinungsdatum im Portal vor jedem Aufgabentitel, in Dialogen, Tagesübersicht und To-do-Listen.
- New: **settings in collapsible sections** (AI & languages, notifications, appointments & classes open; voice announcements, fetching, dashboard collapsed) with a short explanation for every field. Stored options are unchanged. Closes #4. / Neu: Einstellungen in einklappbaren Abschnitten mit Erklärtexten.
- New: **translation progress** – a progress line in the card, a Home Assistant notification on start and finish (from 5 translations) and the sensor attribute `uebersetzung_ausstehend`. Closes #3. / Neu: Fortschritt der Übersetzung in Karte, Benachrichtigung und Sensor.
- Fix: a failed summary translation is retried after 6 hours, up to 3 attempts; changing the language selection starts over. Closes #2. / Behoben: Fehlgeschlagene Übersetzungen werden erneut versucht.

## 0.8.1 – 2026-10-04

- AI summary: missing languages are added by translating only the existing summary in the background – for messages analysed before 0.8.0 and whenever a language is added in the settings. Tasks, appointments, status and comments are never touched (a full re-analysis could reword task titles and create duplicates). / KI-Zusammenfassung: Fehlende Sprachen werden im Hintergrund nur übersetzt – ohne Aufgaben neu zu erzeugen.

## 0.8.0 – 2026-10-04

- New: messages have a status **open / in progress / done** like tasks (dialog in the card, action `schulmanager.update_item`). Done messages count as read and move to the "Erledigt" tab. / Neu: Mitteilungen mit Status Offen / In Arbeit / Erledigt; erledigte wandern in den Reiter „Erledigt“.
- New: PDF **full screen** ("Vollbild") and **print** ("Drucken") buttons in the message and task dialogs. / Neu: PDF im Vollbild und Drucken.
- New: **AI summary in several languages** – choose up to 4 of German, English, Spanish and Catalan in the settings (default German and English); the card shows one tab per language. / Neu: KI-Zusammenfassung in bis zu 4 Sprachen mit Reitern.
- New: setting **"Only appointments of the child's class"** (default on) hides portal and AI appointments that name only other classes or grades, e.g. "Schullandheim 5b+5c" or "Jgst. 10". The AI is also told to skip them. / Neu: Termine anderer Klassen werden ausgeblendet.
- Dashboard "Schule": "⚙️ Einstellungen" link to the integration settings in the overview header. / Link zu den Einstellungen auf der Übersicht.

## 0.7.3 – 2026-10-04

- Dashboard "Schule": all timetables (overview, child tabs, single page) start in the week view. / Alle Stundenpläne im Dashboard „Schule“ starten in der Wochenansicht.
- README: images left-aligned. / README: Bilder linksbündig.

## 0.7.2 – 2026-10-04

- Timetable card: the week view no longer needs horizontal scrolling in narrow cards (half a column on the *Overview* tab, child tabs, phones). Narrow cards use short subject names ("Mathe", "Engl.", "Reli/Eth") and short labels ("SA", "Vertr."). / Stundenplan: Wochenansicht ohne Querscrollen in schmalen Karten, mit abgekürzten Fächern.
- Timetable card: new option `view: week` to start in the week view. The *Overview* tab of the "Schule" dashboard uses it for both timetables. / Neue Option `view: week`; die Übersicht startet in der Wochenansicht.

## 0.7.1 – 2026-10-04

- Dashboard "Schule", tab *Overview*: the right-hand "Schulmanager" panel (last fetch, refresh, send summary) is replaced by **each child's timetable** with substitutions, exams and tests. Refresh and summary stay available as actions `schulmanager.refresh` / `schulmanager.send_digest`, and the last fetch as `sensor.schulmanager_letzter_abruf`. The dashboard updates by itself after the restart unless it was changed by hand (then: action `schulmanager.rebuild_dashboard`). / Dashboard „Schule“, Reiter *Übersicht*: Statt der Karte „Schulmanager“ steht rechts jetzt der **Stundenplan je Kind** mit Vertretungen, Schulaufgaben und Tests. Abrufen und Tagesübersicht bleiben als Aktionen erhalten.
- Docs: new screenshots with made-up demo data (timetable day/week view, appointments, task details), reproducible via `docs/screenshots/`. / Doku: neue Screenshots mit Demo-Daten.

## 0.7.0 – 2026-10-04

- New: portal appointments are classified like in Eltern-Portal – **exams** (*Schulaufgabe*, 📝), **tests** (*Test / Kurzarbeit / kl. Leistungsnachweis / Stegreifaufgabe*, ✏️) and **school appointments** (🏫). By default only exams and tests are shown; school appointments can be switched on under Configure → Settings → "Portal appointments to show". / Neu: Portal-Termine nach Art wie im Eltern-Portal; standardmäßig nur Schulaufgaben und Tests, Termine der Schule per Einstellung.
- New: exams and tests are highlighted in the timetable card (weekday buttons, day box, badge on the matching subject, week view) and tomorrow's exams/tests appear in the morning summary. / Neu: Schulaufgaben und Tests im Stundenplan hervorgehoben, morgige in der Tagesübersicht.

## 0.6.1 – 2026-10-04

- Fix: if a school does not offer the timetable, substitution plan or sick notes page and the portal drops the connection there, only that section is skipped – the rest of the portal (letters, messages, tasks) is still fetched. In 0.6.0 the whole fetch for that school was aborted. / Behoben: Bietet eine Schule Stundenplan, Vertretungsplan oder Krankmeldungen nicht an und trennt das Portal dort die Verbindung, wird nur dieser Bereich übersprungen. In 0.6.0 brach der ganze Abruf dieser Schule ab.

## 0.6.0 – 2026-10-04

- New: **sick notes** (*Krankmeldungen*) from Eltern-Portal (read only). Sensor `sensor.schule_<child>_krankmeldungen` with school days off sick in the current school year, sick notes in the calendar and in the appointments card (🤒, explained in the legend). An empty portal response keeps known sick notes. Closes #1. / Neu: **Krankmeldungen** aus dem Eltern-Portal (nur lesen) – Sensor mit Krankheitstagen im Schuljahr, Einträge im Kalender und in der Termin-Karte (🤒, in der Legende erklärt).

## 0.5.4 – 2026-10-04

- Timetable card: changes are written in plain words with full subject names (e.g. "Englisch entfällt", "Raumänderung: Raum N12"). README (English and German) updated with the new cards and screenshots. / Stundenplan-Karte: Änderungen in Klartext mit ausgeschriebenen Fächern; README (deutsch und englisch) mit den neuen Karten und Bildern.

## 0.5.3 – 2026-10-04

- More subject abbreviations (iF, iL, PhÜ, CÜ). / Weitere Fächerkürzel.

## 0.5.2 – 2026-10-04

- Timetable card shows full subject names in bold (e.g. "Biologie", "Mathematik (Intensivierung)", "Sport") instead of abbreviations. / Stundenplan zeigt Fächer ausgeschrieben statt Kürzeln.

## 0.5.1 – 2026-10-04

- Timetable card: lesson times no longer wrap. / Stundenplan-Karte: Uhrzeiten brechen nicht mehr um.

## 0.5.0 – 2026-10-04

- New: **timetable and substitution plan** from the Eltern-Portal. Sensors `sensor.schule_<child>_stundenplan` and `sensor.schule_<child>_vertretungen`, substitutions and cancelled lessons in the calendar (with lesson times) and in the morning summary, push notification when a new change appears. / Neu: **Stundenplan und Vertretungsplan** – Sensoren, Einträge im Kalender und in der Tagesübersicht, Push bei neuen Vertretungen oder Ausfällen.
- New cards `custom:schulmanager-termine` (appointments and deadlines; hovering shows the AI summary, legend of all categories at the bottom) and `custom:schulmanager-stundenplan` (day and week view with changes highlighted). / Neue Karten „Termine“ (Kurzbeschreibung beim Überfahren, Legende) und „Stundenplan“.
- Dashboard: the overview's Schulmanager card no longer lists one row per child; child tabs now show timetable and appointments. / Dashboard: keine Kinder-Zeilen mehr in der Schulmanager-Karte der Übersicht; Kinder-Reiter mit Stundenplan und Terminen.

## 0.4.0 – 2026-10-03

- New: the integration creates and maintains the **"Schule" dashboard**. Default layout on phones: tabs **Overview** (calendar + Schulmanager status with links) and **one tab per child**. Choose *Tabs*, *Single page* or *Do not manage* under Configure → Settings. / Neu: Dashboard „Schule“ wird automatisch angelegt – Reiter „Übersicht“ und je Kind, einstellbar unter Konfigurieren → Einstellungen.
- Dashboards you edited by hand are never overwritten silently; use the action `schulmanager.rebuild_dashboard` or pick a layout in the settings to regenerate. / Eigene Änderungen bleiben erhalten.

## 0.3.1 – 2026-10-03

- Fix: dashboard card sometimes showed "Konfigurationsfehler" (configuration error) when a client opened the dashboard while Home Assistant was still starting. The card is now published to `/local/schulmanager/` and registered as a dashboard resource, so it is available from the first second. / Behoben: Die Karte zeigte manchmal „Konfigurationsfehler“, wenn ein Gerät das Dashboard öffnete, während Home Assistant noch startete.
- The card retries automatically until the integration is ready. / Die Karte lädt die Daten automatisch nach, sobald der Schulmanager bereit ist.

## 0.3.0 – 2026-10-03

First public release. / Erste öffentliche Version.

- Eltern-Portal: parent letters, teacher messages, notice board, surveys and exam dates for several schools and children
- AI analysis via Home Assistant AI Task with rule-based fallback
- Tasks with status open / in progress / done and comments; to-do list, calendar, sensors, traffic light per child
- Push reminders with actions, daily summary, voice announcements
- Dashboard card `custom:schulmanager-card` with task and message details, PDF viewer and a mobile-friendly dialog
- Own brand icon (Home Assistant 2026.3+)
- English and German configuration dialogs
