# Sensitivity analysis

`pv-bess sensitivity` reruns one scenario through the unchanged dispatch and finance kernel, changing exactly one parameter per run. It answers questions of the form "what happens to NPV if prices are 20% lower" without editing scenario files by hand. The equations are exactly those in [methodology.md](methodology.md); this layer only rewrites the validated scenario and solves it again.

## Spec format

The spec is a small JSON file. Each supported parameter maps to either a list of multipliers applied to the base value or a list of absolute replacement values:

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

| Parameter | Changes | Modes |
| --- | --- | --- |
| `market_price_level` | every market price in the series | multipliers only |
| `energy_capacity_kwh` | battery DC energy capacity, with CAPEX derived from `capex_eur_per_kwh` | multipliers or values |
| `power_kw` | AC charge and discharge power limits together | multipliers or values |
| `charge_efficiency` | battery charge efficiency | multipliers or values |
| `discharge_efficiency` | battery discharge efficiency | multipliers or values |
| `degradation_cost_eur_per_mwh_dc_discharged` | degradation reserve price | multipliers or values |
| `capex_eur` | project CAPEX in the financial evaluation | multipliers or values |
| `discount_rate_fraction` | the discount rate in the financial evaluation | multipliers or values |

Note that `degradation_cost_eur_per_mwh_dc_discharged` varies the per-MWh degradation reserve inside the dispatch objective only. It is distinct from the multi-year capacity fade parameters (`calendar_fade_fraction_per_year`, `cycling_fade_fraction_per_efc`), which scale later project years in the financial layer and are not part of the sensitivity set.

Two of the parameters deserve their own rules:

- **`capex_eur` and `discount_rate_fraction` do not enter the dispatch optimization.** Their variants share the base solve: the row keeps the base `dispatch_input_sha256`, saying openly that the dispatch is the same result, while `analysis_input_sha256` and the financial metrics move. Nothing is re-solved for effect.
- **`energy_capacity_kwh` requires `capex_eur_per_kwh` on its entry** — the marginal cost of capacity, in EUR per kWh, applied to each variant's capacity delta against the base battery. A capacity variant without it is refused, because a resized battery that inherits the base CAPEX prices every size the same and biases every sizing conclusion toward the larger battery. The derived CAPEX of each variant is reported on its row. The declared cost is a linear model of capacity cost; if your quotes are not linear in kWh, write the sizes as separate scenarios instead. A declared `0` is accepted as an explicit statement that extra capacity is free — it knowingly reinstates the fixed-cost comparison, so reserve it for capacity that is genuinely sunk.

The layer is one-at-a-time by design: every run changes a single axis — a capacity variant carries its derived CAPEX with it — and there are no combination grids. At most 32 runs, including the base case, are accepted per spec. Unknown parameters, duplicate values, nonpositive multipliers, capacity variants without a declared cost, and variants that produce an invalid scenario (for example, an efficiency above one) are rejected with a clear error before anything is solved.

## Running it

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity
```

This writes `sensitivity.json` and a flat `sensitivity.csv` with one row per run. Every run records its own dispatch-input and analysis-input SHA-256 using the same canonical serialization as `pv-bess run`, so any single variant can be reproduced and checked as a standalone run; the base row's hashes match a plain `run` of the same scenario byte for byte. Each row also reports the `capex_eur` it was evaluated under and the kernel's `warnings` for its own assumptions, so a scanned value that crosses a plausibility threshold is flagged on the row that crossed it. Existing output files are not overwritten unless you pass `--force`.

## Worked example

The bundled spec above against the bundled 24-hour sample produces eleven runs. Values are rounded here for reading; the artifacts hold full precision.

| Run | Market value (EUR) | NPV (EUR) | IRR | LCOS (EUR/MWh) | CAPEX (EUR) |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 2,754.63 | -3,818,737 | -0.112 | 265.97 | 5,000,000 |
| `market_price_level*0.8` | 2,203.70 | -4,297,302 | -0.171 | 259.02 | 5,000,000 |
| `market_price_level*1.2` | 3,305.55 | -3,340,173 | -0.074 | 272.93 | 5,000,000 |
| `energy_capacity_kwh*0.5` | 2,400.80 | -2,183,502 | — | 290.84 | 2,500,000 |
| `energy_capacity_kwh*1.5` | 3,039.29 | -5,647,639 | -0.103 | 258.81 | 7,500,000 |
| `degradation_cost_eur_per_mwh_dc_discharged=0` | 2,754.63 | -3,566,721 | -0.091 | 255.56 | 5,000,000 |
| `degradation_cost_eur_per_mwh_dc_discharged=20` | 2,754.62 | -4,070,753 | -0.139 | 276.39 | 5,000,000 |
| `capex_eur*0.8` | 2,754.63 | -2,818,737 | -0.090 | 228.93 | 4,000,000 |
| `capex_eur*1.2` | 2,754.63 | -4,818,737 | -0.130 | 303.02 | 6,000,000 |
| `discount_rate_fraction=0.06` | 2,754.63 | -3,682,869 | -0.112 | 244.23 | 5,000,000 |
| `discount_rate_fraction=0.1` | 2,754.63 | -3,932,986 | -0.112 | 288.97 | 5,000,000 |

How to read this, honestly:

- The sample is a synthetic demonstration day annualized by 365, and no variant makes it profitable; every NPV stays negative and no run ever recovers CAPEX, so both payback columns are empty throughout.
- Capacity variants are priced at the declared 250 EUR/kWh, and the pricing decides the ranking: the half-size battery has the least negative NPV in the table and the 1.5x battery the most negative, even though the larger battery moves more energy. Under the previous fixed-cost behavior these two rows ranked the other way around.
- The IRR cell for `energy_capacity_kwh*0.5` is empty because its cash-flow sequence changes sign twice: after CAPEX, the operating flow starts positive and turns negative in year 14, when the 2%-per-year benefit degradation crosses the 2%-per-year OPEX escalation, so no unique conventional IRR exists.
- The financial rows (`capex_eur*`, `discount_rate_fraction=`) carry the base `dispatch_input_sha256`: the dispatch is the same result, not a new solve, and market value is identical by construction. The CAPEX rows move NPV euro for euro with the CAPEX delta, and the IRR column is constant across the discount-rate rows because IRR does not depend on the discount rate.
- LCOS is a cost metric, not a value metric: at `market_price_level*0.8` the LCOS falls (cheaper charging) while the NPV worsens by about EUR 479,000. Read NPV and LCOS together.

## Limitations

Combined effects are not additive; changing two parameters at once requires editing the scenario. `power_kw` variants still carry the base CAPEX unchanged — no per-kW marginal cost is declarable yet, so a power sweep compares differently rated batteries at the same price. OPEX, project life, the annualization factor, and the fade parameters are not in the sensitivity set. Results remain scenario calculations, not forecasts or investment advice.
