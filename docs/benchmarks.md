# Solver benchmarks

The roadmap requires benchmarking a complete 8,760-interval scenario and publishing the hardware, runtime, solver gap, and input hash. This page records those measurements and explains why the committed large fixture is a month rather than a year.

## Environment

| Component | Value |
| --- | --- |
| CPU | 7th-generation Intel Core i5 class, 2 cores / 4 threads, 2.5 GHz |
| Memory | 8 GB |
| Operating system | Windows 10, 64-bit |
| Python | 3.13.3 |
| NumPy / SciPy | 2.5.1 / 1.18.0 |
| HiGHS backend | 1.12.0 |
| Model version | `dispatch-milp-1.0` |
| Requested relative MIP gap | `1e-8`, presolve enabled |

## Method

All horizons use the deterministic synthetic year produced by `tools/make_synthetic_year.py` with seed 2026. Shorter horizons are the first N hours of that year with the battery, grid, and degradation configuration of `sample-data/monthly/scenario.json`. Each row is a single-process wall-clock measurement with no concurrent load. The economic and refinement columns time the two `scipy.optimize.milp` calls; the total additionally includes problem construction and post-solve validation.

## Results

| Horizon | Economic phase | Refinement phase | Total wall clock |
| --- | ---: | ---: | ---: |
| 24 h | 0.02 s | 0.02 s | 0.04 s |
| 168 h (week) | 0.04 s | 0.03 s | 0.08 s |
| 744 h (month) | 0.19 s | 0.20 s | 0.58 s |
| 2,190 h (quarter) | 1.20 s | 1.04 s | 2.75 s |
| 4,380 h (half year) | 3.44 s | 18.62 s | 22.54 s |
| 8,760 h (full year) | 13.72 s | 176.69 s | 191.18 s (best case; see below) |

Every completed solve proved a relative MIP gap of 0.0 in both phases. Peak working-set memory observed during full-year attempts was about 245 MiB.

The full-year result is not dependable. One run completed in 191 seconds, but an identical repeat run of the same problem found no feasible refinement solution within a 1,200-second per-phase limit and was aborted, and an earlier draft of the price series (different jitter and midday-depression depth) also produced no refinement incumbent within 280 seconds. The economic phase scales roughly linearly; the throughput-refinement phase dominates beyond roughly 2,000 intervals, grows super-linearly, and its runtime is highly sensitive to the price series and solver environment.

## Consequences

- The committed large fixture is the 744-hour month in `sample-data/monthly/`, which solves in about one second — comfortably inside the default 60-second limit. CI solves a one-week slice; the full-month solve runs with `PV_BESS_RUN_SLOW_TESTS=1`.
- A full-year fixture is not committed: on the reference hardware it can exceed any practical time limit, and a sample that fails its own documented run would be worse than none.
- Practical single-solve horizons on modest hardware are currently up to roughly a quarter (about 2,000 intervals). For longer studies, a rolling-horizon (chunked) solve with state-of-charge hand-off between windows would bound refinement time; that decomposition is future work and is not implemented.

## Reproduction

Committed monthly fixture (hashes are also asserted by the test suite):

| Evidence | Value |
| --- | --- |
| Dispatch input SHA-256 | `45d62c07d58c8f381138cc54da10605c4a2fd5d75e38b84ef15ee45801964958` |
| Complete analysis SHA-256 | `a9b25aaec1e112250cd3bf2b3dc024fa27e4f6e8e69fe6ea01a6306b8a26e884` |

Full-year benchmark scenario: generate the year CSV, copy `sample-data/monthly/scenario.json` next to it, and change only `time_series_csv` to the generated file and `annualization_factor` to 1. `pv-bess validate` then reports dispatch input SHA-256 `ae2cb81d51cf618fd59092f7159e03a8489a75dc92e0bcadcc08ef7bb852b507` for 8,760 intervals.

```bash
python tools/make_synthetic_year.py --seed 2026 --output year.csv
pv-bess validate --scenario scenario.json
pv-bess run --scenario scenario.json --output results/annual --time-limit 1200
```

The last command may or may not finish, which is precisely the published finding.
