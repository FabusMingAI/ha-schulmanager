# Changelog

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
