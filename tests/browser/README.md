Component browser checks with fictional pupil data (no live account or portal access):

```sh
cd tests/browser
npm ci
npm test
```

Requires system Chromium (`/usr/bin/chromium`, or set `CHROMIUM_PATH`). Covers desktop and mobile width, keyboard lesson selection in the following week, lesson details, calendar export, dynamic footer, archive/restore services and WebUntis changes without a portal timetable. Screenshots are written to `/tmp/schulmanager-{1280,390}.png`. Home Assistant services and WebSocket responses are mocked; this does not replace a live dashboard test.

Notification-link checks additionally cover delayed cold loads, child selection, warm navigation to tasks, missing items, duplicate cards and preserving unrelated URL parameters.

Outage checks retain timetable/agenda content while showing connection, partial-response and authentication warnings, known/unknown data age, and recovery.
