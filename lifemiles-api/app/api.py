"""API HTTP para consultar ofertas y deals, y controlar el monitor."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .client import build_client
from .config import get_config, get_settings
from .deals import DealDetector
from .monitor import Monitor
from .notifier import Notifier
from .storage import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    config = get_config()
    store = Store()
    client = build_client(settings)
    detector = DealDetector(config.deals, store)
    notifier = Notifier(settings.alert_webhook_url)
    monitor = Monitor(config, client, store, detector, notifier)
    monitor.start()

    _state.update(
        settings=settings, config=config, store=store,
        client=client, monitor=monitor,
    )
    try:
        yield
    finally:
        monitor.stop()
        store.close()


app = FastAPI(
    title="LifeMiles Deals API (no oficial)",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    monitor: Monitor = _state["monitor"]
    settings = _state["settings"]
    return {
        "status": "ok",
        "mode": settings.lifemiles_mode,
        "last_cycle": monitor.last_cycle,
    }


@app.get("/deals")
def list_deals(limit: int = 50) -> list[dict]:
    """Deals detectados, más recientes primero."""
    store: Store = _state["store"]
    return store.recent_deals(limit=limit)


@app.get("/offers")
def list_offers(limit: int = 50) -> list[dict]:
    """Mejores disponibilidades vistas, ordenadas por millas ascendente."""
    store: Store = _state["store"]
    return store.best_offers(limit=limit)


@app.get("/routes")
def list_routes() -> list[dict]:
    config = _state["config"]
    return [r.model_dump() for r in config.routes]


@app.post("/scan", status_code=202)
def scan_now() -> dict:
    """Dispara un ciclo de búsqueda en segundo plano.

    Un ciclo completo puede tardar minutos (rate limiting entre requests),
    así que se ejecuta en un hilo aparte y devuelve de inmediato. Consultá
    ``/health`` (last_cycle) y ``/deals`` para ver el resultado.
    """
    monitor: Monitor = _state["monitor"]
    threading.Thread(target=monitor.run_cycle, daemon=True).start()
    return {"status": "scan_started", "last_cycle": monitor.last_cycle}
