"""Detección de ofertas (deals) a partir de las disponibilidades vistas."""
from __future__ import annotations

from .config import DealsConfig
from .models import Deal, Offer
from .storage import Store


class DealDetector:
    def __init__(self, config: DealsConfig, store: Store) -> None:
        self._cfg = config
        self._store = store

    def evaluate(self, offer: Offer) -> Deal | None:
        """Devuelve un ``Deal`` si la oferta cruza algún umbral, si no ``None``.

        Se llama ANTES de registrar la oferta, para comparar contra el
        mínimo histórico previo (sin contarse a sí misma).
        """
        reasons: list[str] = []

        threshold = self._cfg.max_miles.get(offer.cabin)
        if threshold is not None and offer.miles <= threshold:
            reasons.append(
                f"{offer.miles} millas <= umbral {threshold} ({offer.cabin})"
            )

        hist_min = self._store.historical_min(
            offer.origin, offer.destination, offer.cabin
        )
        if hist_min is not None and hist_min > 0:
            drop_pct = (hist_min - offer.miles) / hist_min * 100
            if drop_pct >= self._cfg.drop_pct_vs_historical:
                reasons.append(
                    f"caída {drop_pct:.0f}% vs mínimo histórico {hist_min}"
                )

        if not reasons:
            return None
        return Deal(offer=offer, reasons=reasons, historical_min=hist_min)
