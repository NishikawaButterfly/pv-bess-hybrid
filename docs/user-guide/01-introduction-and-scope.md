# 1. Introduction and scope

## Who this guide is for

You are sizing or appraising a solar-plus-storage project. You have, or can obtain, an
hourly PV production profile and an hourly market price series. You want to know what a
battery of a given size would do on that site, what incremental revenue it would earn,
and whether the investment case survives contact with the numbers.

This guide assumes you can read a CSV, edit a JSON file, and run a command. It does not
assume you know mixed-integer programming; the [methodology](../methodology.md) is there
if you want the formulation.

## What the model decides

Given a fixed plant and a fixed price series, the optimiser chooses, for every interval,
how to split the available PV and how to move the battery. There are five flows and one
stored quantity:

| Decision | Meaning |
| --- | --- |
| `pv_export_kw` | PV sent straight to the grid |
| `pv_charge_kw` | PV diverted into the battery |
| `grid_charge_kw` | Energy imported from the grid into the battery (only if you allow it) |
| `battery_export_kw` | Battery discharge sent to the grid |
| `curtailed_pv_kw` | PV deliberately not used |
| `soc_end_kwh` | Stored energy at the end of the interval |

Two binary decisions per interval enforce physical exclusivity: the battery cannot charge
and discharge in the same interval, and the point of connection cannot import and export
in the same interval.

The objective is market value less an explicit degradation reserve. A second solve then
strips out any battery movement that earned nothing, so the schedule you read is the
least-throughput schedule among those achieving the optimal economics.

## What the model takes as given

Everything else. In particular:

- **The plant.** PV capacity, battery capacity and power, efficiencies, and the grid
  limits are inputs, not outputs. The model does not size the battery for you — it
  evaluates the battery you specify. Sizing is done by running several scenarios and
  comparing, which is what [sensitivity analysis](21-sensitivity.md) automates for one
  parameter at a time.
- **The prices.** There is no forecasting and no market connection. The optimiser sees
  your entire price series at once and dispatches with perfect foresight. Real operation
  under uncertainty will earn less.
- **The costs.** CAPEX and fixed OPEX are numbers you supply. The model has no cost
  database and will happily evaluate a 200 MWh battery at the CAPEX you gave for a 20 MWh
  one.
- **The physics beyond energy.** No voltage, current, protection, thermal, or grid-code
  calculation happens anywhere in this software.

## The two questions it answers

**Operationally**: what does the battery do, and what is that worth over the modelled
period? This comes out as `dispatch.csv` and the dispatch KPIs.

**Financially**: scaled to a year and carried across the project life, does the
incremental benefit recover the incremental cost? This comes out as NPV, IRR, payback,
and LCOS.

The link between them is the `annualization_factor`, which you set explicitly. The model
never guesses how representative your period is. If you model one summer day and set the
factor to 365, you have asserted that every day of the year looks like that day — an
assertion the software will honour without comment.

## The incremental convention

This is the single most important convention in the product, and it is easy to miss.

Every financial figure describes the **battery increment**, not the whole plant. The
model solves the scenario twice in effect: once as configured, and once as a PV-only
baseline that exports up to the grid limit whenever the price is non-negative and curtails
the rest. The difference between the two is the battery's contribution.

So `capex_eur` should be the battery's cost, not the plant's. `annual_fixed_opex_eur`
should be the battery's fixed operating cost. If you enter the whole project's CAPEX
against the battery's incremental benefit, the NPV will be meaninglessly negative — and
the software cannot tell that you have done so.

## What a run produces

A completed `pv-bess run` writes two files that belong together:

- `summary.json` — provenance hashes, solver metadata, units, dispatch KPIs, the cash-flow
  series, the financial metrics, and a short limitations list.
- `dispatch.csv` — one row per interval with every flow, the SOC at both ends, and the
  per-interval value.

Both carry the same two SHA-256 hashes, so a summary and a dispatch file can always be
checked against each other. [Exporting results](22-exporting-results.md) covers the
optional Excel workbook.

## What this is not

The [limitations](../limitations.md) document is the authoritative list. The short version:
this is a dispatch and investment-arithmetic model. It is not an electrical design tool,
not a grid-code study, not a price forecast, not a probabilistic analysis, and not
investment advice. It models one aggregated PV source, one aggregated battery, and one
point of connection, with no local load.

## Environment used for this guide

Every figure in these chapters was produced on this configuration. Small numerical
differences on other builds are expected; large ones are worth investigating.

| Component | Value |
| --- | --- |
| Package | `pv-bess-hybrid` 0.1.0 |
| Python | 3.13.3 |
| NumPy | 2.5.2 |
| SciPy | 1.18.0 |
| HiGHS backend | 1.12.0 |
| Schema version | `1.0` |
| Model version | `dispatch-milp-1.0` |
| Operating system | Windows 10, 64-bit |

Where a chapter uses a scenario that is not in the repository, the scenario is printed in
full so you can reproduce the run yourself.
