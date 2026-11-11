Component browser checks with fictional pupil data (no live account or portal access):

```sh
cd tests/browser
npm ci
npm test
```

Requires system Chromium (`/usr/bin/chromium`, or set `CHROMIUM_PATH`). Covers desktop and mobile width, keyboard lesson selection in the following week, lesson details, calendar export, dynamic footer, archive/restore services and WebUntis changes without a portal timetable. Screenshots are written to `/tmp/schulmanager-{1280,390}.png`. Home Assistant services and WebSocket responses are mocked; this does not replace a live dashboard test.
