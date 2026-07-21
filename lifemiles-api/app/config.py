"""Carga de configuración desde config.yaml + variables de entorno."""
from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Secretos y toggles de entorno (.env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    lifemiles_username: str = ""
    lifemiles_password: str = ""
    lifemiles_base_url: str = "https://api.lifemiles.com"
    lifemiles_search_path: str = "/svc/air-redemption-find-flight-private"
    # Bearer JWT del SSO de LifeMiles (Keycloak). Corta vida (~minutos);
    # ver nota de AUTENTICACIÓN en LiveLifeMilesClient.
    lifemiles_api_key: str = ""
    lifemiles_realm: str = "lifemiles"
    lifemiles_language: str = "es"
    lifemiles_country: str = "co"
    lifemiles_currency: str = "COP"
    # Opcional: id de cotización de una sesión web, si el server lo exige.
    lifemiles_id_coti: str = ""
    lifemiles_mode: str = Field("mock", pattern="^(mock|live)$")

    alert_webhook_url: str = ""

    api_host: str = "127.0.0.1"
    api_port: int = 8000


class Route(BaseModel):
    origin: str
    destination: str

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


class DateWindow(BaseModel):
    start_offset: int = 14
    end_offset: int = 120

    def sample(self, count: int) -> list[date]:
        """Devuelve `count` fechas espaciadas uniformemente en la ventana."""
        today = date.today()
        span = max(self.end_offset - self.start_offset, 1)
        if count <= 1:
            return [today + timedelta(days=self.start_offset)]
        step = span / (count - 1)
        return [
            today + timedelta(days=int(self.start_offset + step * i))
            for i in range(count)
        ]


class SearchConfig(BaseModel):
    cabins: list[str] = ["economy", "business"]
    passengers: int = 1
    date_window_days: DateWindow = DateWindow()
    sample_dates_per_cycle: int = 6


class DealsConfig(BaseModel):
    max_miles: dict[str, int] = {"economy": 30000, "premium": 55000, "business": 90000}
    drop_pct_vs_historical: float = 15.0
    # Códigos IATA de aerolíneas a alertar. Vacío = todas las Star Alliance.
    only_carriers: list[str] = []


class SchedulerConfig(BaseModel):
    interval_seconds: int = 900
    jitter_seconds: int = 120
    per_request_delay_seconds: float = 4.0


class AppConfig(BaseModel):
    routes: list[Route]
    search: SearchConfig = SearchConfig()
    deals: DealsConfig = DealsConfig()
    scheduler: SchedulerConfig = SchedulerConfig()


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_config(path: str | None = None) -> AppConfig:
    cfg_path = Path(path) if path else BASE_DIR / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return AppConfig(**data)
