# 5. Scenario configuration

A scenario is one JSON file with five blocks. This chapter walks through them in the order
you fill them in, and flags the fields whose meaning is not obvious from their name.

The repository's `sample-data/scenario.json` is the template to copy. It is a complete,
valid file describing a 5 MW PV plant with a 5 MW / 20 MWh battery.

## The root block

```json
{
  "schema_version": "1.0",
  "name": "Synthetic 5 MW PV plus 5 MW / 20 MWh BESS",
  "time_series_csv": "hourly.csv"
}
```

`schema_version` is currently `"1.0"` and any other value is rejected outright. It is a
string, not a number.

`name` is free text — but it is **part of the dispatch input hash**. Two scenarios
identical in every number but differing in name produce different hashes and therefore
count as different runs. This is intentional: the name is part of what a result claims to
be. It does mean that renaming a scenario invalidates any earlier hash you recorded,
without a single number having changed.

`time_series_csv` is the relative path to the companion CSV, resolved against the
scenario file's own directory and confined to it.

## The dataset block

```json
"dataset": {
  "name": "Deterministic synthetic summer-day profile",
  "source": "Created for repository tests and demonstration; not measured data",
  "license_id": "CC0-1.0",
  "timezone_name": "UTC",
  "currency": "EUR",
  "synthetic": true
}
```

This block is pure provenance — no number in it reaches the optimiser. Its value is that
it travels with the result and forces you to answer, in writing, where the data came from
and whether you are allowed to use it.

`timezone_name` is documentation of the series' native timezone. It does **not** convert
anything: the actual instants come from the UTC offsets in the CSV. Writing
`"Europe/Madrid"` here while the CSV carries `+00:00` offsets produces no error and no
conversion — only a misleading record.

`synthetic` defaults to `true`, which is the safe direction. Set it to `false` only for
genuinely measured data, and only when the licence permits its use.

## The battery block

Covered in detail in [battery parameters](06-battery-parameters.md). The minimum is three
fields:

```json
"battery": {
  "energy_capacity_kwh": 20000,
  "max_charge_power_kw": 5000,
  "max_discharge_power_kw": 5000
}
```

Everything else defaults. Be aware that accepting the defaults asserts a 0.95/0.95
efficiency pair, a 10–90% SOC window, a 50% start and end, and a zero degradation reserve.

## The grid block

Covered in [grid constraints](07-grid-constraints.md).

```json
"grid": {
  "export_limit_kw": 5000,
  "import_limit_kw": 0,
  "allow_grid_charging": false
}
```

The two flags interact: enabling `allow_grid_charging` with a zero import limit is
rejected, because it would be a contradiction rather than a harmless combination.

```text
error: import_limit_kw must be positive when grid charging is enabled
```

## The financial block

```json
"financial": {
  "capex_eur": 5000000,
  "annual_fixed_opex_eur": 100000,
  "project_life_years": 15,
  "discount_rate_fraction": 0.08,
  "annualization_factor": 365,
  "annual_benefit_degradation_fraction": 0.02,
  "annual_opex_escalation_fraction": 0.02
}
```

Four fields deserve individual attention.

### `capex_eur` and `annual_fixed_opex_eur` are the battery's, not the plant's

The model compares your configured plant against a PV-only baseline, so every benefit it
computes is the battery's incremental contribution. The costs must be scoped the same way:
the battery system, its power conversion, its installation, its grid works if attributable,
and its own fixed O&M.

Entering the whole project's CAPEX here compares a full-plant cost against a battery-only
benefit. The result is a large negative NPV that means nothing. Nothing in the software can
detect the mismatch.

CAPEX occurs at time zero and is not discounted. There is no construction schedule, no
drawdown profile, and no interest during construction.

### `annualization_factor` is your assertion, not a calculation

This scales the modelled period to one year. The model will not infer it — a 24-hour
scenario with the default factor of 1.0 is treated as a project whose entire annual benefit
is one day's worth.

| Modelled period | Factor asserting a full year |
| --- | ---: |
| 24 hours | 365 |
| 744 hours (a 31-day month) | 8760 / 744 ≈ 11.774 |
| 2,190 hours (a quarter) | 4 |
| 8,760 hours | 1 |

The factor is an assertion that your period is representative of every period in the year.
For a single summer day that assertion is plainly false, and the repository says so about
its own sample. State the factor and its justification wherever you quote an annual number.

### `discount_rate_fraction` is a fraction

`0.08` is 8%. `8` is 800%, and it is accepted — the accepted range is `[-0.95, 10]` — but
any value above `1.0` is reported as a warning by `validate`, by `run`, in `summary.json`,
and in the API response. See
[the data contract chapter](04-data-contract-in-practice.md#a-discount-rate-entered-as-a-percentage)
for what that does to the output and why it warns instead of refusing.

### `annual_benefit_degradation_fraction` is not battery ageing

This is a **financial haircut** on the incremental operating value: year *n* earns
`(1 - fraction)^(n-1)` of year one. It compounds, and it does not touch LCOS.

It is not a capacity-fade model. Physical fade lives in the battery block's
`calendar_fade_fraction_per_year` and `cycling_fade_fraction_per_efc`, which scale benefit,
variable cost, and discharged energy together. Using the financial haircut when you mean
physical fade produces an NPV that falls while LCOS stays put — internally inconsistent,
and hard to defend in review. [Degradation and the multi-year run](20-degradation-multi-year.md)
covers the distinction with worked numbers.

If you set both, they compound. That is rarely what anyone intends.

## The one-day build

A workable order for a new scenario:

1. Copy `sample-data/scenario.json` and its CSV into a new directory.
2. Replace the CSV with yours; run `pv-bess validate` and check `interval_count` and
   `interval_hours`.
3. Set the grid limits to the real connection agreement.
4. Set battery capacity, power, and the two efficiencies from the vendor datasheet.
5. Set the SOC window to the warranty's operating range.
6. Set the degradation reserve, or set it to zero and say so.
7. Set the annualization factor to match your period.
8. Set CAPEX and OPEX for the battery increment only.
9. Set the discount rate as a fraction, and check it is below 1.
10. Run, and read `pv_energy_mwh` against your yield study before reading anything else.

## Keeping scenarios organised

There is no scenario library, no database, and no run index. A run directory holds
`summary.json` and `dispatch.csv` and nothing that points back to the scenario file that
produced it, other than the hashes.

The practical habit is one directory per scenario containing the JSON, the CSV, and the
run output, with the dispatch hash recorded wherever the result is quoted. Anything more
organised than that, you build yourself.
