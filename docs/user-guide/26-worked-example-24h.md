# 26. A worked 24-hour example

This chapter takes the repository's bundled sample end to end: the inputs, the schedule,
the reconciliation arithmetic, and the economics. Every figure here came from running

```bash
pv-bess run --scenario sample-data/scenario.json --output results/sample
```

on the environment recorded in [chapter 1](01-introduction-and-scope.md). It completed in
3.3 seconds.

## The scenario

A 5 MW PV plant with a 5 MW / 20 MWh battery on a 5 MW connection, over one synthetic
summer day.

| Block | Setting |
| --- | --- |
| Battery | 20,000 kWh DC, 5,000 kW charge and discharge |
| SOC window | 0.20–0.95, i.e. 4,000–19,000 kWh; 15,000 kWh usable |
| Initial and terminal SOC | 0.50 = 10,000 kWh |
| Efficiencies | 0.96 charge, 0.96 discharge (92.16% round trip) |
| Degradation reserve | EUR 10/MWh DC discharged |
| Grid | 5,000 kW export, no import, grid charging off |
| CAPEX / fixed OPEX | EUR 5,000,000 / EUR 100,000 per year |
| Life / discount rate | 15 years / 8% |
| Annualization factor | 365 |
| Benefit haircut / OPEX escalation | 2% / 2% per year |

The PV profile peaks at 5,800 kW — above the 5,000 kW connection — and prices run from
EUR 28/MWh at 06:00 to EUR 140/MWh at 19:00.

Validation reports 24 intervals of 1.0 h, dispatch hash
`76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491`, analysis hash
`c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8`.

## The schedule

| Hour | PV | Price | PV exp | PV chg | Batt exp | Curt | SOC end | Market value |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00:00–05:00 | 0 | 45→30 | 0 | 0 | 0 | 0 | 10,000.0 | 0.000 |
| 06:00 | 200 | 28 | 0 | 200 | 0 | 0 | 10,192.0 | 0.000 |
| 07:00 | 800 | 30 | 0 | 800 | 0 | 0 | 10,960.0 | 0.000 |
| 08:00 | 1,800 | 35 | 0 | 1,800 | 0 | 0 | 12,688.0 | 0.000 |
| 09:00 | 3,200 | 40 | 0 | 3,200 | 0 | 0 | 15,760.0 | 0.000 |
| 10:00 | 4,500 | 45 | 2,725 | 1,775 | 0 | 0 | 17,464.0 | 122.625 |
| 11:00 | 5,200 | 50 | 5,000 | 200 | 0 | 0 | 17,656.0 | 250.000 |
| 12:00 | 5,800 | 55 | 5,000 | 800 | 0 | 0 | 18,424.0 | 275.000 |
| 13:00 | 5,600 | 50 | 5,000 | 600 | 0 | 0 | 19,000.0 | 250.000 |
| 14:00 | 5,000 | 45 | 5,000 | 0 | 0 | 0 | 19,000.0 | 225.000 |
| 15:00 | 4,000 | 48 | 4,000 | 0 | 0 | 0 | 19,000.0 | 192.000 |
| 16:00 | 2,600 | 60 | 2,600 | 0 | 0 | 0 | 19,000.0 | 156.000 |
| 17:00 | 1,200 | 80 | 1,200 | 0 | 0 | 0 | 19,000.0 | 96.000 |
| 18:00 | 300 | 110 | 300 | 0 | 0 | 0 | 19,000.0 | 33.000 |
| 19:00 | 0 | 140 | 0 | 0 | 5,000 | 0 | 13,791.7 | 700.000 |
| 20:00 | 0 | 125 | 0 | 0 | 3,640 | 0 | 10,000.0 | 455.000 |
| 21:00–23:00 | 0 | 90→50 | 0 | 0 | 0 | 0 | 10,000.0 | 0.000 |

One charge, one discharge, ending exactly where it started.

## Reconciling the energy

Every published figure can be rebuilt from the schedule. Doing this once on a scenario you
care about is the best way to be sure you have understood the conventions.

**PV allocation.** PV export sums to 30,825 kWh and PV charge to 9,375 kWh:

```text
30,825 + 9,375 + 0 curtailed = 40,200 kWh = 40.2 MWh   (= pv_energy_mwh)
```

**Into the battery.** 9,375 kWh AC charged at 96%:

```text
9,375 x 0.96 = 9,000 kWh DC stored
```

**Out of the battery.** 8,640 kWh AC discharged (5,000 + 3,640) at 96%:

```text
8,640 / 0.96 = 9,000 kWh DC removed
```

The two DC figures match exactly, which is the terminal-SOC constraint doing its job: SOC
ends at 10,000 kWh, where it began.

**Equivalent full cycles.**

```text
9,000 kWh DC / 20,000 kWh capacity = 0.45   (= equivalent_full_cycles)
```

**Degradation reserve.** Charged on DC energy, not AC:

```text
9,000 kWh DC x EUR 10/MWh / 1,000 = EUR 90.00   (= degradation_cost_eur)
```

**Export energy.**

```text
30,825 PV + 8,640 battery = 39,465 kWh = 39.465 MWh   (= export_energy_mwh)
```

## Reconciling the value

**The baseline.** A PV-only plant exports `min(PV, 5,000)` at non-negative prices:

| Hour | Export | Price | Value |
| --- | ---: | ---: | ---: |
| 06:00 | 200 | 28 | 5.60 |
| 07:00 | 800 | 30 | 24.00 |
| 08:00 | 1,800 | 35 | 63.00 |
| 09:00 | 3,200 | 40 | 128.00 |
| 10:00 | 4,500 | 45 | 202.50 |
| 11:00 | 5,000 | 50 | 250.00 |
| 12:00 | 5,000 | 55 | 275.00 |
| 13:00 | 5,000 | 50 | 250.00 |
| 14:00 | 5,000 | 45 | 225.00 |
| 15:00 | 4,000 | 48 | 192.00 |
| 16:00 | 2,600 | 60 | 156.00 |
| 17:00 | 1,200 | 80 | 96.00 |
| 18:00 | 300 | 110 | 33.00 |
| | | | **1,900.10** |

matching `baseline_market_value_eur: 1900.1`. The baseline curtails 200 + 800 + 600 =
1,600 kWh = 1.6 MWh, matching `baseline_curtailed_energy_mwh`.

**The optimised plant.** Summing the market value column: EUR 2,754.625.

**The increment.**

```text
operating value    = 2,754.625 - 90.000 = 2,664.625
incremental value  = 2,664.625 - 1,900.100 = EUR 764.525   (per modelled day)
```

## Where the EUR 764.525 comes from

Two value streams, and it is worth separating them:

**Clipping recovery.** 1,600 kWh the baseline would have thrown away at 11:00–13:00 is
stored and sold later. Optimised curtailment is 0 MWh against the baseline's 1.6 MWh, a
100% reduction.

**Time shifting.** 7,775 kWh of PV that the baseline would have exported in the morning at
EUR 28–45/MWh is stored and sold at EUR 125–140/MWh instead, less round-trip losses and the
EUR 10/MWh reserve.

The second is the larger stream, and it is why the morning hours sell nothing at all
despite an open connection.

## The economics

```text
annualized benefit = 764.525 x 365 = EUR 279,051.625

year 1  = 279,051.625 x 1.0000 - 100,000 x 1.0000 = 179,051.625
year 2  = 279,051.625 x 0.9800 - 100,000 x 1.0200 = 171,470.5925
year 3  = 279,051.625 x 0.9604 - 100,000 x 1.0404 = 163,961.18065
...
year 15 = 78,357.13
```

which are the first entries of `cash_flows_eur` exactly.

| Metric | Value |
| --- | ---: |
| NPV at 8% | EUR -3,818,737.08 |
| IRR | -11.25% |
| Simple payback | not reached |
| Discounted payback | not reached |
| LCOS | EUR 265.97/MWh |

Both solver phases reported `optimal` with an achieved MIP gap of 0.0.

## Reading this result honestly

**It does not pay, and that is the point.** EUR 279,052 a year against EUR 5,000,000 of
CAPEX and EUR 100,000 of OPEX was never going to. The repository states plainly that the
negative NPV is intentional evidence that the software reports its assumptions rather than
forcing a favourable conclusion.

**The annualization is a demonstration, not an analysis.** Multiplying one synthetic summer
day by 365 asserts that every day of the year has this PV profile and this price shape.
December does not. The factor is the largest lever in the entire calculation and it is
doing all the work here.

**The dispatch is a perfect-foresight upper bound.** The optimiser knew at 06:00 that
19:00 would clear at EUR 140/MWh. A real operator bidding into a day-ahead market with
uncertainty earns less.

**The data is synthetic.** Both series were invented for this repository. Nothing here is
evidence about any real site.

What the example *is* good for: understanding the mechanics, checking an installation
against published anchors, and having a reconciliation you can follow line by line before
attempting the same on data that matters.

## What to change first on real data

1. Replace both series with a real, licensed year — or a genuinely representative period,
   with the annualization factor set to match.
2. Scope `capex_eur` and `annual_fixed_opex_eur` to the battery increment alone.
3. Take the SOC window and the efficiencies from the vendor datasheet, as two directional
   values.
4. Decide whether the 2% benefit haircut is what you mean, or whether you want physical
   capacity fade instead — see [chapter 20](20-degradation-multi-year.md).
