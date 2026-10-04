"""Screenshots der Schulmanager-Karten mit Demo-Daten erzeugen (für README.md / README.de.md).

Benötigt Playwright mit Chromium:
    pip install playwright && playwright install chromium
Aufruf (aus dem Repo-Wurzelverzeichnis):
    python docs/screenshots/make_screenshots.py [--font-dir PFAD_ZU_ROBOTO_WOFF2]

Alle Daten stammen aus docs/screenshots/demo.html und sind erfunden.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "images"

SHOTS = [
    # (Dateiname, Karte, Breite, Aktion)
    ("stundenplan.png", "stundenplan", 380, "day"),
    ("stundenplan-woche.png", "stundenplan", 640, "week"),
    ("termine.png", "termine", 400, "hover"),
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
    return css


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font-dir", type=Path)
    ap.add_argument("--theme", default="dark")
    args = ap.parse_args()
    css = font_css(args.font_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, card, width, action in SHOTS:
            page = browser.new_page(device_scale_factor=2, viewport={"width": width + 120, "height": 1400})
            page.goto(f"{(HERE / 'demo.html').as_uri()}?card={card}&w={width}&theme={args.theme}")
            if css:
                page.add_style_tag(content=css)
            card_el = page.locator(f"schulmanager-{card}")
            card_el.locator("ha-card").wait_for()
            page.wait_for_function("() => !window.cardEl.shadowRoot.textContent.includes('Lade')")
            if action == "day":
                card_el.locator('[data-day="2026-10-07"]').click()
            elif action == "week":
                card_el.locator("[data-week]").click()
            elif action == "hover":
                card_el.locator('[data-ev="anna:e5"]').hover()
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            box = page.locator("#wrap").bounding_box()
            clip = {"x": box["x"] - 8, "y": box["y"] - 8, "width": box["width"] + 16, "height": box["height"] + 16}
            if action == "hover":  # Tooltip darf über die Karte hinausragen
                tip = card_el.locator(".tip").bounding_box()
                if tip:
                    right = max(clip["x"] + clip["width"], tip["x"] + tip["width"] + 8)
                    bottom = max(clip["y"] + clip["height"], tip["y"] + tip["height"] + 8)
                    clip["width"], clip["height"] = right - clip["x"], bottom - clip["y"]
            page.screenshot(path=str(OUT / name), clip=clip)
            print("geschrieben:", OUT / name)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
