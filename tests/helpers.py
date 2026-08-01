from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pv_bess.models import (
    BatteryConfig,
    DatasetMetadata,
    GridConfig,
    IntervalInput,
    Scenario,
)


def make_scenario(
    pv_kw: list[float],
    prices: list[float],
    *,
    interval_hours: float = 1.0,
    battery: BatteryConfig | None = None,
    grid: GridConfig | None = None,
) -> Scenario:
    if len(pv_kw) != len(prices):
        raise ValueError("test vectors must have the same length")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    intervals = tuple(
        IntervalInput(
            timestamp=start + timedelta(hours=interval_hours * index),
            pv_power_kw=pv,
            market_price_eur_per_mwh=price,
        )
        for index, (pv, price) in enumerate(zip(pv_kw, prices, strict=True))
    )
    return Scenario(
        name="Analytical test fixture",
        intervals=intervals,
        battery=battery
        or BatteryConfig(
            energy_capacity_kwh=2_000,
            max_charge_power_kw=1_000,
            max_discharge_power_kw=1_000,
            minimum_soc_fraction=0,
            maximum_soc_fraction=1,
            initial_soc_fraction=0.5,
            terminal_soc_fraction=0.5,
            charge_efficiency=1,
            discharge_efficiency=1,
            degradation_cost_eur_per_mwh_dc_discharged=1,
        ),
        grid=grid or GridConfig(export_limit_kw=1_000),
        dataset=DatasetMetadata(
            name="Analytical fixture",
            source="Hand-calculated test data",
            license_id="CC0-1.0",
            timezone_name="UTC",
        ),
    )
