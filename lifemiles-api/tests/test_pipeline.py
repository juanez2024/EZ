"""Pruebas del pipeline con el cliente mock (sin red)."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from app.client import MockLifeMilesClient
from app.config import AppConfig, DealsConfig, Route, SchedulerConfig, SearchConfig
from app.deals import DealDetector
from app.models import Offer
from app.monitor import Monitor
from app.notifier import Notifier
from app.storage import Store


def _store() -> Store:
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return Store(tmp)


def test_mock_client_is_deterministic():
    c = MockLifeMilesClient()
    a = c.search("BOG", "MAD", date(2026, 8, 1), "business", 1)
    b = c.search("BOG", "MAD", date(2026, 8, 1), "business", 1)
    assert a[0].miles == b[0].miles
    assert a[0].miles > 0


def test_deal_threshold_triggers():
    store = _store()
    detector = DealDetector(DealsConfig(max_miles={"economy": 30000}), store)
    cheap = Offer(
        origin="BOG", destination="MIA", depart_date=date(2026, 8, 1),
        cabin="economy", miles=20000,
    )
    deal = detector.evaluate(cheap)
    assert deal is not None
    assert "umbral" in " ".join(deal.reasons)


def test_deal_not_triggered_above_threshold():
    store = _store()
    detector = DealDetector(
        DealsConfig(max_miles={"economy": 30000}, drop_pct_vs_historical=15), store
    )
    pricey = Offer(
        origin="BOG", destination="MIA", depart_date=date(2026, 8, 1),
        cabin="economy", miles=45000,
    )
    assert detector.evaluate(pricey) is None


def test_historical_drop_triggers_deal():
    store = _store()
    detector = DealDetector(
        DealsConfig(max_miles={"business": 1}, drop_pct_vs_historical=15), store
    )
    baseline = Offer(
        origin="BOG", destination="GRU", depart_date=date(2026, 8, 1),
        cabin="business", miles=100000,
    )
    store.record_offer(baseline)
    dropped = Offer(
        origin="BOG", destination="GRU", depart_date=date(2026, 8, 2),
        cabin="business", miles=70000,  # -30% vs 100k
    )
    deal = detector.evaluate(dropped)
    assert deal is not None
    assert any("caída" in r for r in deal.reasons)


def test_full_cycle_records_and_dedupes():
    store = _store()
    config = AppConfig(
        routes=[Route(origin="BOG", destination="MAD")],
        search=SearchConfig(cabins=["business"], sample_dates_per_cycle=2),
        deals=DealsConfig(max_miles={"business": 999999}),  # todo es deal
        scheduler=SchedulerConfig(per_request_delay_seconds=0),
    )
    monitor = Monitor(
        config, MockLifeMilesClient(), store,
        DealDetector(config.deals, store), Notifier(),
    )
    first = monitor.run_cycle()
    assert monitor.last_cycle["offers"] == 2
    # Segundo ciclo: mismas ofertas => no hay deals nuevos (dedup por fingerprint).
    second = monitor.run_cycle()
    assert len(second) == 0
    assert len(first) >= 1
