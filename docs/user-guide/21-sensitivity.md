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
    "energy_capacity_kwh": { "multipliers": [0.5, 1.5] },
    "degradation_cost_eur_per_mwh_dc_discharged": { "values": [0, 20] }
  }
}
```

Each parameter takes either `multipliers` (relative to the base value) or `values`
(absolute), never both. Six parameters are supported:

| Parameter | Changes | Modes |
| --- | --- | --- |
| `market_price_level` | every price in the series | multipliers only |
| `energy_capacity_kwh` | battery DC energy capacity | either |
| `power_kw` | charge **and** discharge power together | either |
| `charge_efficiency` | charge efficiency | either |
| `discharge_efficiency` | discharge efficiency | either |
| `degradation_cost_eur_per_mwh_dc_discharged` | the degradation reserve | either |

At most 32 runs including the base. Unknown parameters, duplicates, non-positive
multipliers, and variants producing an invalid scenario are all rejected before anything is
solved, and the message lists what is supported:

```text
error: unknown sensitivity parameter 'capex_eur'; supported parameters: charge_efficiency,
degradation_cost_eur_per_mwh_dc_discharged, discharge_efficiency, energy_capacity_kwh,
market_price_level, power_kw
```

## Running it

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity
```

Seven runs completed in 2.4 seconds on the reference machine. Two files are written:
`sensitivity.json` and a flat `sensitivity.csv` with one row per run.

The base row's hashes match a plain `run` of the same scenario exactly — verified:
`76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491`. Every variant carries
its own pair of hashes, so any single row can be reproduced as a standalone run.

`sensitivity.json` also carries a `warnings` array. The financial assumptions are shared by
every run — no supported parameter varies them — so a warning describes the whole table and
is stored once beside it rather than repeated on each row.

## Reading the shipped example

| Run | Market value | NPV | IRR | LCOS |
| --- | ---: | ---: | ---: | ---: |
| base | 2,754.63 | -3,818,737 | -0.112 | 265.97 |
| `market_price_level*0.8` | 2,203.70 | -4,297,302 | -0.171 | 259.02 |
| `market_price_level*1.2` | 3,305.55 | -3,340,173 | -0.074 | 272.93 |
| `energy_capacity_kwh*0.5` | 2,400.80 | -4,683,502 | — | 476.07 |
| `energy_capacity_kwh*1.5` | 3,039.29 | -3,147,639 | -0.061 | 197.06 |
| `degradation_cost...=0` | 2,754.63 | -3,566,721 | -0.091 | 255.56 |
| `degradation_cost...=20` | 2,754.62 | -4,070,753 | -0.139 | 276.39 |

Four readings, in order of how easily they are got wrong.

**LCOS and NPV move in opposite directions on price.** At 80% of prices, LCOS *improves* by
EUR 6.95/MWh while NPV *worsens* by EUR 479,000. Charging is cheaper; the project is worse.
This single row is the best argument in the product for never ranking scenarios by LCOS
alone.

**The capacity variants are not a sizing study.** They change the battery and hold CAPEX at
EUR 5,000,000. The `energy_capacity_kwh*1.5` row shows a 50% larger battery for free. To
size honestly, vary capacity and CAPEX together in separate scenario files.

**An empty IRR cell is a real outcome.** The `energy_capacity_kwh*0.5` variant has no root
in the `[-0.95, 10]` domain. Both payback columns are empty in every row because no variant
recovers CAPEX. See [chapter 17](17-irr.md) and [chapter 18](18-payback.md).

**The degradation reserve barely moves market value and moves NPV by half a million.**
Market value goes from 2,754.63 to 2,754.62 across a EUR 0–20/MWh reserve, so the reserve
is not changing what the battery *does* — the price spread on this day survives EUR 20/MWh
— it is being subtracted from what the battery earns. On a scenario with thinner spreads,
market value would move too.

## What the layer is for, and what it is not

It is a **one-at-a-time** design. Every run changes exactly one parameter; there are no
combination grids. That is a deliberate scope choice and it has a consequence worth
stating: **effects are not additive.** You cannot read the price row and the capacity row
and infer what both together would do. For that, write the combined scenario and run it.

Two gaps to plan around:

**No financial parameters.** CAPEX, discount rate, project life, annualization factor, OPEX,
and the fade parameters are all outside the parameter set. Since CAPEX and the discount
rate are usually the two most uncertain inputs in an appraisal, this is the limitation you
will meet first. Vary them by editing scenario files and running `run` for each.

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
