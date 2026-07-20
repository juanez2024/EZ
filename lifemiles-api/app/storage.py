"""Persistencia en SQLite de ofertas vistas y deals detectados."""
from __future__ import annotations

import sqlite3
import threading
from datetime import date
from pathlib import Path

from .models import Deal, Offer

_DDL = """
CREATE TABLE IF NOT EXISTS offers (
    fingerprint TEXT PRIMARY KEY,
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    cabin       TEXT NOT NULL,
    miles       INTEGER NOT NULL,
    taxes       REAL NOT NULL,
    currency    TEXT NOT NULL,
    carrier     TEXT NOT NULL,
    seats_left  INTEGER,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offers_route_cabin ON offers(origin, destination, cabin);

CREATE TABLE IF NOT EXISTS deals (
    fingerprint  TEXT PRIMARY KEY,
    origin       TEXT NOT NULL,
    destination  TEXT NOT NULL,
    depart_date  TEXT NOT NULL,
    cabin        TEXT NOT NULL,
    miles        INTEGER NOT NULL,
    reasons      TEXT NOT NULL,
    historical_min INTEGER,
    detected_at  TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: str | Path = "lifemiles.db") -> None:
        self._path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ---- offers ----
    def record_offer(self, offer: Offer) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO offers
                   (fingerprint, origin, destination, depart_date, cabin, miles,
                    taxes, currency, carrier, seats_left, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    offer.fingerprint, offer.origin, offer.destination,
                    offer.depart_date.isoformat(), offer.cabin, offer.miles,
                    offer.taxes, offer.currency, offer.carrier,
                    offer.seats_left, offer.fetched_at.isoformat(),
                ),
            )
            self._conn.commit()

    def historical_min(self, origin: str, destination: str, cabin: str) -> int | None:
        cur = self._conn.execute(
            "SELECT MIN(miles) AS m FROM offers WHERE origin=? AND destination=? AND cabin=?",
            (origin, destination, cabin),
        )
        row = cur.fetchone()
        return row["m"] if row and row["m"] is not None else None

    def best_offers(self, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM offers ORDER BY miles ASC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    # ---- deals ----
    def record_deal(self, deal: Deal) -> bool:
        """Guarda el deal. Devuelve True si es nuevo (no visto antes)."""
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM deals WHERE fingerprint=?",
                (deal.offer.fingerprint,),
            ).fetchone()
            if exists:
                return False
            self._conn.execute(
                """INSERT INTO deals
                   (fingerprint, origin, destination, depart_date, cabin, miles,
                    reasons, historical_min, detected_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    deal.offer.fingerprint, deal.offer.origin, deal.offer.destination,
                    deal.offer.depart_date.isoformat(), deal.offer.cabin,
                    deal.offer.miles, "; ".join(deal.reasons),
                    deal.historical_min, deal.detected_at.isoformat(),
                ),
            )
            self._conn.commit()
            return True

    def recent_deals(self, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM deals ORDER BY detected_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
