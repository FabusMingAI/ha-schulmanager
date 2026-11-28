Component browser checks with fictional pupil data (no live account or portal access):

```sh
cd tests/browser
npm ci
npm test
```

Requires system Chromium (`/usr/bin/chromium`, or set `CHROMIUM_PATH`). Covers desktop and mobile width, keyboard lesson selection in the following week, lesson details, calendar export, dynamic footer, archive/restore services and WebUntis changes without a portal timetable. Screenshots are written to `/tmp/schulmanager-{1280,390}.png`. Home Assistant services and WebSocket responses are mocked; this does not replace a live dashboard test.

Notification-link checks additionally cover delayed cold loads, child selection, warm navigation to tasks, missing items, duplicate cards and preserving unrelated URL parameters.

Outage checks retain timetable/agenda content while showing connection, partial-response and authentication warnings, known/unknown data age, and recovery.

Timetable navigation checks cover start/end times and missing end times, returning from lessons and appointments in a different week, restored keyboard focus and scroll position, sticky return-button visibility, and no horizontal overflow at desktop/mobile widths. Scroll restoration is checked for both document scrolling and a simulated Home Assistant dashboard scroll container inside a shadow root.

Break checks cover 5/15/45-minute gaps, missing/invalid/overlapping/adjacent times, holidays, hidden lessons, appointments during breaks and after school, theme adaptation, and no horizontal overflow on desktop and mobile.

Schedule checks cover relevance confirmation: unconfirmed offers stay outside the
week grid, yes/no answers call the appropriate service, and hiding one offer does
not confirm another. Break checks also cover Monday–Thursday shared cells when
Friday school ends earlier and appointments splitting a shared range.
