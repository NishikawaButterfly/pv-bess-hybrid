"""Deterministic generator for the synthetic hourly PV and price fixtures.

The generator invents a fictional, seeded 8,760-hour year with a smooth
seasonal and diurnal PV shape and a day/night market-price shape. It exists so
that every committed CSV fixture can be reproduced byte for byte:

    python tools/make_synthetic_year.py --seed 2026 --month 3 \
        --output sample-data/monthly/hourly.csv

Omitting ``--month`` emits the complete year, which is used for solver
benchmarks. No measured generation or market data is used; every constant is a
round, invented number and the only randomness is an explicitly seeded jitter.
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from math import cos, pi, sin, tau
from pathlib import Path

HOURS_PER_YEAR = 8_760
PEAK_PV_KW = 5_000
START = datetime(2026, 1, 1, tzinfo=UTC)
CSV_HEADER = "timestamp,pv_power_kw,market_price_eur_per_mwh"

# Fixed diurnal price offsets in EUR/MWh: night trough, morning ramp,
# midday depression, evening peak.
_DIURNAL_PRICE_OFFSETS = (
    -15, -18, -20, -20, -18, -12,
    -5, 5, 10, 5, -5, -12,
    -15, -12, -8, 0, 8, 15,
    20, 18, 10, 0, -8, -12,
)  # fmt: skip


def synthetic_year(seed: int) -> list[tuple[datetime, int, int]]:
    """Return 8,760 rows of (UTC timestamp, PV kW, price EUR/MWh)."""

    rng = random.Random(seed)
    rows: list[tuple[datetime, int, int]] = []
    for step in range(HOURS_PER_YEAR):
        day = step // 24
        hour = step % 24
        # Seasonal PV scale peaks at 1.0 near the June solstice and bottoms
        # at 0.4 near the December one; daylight spans 16 h down to 8 h.
        season = 0.7 + 0.3 * cos(tau * (day - 171) / 365)
        daylight = 12 + 4 * cos(tau * (day - 171) / 365)
        sunrise = 12 - daylight / 2
        midpoint = hour + 0.5
        diurnal = 0.0
        if sunrise < midpoint < sunrise + daylight:
            diurnal = sin(pi * (midpoint - sunrise) / daylight)
        pv_kw = round(PEAK_PV_KW * season * diurnal)

        # Prices: seasonal base (60 EUR/MWh mid-January down to 40 mid-July),
        # a fixed diurnal shape, a solar-correlated midday depression that can
        # push high-summer hours slightly negative, and seeded whole-EUR jitter.
        base = 50 + 10 * cos(tau * (day - 15) / 365)
        solar_depression = 25 * season * diurnal
        price = round(base + _DIURNAL_PRICE_OFFSETS[hour] - solar_depression + rng.randint(-3, 3))
        rows.append((START + timedelta(hours=step), pv_kw, price))
    return rows


def month_slice(
    rows: list[tuple[datetime, int, int]], month: int
) -> list[tuple[datetime, int, int]]:
    """Return the rows of one calendar month, jitter identical to the full year."""

    selected = [row for row in rows if row[0].month == month]
    if not selected:
        raise ValueError(f"month {month} selects no rows")
    return selected


def render_csv(rows: list[tuple[datetime, int, int]]) -> str:
    lines = [CSV_HEADER]
    lines.extend(f"{timestamp.isoformat()},{pv_kw},{price}" for timestamp, pv_kw, price in rows)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=2026, help="deterministic seed (default 2026)")
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        default=None,
        help="emit only this calendar month of the synthetic year",
    )
    parser.add_argument("--output", type=Path, required=True, help="CSV file to write")
    args = parser.parse_args(argv)

    rows = synthetic_year(args.seed)
    if args.month is not None:
        rows = month_slice(rows, args.month)
    args.output.write_text(render_csv(rows), encoding="utf-8", newline="")
    print(f"wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
