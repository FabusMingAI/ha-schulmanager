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
they are not committed. On Linux, the generator also creates a temporary
Fontconfig configuration/cache so small emoji in shadow-root text use the same
font. It leaves the system font configuration unchanged. `--theme light` selects the light theme; dark is the default.

The script regenerates every screenshot referenced by both READMEs, waits for
card data and fonts, and fails on JavaScript page errors. Review each image before
committing. The isolated demo is also available interactively, for example:

- `demo.html?card=dashboard&w=1120&theme=dark`
- `demo.html?card=stundenplan&view=week&theme=dark`
- `demo.html?card=item&item=blackboard&theme=dark`

The generator reads the displayed version from the integration manifest. The
interactive demo has a fallback version that should track releases.
Screenshots describe the checked-out code; the READMEs distinguish unreleased
features from the published release.

The v0.15.5 examples show 20/25-minute shared breaks and a 5-minute break
shared by Monday–Thursday, an evening appointment in the week grid, and a
separate relevance-confirmation image (`stundenplan-relevanz.png`). Use
`demo.html?card=stundenplan&pending=1&theme=dark` to try the yes/no controls
with fictional offers. The relevance image crops the card above the day buttons;
it does not alter or simulate the runtime card layout.
