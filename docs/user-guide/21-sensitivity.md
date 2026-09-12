# 21. Sensitivity analysis

`pv-bess sensitivity` reruns one scenario through the unchanged kernel, changing exactly
one parameter per run. The [sensitivity reference](../sensitivity.md) covers the spec
format; this chapter is about using it and reading it.

## The spec

```json
{
  "schema_version": "1.0",
  "parameters": {
    "market_price_level": { "multipliers": [0.8, 1.2] },
    "energy_capacity_kwh": { "multipliers": [0.5, 1.5], "capex_eur_per_kwh": 250 },
    "degradation_cost_eur_per_mwh_dc_discharged": { "values": [0, 20] },
    "capex_eur": { "multipliers": [0.8, 1.2] },
    "discount_rate_fraction": { "values": [0.06, 0.1] }
  }
}
```

Each parameter takes either `multipliers` (relative to the base value) or `values`
(absolute), never both. Eight parameters are supported:

| Parameter | Changes | Modes |
| --- | --- | --- |
| `market_price_level` | every price in the series | multipliers only |
| `energy_capacity_kwh` | battery DC energy capacity **and** its derived CAPEX | either |
| `power_kw` | charge **and** discharge power together | either |
| `charge_efficiency` | charge efficiency | either |
| `discharge_efficiency` | discharge efficiency | either |
| `degradation_cost_eur_per_mwh_dc_discharged` | the degradation reserve | either |
| `capex_eur` | project CAPEX, financial evaluation only | either |
| `discount_rate_fraction` | the discount rate, financial evaluation only | either |

**A capacity sweep must declare what capacity costs.** The `energy_capacity_kwh` entry
requires `capex_eur_per_kwh`, the marginal cost of capacity: each variant's CAPEX is the
base CAPEX plus the capacity delta times that cost, and it is reported on the row. Without
the declaration the entry is refused:

```text
error: energy_capacity_kwh variants resize the battery while capex_eur stays at the base
value, so every size would carry the same capital cost; declare capex_eur_per_kwh (the
marginal cost of capacity, in EUR per kWh) on the energy_capacity_kwh entry so each
variant's CAPEX co-varies with its size
```

The declared cost is a linear model. If your quotes are not linear in kWh — they rarely
are, exactly — treat the swept rows as a first pass and price the shortlisted size as its
own scenario. A declared `0` is accepted as an explicit statement that extra capacity is
free; it knowingly reinstates the fixed-cost comparison, so reserve it for capacity that
is genuinely sunk.

At most 32 runs including the base. Unknown parameters, duplicates, non-positive
multipliers, and variants producing an invalid scenario are all rejected before anything is
solved, and the message lists what is supported:

```text
error: unknown sensitivity parameter 'project_life_years'; supported parameters:
capex_eur, charge_efficiency, degradation_cost_eur_per_mwh_dc_discharged,
discharge_efficiency, discount_rate_fraction, energy_capacity_kwh, market_price_level,
power_kw
```

## Running it

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity
```

Eleven runs completed in about two seconds on the reference machine — the financial rows
cost almost nothing, because they do not re-solve the dispatch. Two files are written:
`sensitivity.json` and a flat `sensitivity.csv` with one row per run.

The base row's hashes match a plain `run` of the same scenario exactly — verified:
`76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491`. Every physical variant
carries its own pair of hashes, so any single row can be reproduced as a standalone run. A
`capex_eur` or `discount_rate_fraction` row instead carries the **base**
`dispatch_input_sha256` — the dispatch is deliberately the same result, since neither
parameter enters the optimization — while its `analysis_input_sha256` and financial
metrics move.

`sensitivity.json` carries warnings at two levels. The `warnings` array beside the table
is the base case's judgment. Each row also carries its own `warnings`, produced by the
same kernel channel for the assumptions that row was evaluated under — which means a
mistyped input in the scenario itself appears beside the table *and* on every row, because
every row inherits the base assumptions, while a warning only a scanned value trips
appears on that row alone. On stdout the CLI prints the base case's warnings once,
unlabelled, and labels only what a scanned value introduced — so scanning
`discount_rate_fraction` across `2` prints:

```text
warning: discount_rate_fraction=2: discount_rate_fraction is 2, which the model read as
200% per year; a value above 1.0 is usually a percentage entered as a fraction, and 2%
would be 0.02. NPV, discounted payback, and LCOS use 200%.
```

## Reading the shipped example

| Run | Market value | NPV | IRR | LCOS | CAPEX |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 2,754.63 | -3,818,737 | -0.112 | 265.97 | 5,000,000 |
| `market_price_level*0.8` | 2,203.70 | -4,297,302 | -0.171 | 259.02 | 5,000,000 |
| `market_price_level*1.2` | 3,305.55 | -3,340,173 | -0.074 | 272.93 | 5,000,000 |
| `energy_capacity_kwh*0.5` | 2,400.80 | -2,183,502 | — | 290.84 | 2,500,000 |
| `energy_capacity_kwh*1.5` | 3,039.29 | -5,647,639 | -0.103 | 258.81 | 7,500,000 |
| `degradation_cost...=0` | 2,754.63 | -3,566,721 | -0.091 | 255.56 | 5,000,000 |
| `degradation_cost...=20` | 2,754.62 | -4,070,753 | -0.139 | 276.39 | 5,000,000 |
| `capex_eur*0.8` | 2,754.63 | -2,818,737 | -0.090 | 228.93 | 4,000,000 |
| `capex_eur*1.2` | 2,754.63 | -4,818,737 | -0.130 | 303.02 | 6,000,000 |
| `discount_rate_fraction=0.06` | 2,754.63 | -3,682,869 | -0.112 | 244.23 | 5,000,000 |
| `discount_rate_fraction=0.1` | 2,754.63 | -3,932,986 | -0.112 | 288.97 | 5,000,000 |

Six readings, in order of how easily they are got wrong.

**LCOS and NPV move in opposite directions on price.** At 80% of prices, LCOS *improves* by
EUR 6.95/MWh while NPV *worsens* by EUR 479,000. Charging is cheaper; the project is worse.
This single row is the best argument in the product for never ranking scenarios by LCOS
alone.

**The capacity ranking is decided by the declared cost, and it reverses the free-battery
story.** At 250 EUR/kWh the half-size battery is the least negative NPV in the table and
the 1.5x battery the most negative, even though the larger battery moves more energy —
2,400.80 versus 3,039.29 in market value. When capacity was swept with CAPEX held at
EUR 5,000,000, these two rows ranked the other way around, which is exactly the bias that
made fixed-cost capacity sweeps a lie: the extra energy is real, and so is the extra
EUR 2,500,000.

**The financial rows share the base dispatch, and say so.** Every `capex_eur*` and
`discount_rate_fraction=` row carries the base `dispatch_input_sha256` and the identical
market value of 2,754.63: neither parameter enters the optimization, so re-solving would
produce the same schedule and pretending otherwise would be theater. What moves is the
financial evaluation — NPV shifts euro for euro with CAPEX, and note the IRR column is
constant at -0.112 across both discount-rate rows, because IRR is the rate at which NPV
is zero and does not depend on the rate you discount at.

**An empty IRR cell is a real outcome.** The `energy_capacity_kwh*0.5` cash-flow sequence
changes sign twice — the operating flow starts positive and turns negative in year 14,
when the 2%-per-year benefit degradation crosses the 2%-per-year OPEX escalation — so no
unique conventional IRR exists. Both payback columns are empty in every row because no
variant recovers CAPEX. See [chapter 17](17-irr.md) and [chapter 18](18-payback.md).

**The degradation reserve barely moves market value and moves NPV by half a million.**
Market value goes from 2,754.63 to 2,754.62 across a EUR 0–20/MWh reserve, so the reserve
is not changing what the battery *does* — the price spread on this day survives EUR 20/MWh
— it is being subtracted from what the battery earns. On a scenario with thinner spreads,
market value would move too.

**A scanned value can carry its own warning.** The table above is clean. A scanned
`discount_rate_fraction` above `1.0` is flagged by the same kernel channel as everywhere
else, on the row that crossed the threshold, and printed by the CLI labelled with the
variant. A warning the scenario's own assumptions already trip — a mistyped opex
escalation, say — sits beside the table and on every row, since every row inherits the
base assumptions, and is printed once on stdout. A sweep never silences a warning the
equivalent standalone run would have raised.

## Reading a retained schedule

A row says *that* a variant differs. Its schedule says *why*. Run the bundled spec again with
`--retain-schedules`:

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity-schedules \
  --retain-schedules
```

A new output directory, because the one from the first run already holds a table and
would be refused without `--force`. The command prints one more line, `sensitivity_schedules:` followed by the directory, and
`schedules/` holds eleven files, one per row. Each is the `dispatch.csv` that a standalone
`run` of that row's scenario and assumptions would write at the same solver settings,
named by the row's analysis hash;
every row names its own in `schedule_file`.

Take the row whose NPV departs furthest from the base: `energy_capacity_kwh*1.5`, at
EUR -5,647,639 against the base's -3,818,737. Its `schedule_file` is
`schedules/200262c3f93a4bc21986f0055cc2f6b4c20c28b9d706a690f20a9011a3dbf88e.csv`. The base's is
`schedules/c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8.csv`, named by the analysis hash every
plain `run` of the sample reports. Twenty of the twenty-four hours carry the same flows in
both files. These are the other four, from inside `results/sensitivity-schedules`:

```text
$ head -1 schedules/c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8.csv | cut -d, -f3,6,8,10,14
timestamp,market_price_eur_per_mwh,pv_charge_kw,battery_export_kw,soc_end_kwh
$ grep -E "T(10|14|18|20):00" schedules/c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8.csv | cut -d, -f3,6,8,10,14
2026-06-15T10:00:00+00:00,45.0,1774.9999999999986,0.0,17464.0
2026-06-15T14:00:00+00:00,45.0,0.0,0.0,19000.0
2026-06-15T18:00:00+00:00,110.0,0.0,0.0,19000.0
2026-06-15T20:00:00+00:00,125.0,0.0,3639.9999999999995,10000.0
$ grep -E "T(10|14|18|20):00" schedules/200262c3f93a4bc21986f0055cc2f6b4c20c28b9d706a690f20a9011a3dbf88e.csv | cut -d, -f3,6,8,10,14
2026-06-15T10:00:00+00:00,45.0,1462.4999999999977,0.0,22163.999999999996
2026-06-15T14:00:00+00:00,45.0,5000.0,0.0,28499.999999999996
2026-06-15T18:00:00+00:00,110.0,0.0,2959.9999999999964,25416.666666666668
2026-06-15T20:00:00+00:00,125.0,0.0,5000.0,15000.0
```

The files keep full float precision, so `1774.9999999999986` is 1,775 kW. Across the day:

| Over the day | base | `energy_capacity_kwh*1.5` |
| --- | ---: | ---: |
| PV charged | 9.375 MWh | 14.0625 MWh |
| Battery discharged | 8.64 MWh | 12.96 MWh |
| Hours charging / discharging | 8 / 2 | 9 / 3 |
| Highest state of charge | 19,000 kWh | 28,500 kWh |
| Market value | EUR 2,754.63 | EUR 3,039.29 |
| Degradation reserve | EUR 90.00 | EUR 135.00 |
| Operating value | EUR 2,664.63 | EUR 2,904.29 |

**Four hours carry the whole difference.** At 14:00 the base battery is already at
19,000 kWh, its 95% ceiling, and charges nothing. The larger battery takes 5,000 kW of PV
that would otherwise have been exported at EUR 45 (the sample does not charge from the
grid) and ends the hour at its own ceiling of 28,500 kWh. It spends that energy in the
evening: 2,960 kW at 18:00, when the base battery is idle, and the full 5,000 kW at 20:00,
where the base battery gives 3,640 kW. Each ends 20:00 at the state of charge it must also
end the day with, 10,000 kWh and 15,000 kWh. The larger battery also takes 312.5 kW less
at 10:00. That is one more charging hour, one more discharging hour, 4.32 MWh more
discharged, and EUR 284.66 more market value a day. The degradation reserve rises too,
from EUR 90 to 135, all of it at 18:00 and 20:00, so the day's operating value, which is
what the NPV is built on, rises by EUR 239.66.

**The table says it does not pay; the schedule says what it does.** At the declared
250 EUR/kWh the extra 10 MWh add EUR 2,500,000 of CAPEX, and EUR 239.66 a day of operating
value does not earn that back over the project life, hence the EUR 1,828,902 fall in NPV. The schedule
shows where the gain comes from, and why it is small: both batteries already discharge
the full 5,000 kW at 19:00, the day's highest price at EUR 140, so the extra capacity only
reaches the hours either side of it, 18:00 at EUR 110 and 20:00 at EUR 125, with PV that
would have sold for EUR 45 at 14:00. The case for a larger battery turns on those shoulder prices, not on
the peak.

For a financial-only row the schedule is the base's dispatch under that row's analysis hash:
compare its file with the base's and only the `analysis_input_sha256` column differs.

## What the layer is for, and what it is not

It is a **one-at-a-time** design. Every run changes exactly one axis — a capacity variant
carries its derived CAPEX with it, by declaration — and there are no
combination grids. That is a deliberate scope choice and it has a consequence worth
stating: **effects are not additive.** You cannot read the price row and the capacity row
and infer what both together would do. For that, write the combined scenario and run it.

Three gaps to plan around:

**Not every financial parameter.** `capex_eur` and `discount_rate_fraction` — usually the
two most uncertain inputs in an appraisal — are in the set. Project life, the
annualization factor, OPEX, and the fade parameters are not; vary those by editing
scenario files and running `run` for each.

**Power is not cost-priced.** `power_kw` variants carry the base CAPEX unchanged — there
is no per-kW marginal cost to declare — so a power sweep compares differently rated
batteries at the same price, with exactly the bias the capacity axis used to have. Read
those rows as operational, not financial, comparisons.

**No grid parameters.** `export_limit_kw` and `import_limit_kw` are not in the set either,
so the common "would a battery let us accept a smaller connection" study is manual.

## Getting value from 32 runs

**Scan the parameter you are least sure of, not the one that is easiest.** Price level is
the default choice and often the least informative — the response is close to linear and
you could have estimated it. The efficiency split, by contrast, is genuinely
non-obvious: two scenarios with identical round-trip efficiency differ by 4.7% in
incremental value (see [chapter 8](08-efficiencies.md)), and `charge_efficiency` and
`discharge_efficiency` are both in the set.

**Use `values` rather than `multipliers` for physical parameters.** Vendor quotes come as
absolute numbers, and `{"values": [0.92, 0.94, 0.96]}` is easier to trace back to a
datasheet than a multiplier.

**Bracket, do not scan.** With 31 variants available, three well-chosen points on each of
several parameters is more useful than 31 points on one.

**Read the whole row.** Each run reports market value, NPV, IRR, both paybacks, and LCOS.
A variant that improves one and worsens another is telling you something about the
scenario's structure, and it is the reason to keep all six columns rather than plotting
one.
