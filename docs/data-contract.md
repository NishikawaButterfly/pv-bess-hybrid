# Data contract

## Scenario JSON

The root object requires:

- `schema_version`: currently `1.0`;
- `name`: non-blank scenario name;
- `time_series_csv`: relative companion path that cannot escape the scenario directory;
- `dataset`: provenance and currency metadata;
- `battery`: AC power, DC energy, SOC, efficiency, and degradation-reserve assumptions;
- `grid`: import/export limits and grid-charging feature flag;
- `financial`: explicit project and annualization assumptions.

Unknown properties and duplicate keys are rejected at every JSON object level. This prevents misspelled assumptions from falling back silently. Additive contract changes require a schema update and coordinated reader change; incompatible changes require a new schema version.

## Time-series CSV

The header and order are exact:

| Column | Type | Unit | Rule |
| --- | --- | --- | --- |
| `timestamp` | ISO 8601 string | explicit UTC offset | interval start; unique, increasing, uniform, gap-free |
| `pv_power_kw` | finite number | kW AC | greater than or equal to zero |
| `market_price_eur_per_mwh` | finite number | EUR/MWh | negative values are allowed |

The interval duration is inferred in UTC from the first two timestamps. The last row represents an interval with the same duration as its predecessors. At least two and at most 100,000 rows are accepted.

## Battery convention

- `energy_capacity_kwh`: nominal DC stored energy;
- charge/discharge power: AC-side magnitude at the modeled bus;
- SOC limits: fractions of nominal DC capacity;
- charge efficiency: AC charging energy to stored DC energy;
- discharge efficiency: stored DC energy to exported AC energy;
- `degradation_cost_eur_per_mwh_dc_discharged`: economic reserve applied to DC energy removed from storage, not a physical degradation model;
- `calendar_fade_fraction_per_year` and `cycling_fade_fraction_per_efc`: optional multi-year usable-capacity fade as fractions of the original usable energy per year and per equivalent full cycle; zero (the default) reproduces earlier results and hashes exactly;
- `minimum_capacity_fraction`: validated capacity floor; financial evaluation fails with a clear error when the fade parameters imply crossing it within the project life;
- terminal SOC defaults to initial SOC when omitted; financial evaluation requires equality until explicit inventory valuation is implemented.

If only round-trip efficiency is known, it must not be copied into both directional fields. A derived split such as the square root requires an explicit documented assumption.

## Financial convention

- cash flows are nominal EUR, unlevered, and pre-tax;
- CAPEX occurs at time zero;
- annual operating benefits occur at each year end;
- the discount and escalation rates are fractions, not percentages. `discount_rate_fraction` accepts `[-0.95, 10]` for numerical conditioning and because IRR is searched over the same interval; a value above `1.0` is almost always a percentage typed as a fraction, so it is reported as a warning rather than refused. Rates above 100% remain legal and are calculated as given;
- `annualization_factor` explicitly scales the modeled period to one year;
- `annual_benefit_degradation_fraction` is a financial haircut on incremental operating value only; it is not a battery capacity-fade model and does not alter LCOS energy. Physical fade is the battery's fade parameters, which scale each year's benefit, variable cost, and discharged energy together;
- IRR is returned only for a conventional cash-flow sequence with exactly one sign change.

## Warnings

Some inputs are inside their validated domain yet are almost certainly mistyped. Rejecting them would be wrong, because the same values are occasionally intended; staying silent is what produced a confident wrong answer. Such inputs are reported as warnings.

Warnings are generated once, in the financial kernel, and carried on the result. Every surface reads the same list, so the text cannot diverge between them:

| Surface | Where the warnings appear |
| --- | --- |
| `pv-bess run` | `warning:` lines on stdout, before the artifact paths |
| `summary.json` | `financial_summary.warnings`, always present, empty when there are none |
| HTTP API | `financial_summary.warnings` of the `/api/v1/dispatch` response |
| `pv-bess sensitivity` | `warning:` lines on stdout, and `warnings` in `sensitivity.json` |
| `export-xlsx` | A `Warnings` section on the Summary sheet, present only when non-empty |

A warning never changes a calculated value, never changes either provenance hash, and never fails a run. The current list is:

| Condition | Warning |
| --- | --- |
| `discount_rate_fraction` above `1.0` | The rate was read as a percentage per year; a percentage was probably typed as a fraction |

## Limits

| Resource | Limit |
| --- | ---: |
| Scenario JSON | 1 MB |
| Time-series CSV | 25 MB |
| Intervals | 100,000 |
| Interval duration | 24 hours |
| Default solve time | 60 seconds |

Finite numeric values are also bounded for conditioning: power at 1 billion kW, stored energy at 1 trillion kWh, absolute price/degradation cost at EUR 1 million/MWh, monetary inputs at EUR 1 quadrillion, project life at 100 years, and annualization at 1 million. These are safety ceilings, not statements about realistic project scale.

The CLI does not silently overwrite `summary.json` or `dispatch.csv`. Both artifacts include the dispatch and complete-analysis SHA-256 values, are fully staged before publication, and restore the prior pair if a replace operation fails. Fixed-path replacement of multiple files is not guaranteed to survive a process or host crash atomically; consumers must compare the embedded hashes before accepting a pair.
