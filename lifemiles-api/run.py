"""Entrypoint: levanta la API + el monitor en segundo plano.

    python run.py

Variables clave en .env:
    LIFEMILES_MODE=mock   -> sin red, datos simulados
    LIFEMILES_MODE=live   -> pega contra el endpoint real configurado
"""
from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
