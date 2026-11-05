Component browser checks with synthetic Mireia data (no live account or portal access):

```sh
cd tests/browser
npm ci
npm test
```

Requires system Chromium (`/usr/bin/chromium`, or set `CHROMIUM_PATH`). Covers desktop and mobile width, keyboard lesson selection in the following week, lesson details, calendar export, dynamic footer and archive/restore services. Screenshots are written to `/tmp/schulmanager-{1280,390}.png`. Home Assistant services and WebSocket responses are mocked; this does not replace a live dashboard test.
