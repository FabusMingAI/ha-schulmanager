# README screenshots

Render the repository's actual custom cards with fictional data from `demo.html`.
The demo has no live Home Assistant, school portal or AI connection. It uses a
fixed 5 October 2026 clock so dates, relative labels and fetch times agree.
`dashboard.png` combines the actual appointment, timetable and footer cards;
it is a card preview without Home Assistant navigation chrome. Dialog captures
expand the scroll area vertically to show their complete contents.

From the repository root, in a Python virtual environment:

```sh
python -m pip install playwright
python -m playwright install chromium
python docs/screenshots/make_screenshots.py
```

For an existing Chromium installation, use `--chromium /usr/bin/chromium`
or set `CHROMIUM_PATH`. Ensure an emoji font such as Noto Color Emoji is
installed to avoid missing symbols. Alternatively, pass `--font-dir /path/to/fonts`
containing `NotoColorEmoji.ttf` and, optionally, `roboto-latin-400-normal.woff2`
and `roboto-latin-500-normal.woff2`. These fonts are embedded only while rendering;
they are not committed. `--theme light` selects the light theme; dark is the default.

The script regenerates every screenshot referenced by both READMEs, waits for
card data and fonts, and fails on JavaScript page errors. Review each image before
committing. The isolated demo is also available interactively, for example:

- `demo.html?card=dashboard&w=1120&theme=dark`
- `demo.html?card=stundenplan&view=week&theme=dark`
- `demo.html?card=item&item=blackboard&theme=dark`

The demo's version should track the integration manifest when preparing releases.
Screenshots describe the checked-out code; the READMEs distinguish unreleased
features from the published release.
