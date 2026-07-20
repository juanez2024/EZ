"""Scheduler que recorre las rutas y busca ofertas de forma respetuosa."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .client import LifeMilesClient
from .config import AppConfig
from .deals import DealDetector
from .models import Deal
from .notifier import Notifier
from .storage import Store

log = logging.getLogger("lifemiles.monitor")


class Monitor:
    def __init__(
        self,
        config: AppConfig,
        client: LifeMilesClient,
        store: Store,
        detector: DealDetector,
        notifier: Notifier,
    ) -> None:
        self._cfg = config
        self._client = client
        self._store = store
        self._detector = detector
        self._notifier = notifier
        self._scheduler = BackgroundScheduler()
        self.last_cycle: dict = {"ran_at": None, "offers": 0, "deals": 0}

    def run_cycle(self) -> list[Deal]:
        """Un barrido completo de rutas × cabinas × fechas muestreadas."""
        s = self._cfg.search
        dates = s.date_window_days.sample(s.sample_dates_per_cycle)
        found_offers = 0
        new_deals: list[Deal] = []

        for route in self._cfg.routes:
            for cabin in s.cabins:
                for depart in dates:
                    offers = self._client.search(
                        route.origin, route.destination, depart, cabin, s.passengers
                    )
                    for offer in offers:
                        # Evaluar contra histórico ANTES de registrar la oferta.
                        deal = self._detector.evaluate(offer)
                        self._store.record_offer(offer)
                        found_offers += 1
                        if deal and self._store.record_deal(deal):
                            self._notifier.notify(deal)
                            new_deals.append(deal)
                    # Rate limiting: no martillar el servidor.
                    time.sleep(self._cfg.scheduler.per_request_delay_seconds)

        self.last_cycle = {
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "offers": found_offers,
            "deals": len(new_deals),
        }
        log.info(
            "Ciclo completo: %s ofertas, %s deals nuevos",
            found_offers, len(new_deals),
        )
        return new_deals

    def _tick(self) -> None:
        try:
            self.run_cycle()
        except Exception:  # el scheduler no debe morir por un ciclo fallido
            log.exception("Ciclo de búsqueda falló")
        finally:
            self._reschedule()

    def _reschedule(self) -> None:
        # Intervalo fijo + jitter aleatorio para no ser predecible ni abusivo.
        sc = self._cfg.scheduler
        jitter = random.uniform(-sc.jitter_seconds, sc.jitter_seconds)
        delay = max(60, sc.interval_seconds + jitter)
        self._scheduler.add_job(
            self._tick, "date", run_date=datetime.now() + timedelta(seconds=delay)
        )
        log.info("Próximo ciclo en ~%.0f s", delay)

    def start(self) -> None:
        self._scheduler.start()
        # Primer ciclo casi inmediato; luego se auto-reprograma con jitter.
        self._scheduler.add_job(
            self._tick, "date", run_date=datetime.now() + timedelta(seconds=1)
        )
        log.info("Monitor iniciado")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._client.close()
        log.info("Monitor detenido")
