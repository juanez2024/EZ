"""Ejecuta un único ciclo de búsqueda y muestra los deals. Sin servidor.

    python scan_once.py            # respeta el rate limit de config.yaml
    python scan_once.py --fast     # sin pausas entre requests (solo pruebas)

Útil para probar el pipeline o correrlo desde un cron externo.
"""
from __future__ import annotations

import argparse
import logging

from app.client import build_client
from app.config import get_config, get_settings
from app.deals import DealDetector
from app.monitor import Monitor
from app.notifier import Notifier
from app.storage import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fast", action="store_true",
        help="sin pausas entre requests (solo para pruebas)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = get_settings()
    config = get_config()
    if args.fast:
        config.scheduler.per_request_delay_seconds = 0

    store = Store()
    client = build_client(settings)
    monitor = Monitor(
        config, client, store,
        DealDetector(config.deals, store),
        Notifier(settings.alert_webhook_url),
    )
    deals = monitor.run_cycle()
    client.close()

    print(f"\n=== {len(deals)} deal(s) detectados ===")
    for d in deals:
        o = d.offer
        print(f"  {o.origin}->{o.destination} {o.depart_date} [{o.cabin}] "
              f"{o.miles} millas  ({', '.join(d.reasons)})")
    store.close()


if __name__ == "__main__":
    main()
