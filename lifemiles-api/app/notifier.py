"""Alertas cuando se detecta un deal nuevo."""
from __future__ import annotations

import logging

import httpx

from .models import Deal

log = logging.getLogger("lifemiles.notifier")


class Notifier:
    def __init__(self, webhook_url: str = "") -> None:
        self._webhook = webhook_url

    def _format(self, deal: Deal) -> str:
        o = deal.offer
        return (
            f"🔥 DEAL {o.origin}->{o.destination} {o.depart_date} [{o.cabin}]\n"
            f"   {o.miles} millas + {o.taxes:.0f} {o.currency}"
            f"{f' | {o.seats_left} asientos' if o.seats_left is not None else ''}\n"
            f"   Motivo: {', '.join(deal.reasons)}"
        )

    def notify(self, deal: Deal) -> None:
        message = self._format(deal)
        log.info("ALERTA:\n%s", message)
        if not self._webhook:
            return
        try:
            httpx.post(self._webhook, json={"text": message}, timeout=10.0)
        except httpx.HTTPError as exc:
            log.warning("No se pudo enviar el webhook: %s", exc)
