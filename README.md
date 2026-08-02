# PV-BESS Dispatch Model

[![CI](https://github.com/NishikawaButterfly/pv-bess-hybrid/actions/workflows/ci.yml/badge.svg)](https://github.com/NishikawaButterfly/pv-bess-hybrid/actions/workflows/ci.yml)

A Python model for dispatch of solar-plus-battery plants. It reads hourly PV production and market prices, computes a battery dispatch schedule (a mixed-integer program solved with HiGHS), and works out NPV, IRR, payback and LCOS for the scenario. Early alpha, command-line only.

The scope is dispatch plus unlevered, pre-tax investment math. Results are scenario calculations, not forecasts, grid-code studies, equipment certifications, or investment advice.

## Background

The original prototype mixed dispatch, electrical design, thermal estimates, equipment selections, and hard-coded report claims in two scripts. An independent audit found material dimensional and reconciliation errors, so those scripts were removed from the tree. [`legacy/README.md`](legacy/README.md) marks the migration boundary; the old prototype is not distributed in this repository.

## What it does

- Loads a JSON scenario plus a CSV of hourly PV power and prices, with strict validation (schema, timezone, ordering, gaps, size limits).
- Solves battery dispatch as a mixed-integer program via `scipy.optimize.milp` (HiGHS backend). The model covers PV export, PV and optional grid charging, battery export, curtailment, and SOC accounting with separate charge and discharge efficiencies, all under shared grid limits. A second solve then minimizes battery throughput without changing the economic optimum.
- Compares against a PV-only baseline and reports curtailment reduction, market value, a degradation reserve, and equivalent full cycles.
- Turns the incremental operating value into cash flows and computes NPV, IRR, simple and discounted payback, and LCOS.
- Writes SHA-256 hashes of its inputs and the solver metadata into the output, so a run can be checked later.

The full detail lives in [docs/methodology.md](docs/methodology.md) and [docs/architecture.md](docs/architecture.md).

## Quick start

Python 3.12 or 3.13 is supported.

Bash:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

Validate the sample without solving:

```bash
pv-bess validate --scenario sample-data/scenario.json
```

Run the optimization and financial calculation:

```bash
pv-bess run \
  --scenario sample-data/scenario.json \
  --output results/sample
```

PowerShell equivalent:

```powershell
pv-bess run --scenario sample-data/scenario.json --output results/sample
```

This writes `summary.json` (provenance, solver metadata, units, KPIs, cash flows) and `dispatch.csv` (per-interval flows, SOC, market value, degradation cost). Existing files are not overwritten unless you pass `--force`.

The bundled sample is a synthetic 24-hour day annualized with an explicit factor of 365. It demonstrates the calculation flow and nothing more; see [`sample-data/README.md`](sample-data/README.md).

## Input format

`scenario.json` holds the equipment, grid, provenance, and financial assumptions. Its `time_series_csv` path must be relative and stay inside the scenario directory.

The CSV header must be exactly:

```text
timestamp,pv_power_kw,market_price_eur_per_mwh
```

Timestamps are interval starts with an explicit UTC offset, and the intervals have to be uniform with no gaps. Power is AC-side kW at the modeled point of connection, stored energy is DC-side kWh, prices are EUR/MWh. Short samples are never silently treated as a full year — the `annualization_factor` is yours to set.

See the [data contract](docs/data-contract.md) and the [validation notes](docs/validation.md).

## API

The same calculation is available over HTTP as an optional extra. The kernel does not depend on it; FastAPI is only imported by `pv_bess.api`.

```bash
python -m pip install -r requirements-api.txt
python -m pip install --no-deps -e .
pv-bess serve --host 127.0.0.1 --port 8000
```

(`pip install 'pv-bess-hybrid[api]'` works too.) `POST /api/v1/dispatch` takes the same two files the CLI reads and returns the `summary.json` payload; `GET /health` reports kernel and solver versions. Bad files get a 400, valid files with impossible values a 422, and uploads beyond the documented size limits a 413.

```bash
curl -F scenario=@sample-data/scenario.json \
  -F time_series=@sample-data/hourly.csv \
  http://127.0.0.1:8000/api/v1/dispatch
```

## Tests

If NumPy and SciPy are already installed, nothing else is needed:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

CI additionally runs formatting, lint, strict typing, branch coverage, a package build, and a dependency audit on both supported Python versions.

## Layout

```text
sample-data/        fictional input fixture
src/pv_bess/        models, dispatch MILP, finance, I/O, CLI, provenance, optional API
tests/              unit tests
docs/               data contract, methodology, limitations, threat model
legacy/             migration note about the retired prototype
```

The library itself has no required web framework or database dependency; the HTTP layer is an optional extra on top of the unchanged kernel. See [architecture](docs/architecture.md) and [ADR 0001](docs/decisions/0001-kernel-first.md).

## What it doesn't do

This is a dispatch model, nothing more. It does no electrical design — no protection, short-circuit, cable, transformer, EMF, or thermal calculations. It doesn't check grid-code compliance or certify equipment. There is no price forecasting and no live market connection. The financials ignore taxes, debt, and grants, and there is no probabilistic analysis. No web interface, no persistence, no multi-user anything: just the CLI and an optional single-process HTTP API.

See [known limitations](docs/limitations.md) and the [roadmap](ROADMAP.md).

## Security and data

Only fictional or explicitly redistributable data belongs in this public repository. Imported time series are processed locally and the package makes no network calls. Report vulnerabilities through the process in [SECURITY.md](SECURITY.md).

## License

Source code is available under the [MIT License](LICENSE). The synthetic CSV fixture is released under CC0-1.0 as documented in [`sample-data/README.md`](sample-data/README.md).
