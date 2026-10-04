# Changelog

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
