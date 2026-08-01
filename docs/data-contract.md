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
- terminal SOC defaults to initial SOC when omitted; financial evaluation requires equality until explicit inventory valuation is implemented.

If only round-trip efficiency is known, it must not be copied into both directional fields. A derived split such as the square root requires an explicit documented assumption.

## Financial convention

- cash flows are nominal EUR, unlevered, and pre-tax;
- CAPEX occurs at time zero;
- annual operating benefits occur at each year end;
- the discount and escalation rates are fractions, not percentages;
- `annualization_factor` explicitly scales the modeled period to one year;
- `annual_benefit_degradation_fraction` is a financial haircut on incremental operating value only; it is not a battery capacity-fade model and does not alter LCOS energy;
- IRR is returned only for a conventional cash-flow sequence with exactly one sign change.

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
