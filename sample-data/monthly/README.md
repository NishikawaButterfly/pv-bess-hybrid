# Synthetic monthly sample

`hourly.csv` is a deterministic, fictional 744-hour month (March 2026, UTC) cut from a synthetic 8,760-hour year. It is invented data created for this repository — not measured generation and not real market prices — and must not be used as a forecast.

## How it was generated

```bash
python tools/make_synthetic_year.py --seed 2026 --month 3 --output sample-data/monthly/hourly.csv
```

The generator builds the full synthetic year from round, invented constants: a seasonal PV scale (1.0 near the June solstice, 0.4 near the December one), a daylight window of 8 to 16 hours, a half-sine diurnal shape for a 5,000 kW plant, a seasonal price base of 40 to 60 EUR/MWh with a fixed day/night shape, a solar-correlated midday price depression, and whole-EUR jitter from an explicitly seeded pseudorandom generator. The committed CSV is reproduced byte for byte by the test suite, so any drift between the generator and the fixture fails CI.

March was chosen because it sits near the annual average of the synthetic seasonal PV curve, making it less biased than a midwinter or midsummer month.

## Annualization

`scenario.json` sets `annualization_factor` to `8760 / 744` (about 11.774), which scales the modeled month to one calendar year. Annualizing a single month is suitable only for demonstrating the calculation flow at a realistic solver scale; it ignores seasonality outside March, and a real study needs a complete, licensed year of data. The financial result is intentionally unfavorable (negative NPV, no conventional IRR): the fixture demonstrates that the software reports the configured assumptions instead of forcing a positive investment conclusion.

## Why a month and not the full year

The full 8,760-hour year produced by the same generator was benchmarked and is not committed as a fixture: its throughput-refinement solve phase is unreliable at that horizon on the reference hardware — one run finished in about three minutes, while an identical repeat run found no feasible refinement solution within a 1,200-second per-phase limit. The month solves in about one second. Measured timings per horizon are published in [docs/benchmarks.md](../../docs/benchmarks.md).

The month solves comfortably inside the default 60-second limit. CI solves a one-week slice; the full-month solve runs when `PV_BESS_RUN_SLOW_TESTS=1` is set.

## License

The synthetic CSV is dedicated to the public domain under CC0-1.0. Source code remains under the repository's MIT License.
