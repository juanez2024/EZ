"""Convierte un HAR de Chrome DevTools en la config del cliente `live`.

Cómo obtener el HAR (en TU máquina, no en el servidor):
  1. Chrome -> lifemiles.com -> logueate y hacé una búsqueda de premios.
  2. F12 -> pestaña Network -> hacé la búsqueda de nuevo con Network abierto.
  3. Click derecho en la lista -> "Save all as HAR with content".
  4. Corré:  python har_to_config.py lifemiles.har

El script busca la request que devuelve la disponibilidad de premios,
imprime URL / método / headers / body, y sugiere qué poner en `.env` y
cómo mapear la respuesta en `app/client.py`.

NO se envía nada a ningún lado: todo el análisis es local. Los headers
sensibles (cookie, authorization) se muestran ENMASCARADOS.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

# Pistas de que una request es la búsqueda de disponibilidad de premios.
URL_HINTS = ("availab", "award", "redue", "redem", "search", "flight", "shop", "offers")
# Claves típicas en la respuesta que indican millas/disponibilidad.
RESP_KEY_HINTS = ("mile", "award", "cabin", "fare", "itiner", "segment", "availab", "flight")
SENSITIVE_HEADERS = {"cookie", "authorization", "x-api-key", "apikey", "x-auth-token"}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-4:] + f" ({len(value)} chars)"


def _json_or_none(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _keys_deep(obj, depth=0, acc=None):
    """Recolecta nombres de clave (para detectar 'miles', 'cabin', etc.)."""
    if acc is None:
        acc = set()
    if depth > 6:
        return acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k).lower())
            _keys_deep(v, depth + 1, acc)
    elif isinstance(obj, list):
        for item in obj[:5]:
            _keys_deep(item, depth + 1, acc)
    return acc


def score_entry(entry: dict) -> tuple[int, dict | None]:
    """Puntúa qué tan probable es que la entry sea la búsqueda de premios."""
    req = entry.get("request", {})
    resp = entry.get("response", {})
    url = req.get("url", "")
    method = req.get("method", "")
    score = 0

    low_url = url.lower()
    score += sum(3 for h in URL_HINTS if h in low_url)
    if method == "POST":
        score += 2

    body = _json_or_none((resp.get("content") or {}).get("text"))
    resp_keys: set[str] = set()
    if body is not None:
        resp_keys = _keys_deep(body)
        score += sum(2 for h in RESP_KEY_HINTS if any(h in k for k in resp_keys))

    mime = (resp.get("content") or {}).get("mimeType", "")
    if "json" in mime:
        score += 1

    info = {
        "url": url,
        "method": method,
        "request_headers": req.get("headers", []),
        "post_data": (req.get("postData") or {}).get("text"),
        "response_keys": sorted(resp_keys),
        "status": resp.get("status"),
        "mime": mime,
    }
    return score, info


def analyze(har_path: str) -> None:
    with open(har_path, encoding="utf-8") as fh:
        har = json.load(fh)
    entries = har.get("log", {}).get("entries", [])
    if not entries:
        print("El HAR no tiene entries. ¿Guardaste con contenido?")
        sys.exit(1)

    ranked = sorted(
        (score_entry(e) for e in entries), key=lambda t: t[0], reverse=True
    )
    ranked = [(s, i) for s, i in ranked if s > 0]
    if not ranked:
        print("No encontré ninguna request que parezca búsqueda de premios.")
        print("Revisá que el HAR incluya la request de disponibilidad.")
        sys.exit(1)

    print(f"Analizadas {len(entries)} requests. Candidatos más probables:\n")
    for rank, (score, info) in enumerate(ranked[:3], 1):
        print(f"{'='*70}\n#{rank}  (score {score})  HTTP {info['status']}  {info['mime']}")
        print(f"{info['method']} {info['url']}")

    best = ranked[0][1]
    parsed = urlparse(best["url"])
    print(f"\n{'#'*70}\n# MEJOR CANDIDATO — valores para .env\n{'#'*70}")
    print(f"LIFEMILES_BASE_URL={parsed.scheme}://{parsed.netloc}")
    print(f"LIFEMILES_SEARCH_PATH={parsed.path}")

    print(f"\n# Headers (los sensibles van enmascarados; copialos del HAR real):")
    for h in best["request_headers"]:
        name = h.get("name", "")
        val = h.get("value", "")
        if name.lower() in SENSITIVE_HEADERS:
            val = _mask(val)
        if not name.startswith(":"):  # omitir pseudo-headers HTTP/2
            print(f"  {name}: {val}")

    print(f"\n# Body de la request (esto guía `_build_request` en app/client.py):")
    body = _json_or_none(best["post_data"])
    print(json.dumps(body, indent=2, ensure_ascii=False) if body else f"  {best['post_data']}")

    print(f"\n# Claves de la respuesta (esto guía `_parse_response`):")
    print("  " + ", ".join(best["response_keys"]) or "  (respuesta no-JSON)")
    print(
        "\nBuscá en esas claves las que tienen millas, cabina, aerolínea y asientos,\n"
        "y ajustá `_parse_response` para leerlas. Pegame este output y lo cableo yo."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("har", help="ruta al archivo .har exportado de Chrome DevTools")
    args = ap.parse_args()
    analyze(args.har)


if __name__ == "__main__":
    main()
