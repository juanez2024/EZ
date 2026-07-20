"""Captura interactiva del endpoint de premios LifeMiles con Chromium.

IMPORTANTE: corré esto en TU máquina (no en un servidor sin red hacia
lifemiles.com). Abre un Chromium visible, vos navegás y hacés la búsqueda
de premios a mano (logueándote si hace falta), y el script guarda todas las
requests/responses que parezcan de disponibilidad en `capture_out.json`.

Instalación (local):
    pip install playwright
    playwright install chromium

Uso:
    python capture_playwright.py
    # se abre Chromium -> logueate -> hacé una búsqueda de premios -> volvé
    # a la terminal y apretá Enter para guardar y cerrar.

No se envía nada a ningún lado: el archivo queda en tu disco. Los headers
sensibles (cookie/authorization) se guardan tal cual porque son necesarios
para reproducir la request; tratá ese archivo como secreto.
"""
from __future__ import annotations

import json

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    raise SystemExit(
        "Falta Playwright. Instalá:  pip install playwright && playwright install chromium"
    )

URL_HINTS = ("availab", "award", "redem", "search", "flight", "shop", "offers")
CAPTURE_FILE = "capture_out.json"


def looks_relevant(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in URL_HINTS)


def main() -> None:
    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        def on_response(response):
            req = response.request
            if req.resource_type not in ("xhr", "fetch"):
                return
            if not looks_relevant(req.url):
                return
            try:
                body = response.text()
            except Exception:
                body = None
            captured.append({
                "url": req.url,
                "method": req.method,
                "status": response.status,
                "request_headers": dict(req.headers),
                "post_data": req.post_data,
                "response_body": body,
            })
            print(f"  [capturado] {req.method} {req.url[:90]}")

        page.on("response", on_response)

        page.goto("https://www.lifemiles.com/", wait_until="domcontentloaded")
        print(
            "\nChromium abierto. Logueate y hacé una búsqueda de PREMIOS "
            "(redención de millas).\nCuando veas resultados, volvé acá y apretá Enter."
        )
        input()

        with open(CAPTURE_FILE, "w", encoding="utf-8") as fh:
            json.dump(captured, fh, indent=2, ensure_ascii=False)
        print(f"\nGuardadas {len(captured)} requests en {CAPTURE_FILE}")
        browser.close()


if __name__ == "__main__":
    main()
