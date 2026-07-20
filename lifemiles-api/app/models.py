"""Modelos de dominio para ofertas de premios."""
from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Offer(BaseModel):
    """Una disponibilidad de premio concreta para una ruta/fecha/cabina."""

    origin: str
    destination: str
    depart_date: date
    cabin: str
    miles: int
    taxes: float = 0.0
    currency: str = "USD"
    carrier: str = ""
    seats_left: int | None = None
    fetched_at: datetime = Field(default_factory=_now)

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def fingerprint(self) -> str:
        """Identidad estable de la oferta (para deduplicar)."""
        return (
            f"{self.origin}-{self.destination}-{self.depart_date.isoformat()}"
            f"-{self.cabin}-{self.miles}-{self.carrier}"
        )


class Deal(BaseModel):
    """Una oferta que cruzó un umbral y merece alerta."""

    offer: Offer
    reasons: list[str]
    historical_min: int | None = None
    detected_at: datetime = Field(default_factory=_now)
