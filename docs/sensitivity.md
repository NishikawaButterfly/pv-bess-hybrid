# Sensitivity analysis

`pv-bess sensitivity` reruns one scenario through the unchanged dispatch and finance kernel, changing exactly one parameter per run. It answers questions of the form "what happens to NPV if prices are 20% lower" without editing scenario files by hand. The equations are exactly those in [methodology.md](methodology.md); this layer only rewrites the validated scenario and solves it again.

## Spec format

The spec is a small JSON file. Each supported parameter maps to either a list of multipliers applied to the base value or a list of absolute replacement values:

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

| Parameter | Changes | Modes |
| --- | --- | --- |
| `market_price_level` | every market price in the series | multipliers only |
| `energy_capacity_kwh` | battery DC energy capacity | multipliers or values |
| `power_kw` | AC charge and discharge power limits together | multipliers or values |
| `charge_efficiency` | battery charge efficiency | multipliers or values |
| `discharge_efficiency` | battery discharge efficiency | multipliers or values |
| `degradation_cost_eur_per_mwh_dc_discharged` | degradation reserve price | multipliers or values |

The layer is one-at-a-time by design: every run changes a single parameter and there are no combination grids. At most 32 runs, including the base case, are accepted per spec. Unknown parameters, duplicate values, nonpositive multipliers, and variants that produce an invalid scenario (for example, an efficiency above one) are rejected with a clear error before anything is solved.

## Running it

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity
```

This writes `sensitivity.json` and a flat `sensitivity.csv` with one row per run. Every run records its own dispatch-input and analysis-input SHA-256 using the same canonical serialization as `pv-bess run`, so any single variant can be reproduced and checked as a standalone run; the base row's hashes match a plain `run` of the same scenario byte for byte. Existing output files are not overwritten unless you pass `--force`.

## Worked example

The bundled spec above against the bundled 24-hour sample produces seven runs. Values are rounded here for reading; the artifacts hold full precision.

| Run | Market value (EUR) | NPV (EUR) | IRR | LCOS (EUR/MWh) |
| --- | ---: | ---: | ---: | ---: |
| base | 2,754.63 | -3,818,737 | -0.112 | 265.97 |
| `market_price_level*0.8` | 2,203.70 | -4,297,302 | -0.171 | 259.02 |
| `market_price_level*1.2` | 3,305.55 | -3,340,173 | -0.074 | 272.93 |
| `energy_capacity_kwh*0.5` | 2,400.80 | -4,683,502 | — | 476.07 |
| `energy_capacity_kwh*1.5` | 3,039.29 | -3,147,639 | -0.061 | 197.06 |
| `degradation_cost_eur_per_mwh_dc_discharged=0` | 2,754.63 | -3,566,721 | -0.091 | 255.56 |
| `degradation_cost_eur_per_mwh_dc_discharged=20` | 2,754.62 | -4,070,753 | -0.139 | 276.39 |

How to read this, honestly:

- The sample is a synthetic demonstration day annualized by 365, and no variant makes it profitable; every NPV stays negative and no run ever recovers CAPEX, so both payback columns are empty throughout.
- The IRR cell for `energy_capacity_kwh*0.5` is empty because the bounded IRR search finds no root in its `[-0.95, 10]` domain.
- Battery-size variants change dispatch only. CAPEX and OPEX stay at their base values, so a capacity multiplier compares a differently sized battery at the same cost, not a cost-scaled resizing.
- LCOS is a cost metric, not a value metric: at `market_price_level*0.8` the LCOS falls (cheaper charging) while the NPV worsens by about EUR 479,000. Read NPV and LCOS together.

## Limitations

Combined effects are not additive; changing two parameters at once requires editing the scenario. Financial-only parameters such as CAPEX and the discount rate are not in the sensitivity set yet. Results remain scenario calculations, not forecasts or investment advice.
