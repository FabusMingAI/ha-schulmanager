"""Screenshots der Karten von „Eltern Portal Manager Bavaria“ mit Demo-Daten erzeugen (für README.md / README.de.md).

Benötigt Playwright mit Chromium:
    pip install playwright && playwright install chromium
Aufruf (aus dem Repo-Wurzelverzeichnis):
    python docs/screenshots/make_screenshots.py [--font-dir PFAD_ZU_ROBOTO_WOFF2]

Alle Daten stammen aus docs/screenshots/demo.html und sind erfunden.
"""

from __future__ import annotations

import argparse
import base64
import os
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "images"

SHOTS = [
    ("dashboard.png", "dashboard", 1120, "none"),
    # (Dateiname, Karte, Breite, Aktion)
    ("stundenplan.png", "stundenplan", 380, "day"),
    ("stundenplan-woche.png", "stundenplan", 700, "week"),
    ("termine.png", "termine", 400, "expand"),
    ("task-dialog.png", "task", 390, "dialog"),
    ("item-dialog.png", "item", 390, "dialog"),
    ("footer.png", "header", 700, "none"),
]


def font_css(font_dir: Path | None) -> str:
    if not font_dir:
        return ""
    css = ""
    for weight in (400, 500):
        f = font_dir / f"roboto-latin-{weight}-normal.woff2"
        if f.exists():
            data = base64.b64encode(f.read_bytes()).decode()
            css += f"@font-face{{font-family:Roboto;font-weight:{weight};src:url(data:font/woff2;base64,{data}) format('woff2')}}"
    emoji = font_dir / "NotoColorEmoji.ttf"
    if emoji.exists():
        data = base64.b64encode(emoji.read_bytes()).decode()
        css += f"@font-face{{font-family:'Noto Color Emoji';src:url(data:font/ttf;base64,{data}) format('truetype')}}"
    return css


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-dir", type=Path)
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--only", nargs="+", choices=[shot[0] for shot in SHOTS], help="Regenerate selected images only")
    ap.add_argument("--chromium", default=os.environ.get("CHROMIUM_PATH"), help="Optional system Chromium executable")
    args = ap.parse_args()
    css = font_css(args.font_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.chromium, args=["--lang=de-DE"])
        for name, card, width, action in SHOTS:
            if args.only and name not in args.only:
                continue
            page = browser.new_page(locale="de-DE", timezone_id="Europe/Berlin", device_scale_factor=2, viewport={"width": width + 32, "height": 2200})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.clock.set_fixed_time(datetime(2026, 10, 5, 6, 15, tzinfo=timezone.utc))
            page.goto(f"{(HERE / 'demo.html').as_uri()}?card={card}&w={width}&theme={args.theme}")
            if css:
                page.add_style_tag(content=css)
            if action == "dialog":  # Dialog füllt das Fenster wie am Handy
                page.set_viewport_size({"width": width, "height": 844})
            if card == "dashboard":
                page.locator("eltern-portal-schulmanager-header").get_by_role("button", name="Portale jetzt abrufen").wait_for()
                page.locator("eltern-portal-schulmanager-stundenplan [data-lesson]").first.wait_for()
                page.evaluate("document.fonts.ready")
                assert not errors, errors
                page.locator("#wrap").screenshot(path=str(OUT / name))
                print("geschrieben:", OUT / name)
                page.close()
                continue
            card_el = page.locator("eltern-portal-schulmanager-card" if card in ("task", "item") else f"eltern-portal-schulmanager-{card}")
            card_el.locator("ha-card").wait_for()
            page.wait_for_function("() => !window.cardEl.shadowRoot.textContent.includes('Lade')")
            if action == "day":
                card_el.locator("[data-week]").click()
                card_el.locator('[data-date="2026-10-07"][data-lesson="3"]').click()
                card_el.locator(".lesson-selected").wait_for()
            elif action == "week":
                card_el.locator("[data-week]").click()
            elif action == "expand":
                card_el.locator('[data-ev="anna:e5"]').click()
                card_el.get_by_role("link", name="Google Kalender").wait_for()
            elif action == "dialog":
                page.evaluate("window.cardEl._openItem('i9')" if card == "item" else "window.cardEl._openTask('t9')")
                card_el.locator(".ov").wait_for()
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            assert not errors, errors
            if action == "dialog":
                dialog = card_el.locator(".ov .dlg")
                card_el.locator(".ov").evaluate("el => { el.style.position='absolute'; el.style.alignItems='start'; }")
                dialog.evaluate("el => { el.style.maxHeight='none'; el.style.height='auto'; el.style.overflow='visible'; }")
                dialog.locator(".dh, .df").evaluate_all("els => els.forEach(el => el.style.position='static')")
                dialog.screenshot(path=str(OUT / name))
                print("geschrieben:", OUT / name)
                page.close()
                continue
            box = page.locator("#wrap").bounding_box()
            clip = {"x": box["x"] - 8, "y": box["y"] - 8, "width": box["width"] + 16, "height": box["height"] + 16}
            page.screenshot(path=str(OUT / name), clip=clip)
            print("geschrieben:", OUT / name)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
