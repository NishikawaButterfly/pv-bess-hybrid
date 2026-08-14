# 4. The data contract in user terms

The [data contract](../data-contract.md) is the normative schema. This chapter is about
living with it: what the validator is trying to protect you from, where it succeeds, and
the two places where a scenario passes validation and still fails.

## The design principle: no silent fallback

The reader rejects anything it does not recognise, at every level of the JSON object. A
misspelled key is an error, not a silently ignored line that leaves a default in place.

```text
error: unknown financial key(s): discount_rate
error: unknown battery key(s): round_trip_efficiency
error: unknown scenario key(s): notes
```

This is deliberate and worth appreciating. In a model where `discount_rate_fraction`
defaults to nothing and `charge_efficiency` defaults to 0.95, a tolerant reader would let
`discount_rate` sit in the file looking authoritative while the calculation used something
else entirely. Here, the file cannot lie to you about which assumptions were used.

Duplicate keys are caught for the same reason — JSON parsers normally keep the last one
silently:

```text
error: duplicate JSON key: name
```

The cost is that you cannot leave comments, notes, or extra metadata in the scenario file.
There is no free-text field beyond `dataset.source`, and anything else you add will be
rejected.

## Two files, one unit

A scenario is always a pair: the JSON and the CSV it names in `time_series_csv`. The path
must be relative and must stay inside the scenario's own directory.

```text
error: time_series_csv must be a relative path
error: time_series_csv must stay inside the scenario directory
```

A missing companion reports the resolved absolute path, which is usually enough to see the
mistake immediately:

```text
error: cannot access C:\...\json-missing-csv\nowhere.csv: [WinError 2] The system cannot
find the file specified
```

Keep the pair in one directory and copy them together. Every hash and every result depends
on both.

## Required, defaulted, and forbidden

Only a handful of fields are genuinely required. The rest carry defaults — and knowing
which is which matters, because an omitted field is an accepted assumption.

| Block | Required | Defaulted |
| --- | --- | --- |
| root | `schema_version`, `name`, `time_series_csv`, `dataset`, `battery`, `grid`, `financial` | — |
| `dataset` | `name`, `source`, `license_id`, `timezone_name` | `currency` = `"EUR"`, `synthetic` = `true` |
| `battery` | `energy_capacity_kwh`, `max_charge_power_kw`, `max_discharge_power_kw` | SOC window 0.10–0.90, initial 0.50, terminal = initial, both efficiencies 0.95, degradation reserve 0, all three fade parameters 0 |
| `grid` | `export_limit_kw` | `import_limit_kw` = 0, `allow_grid_charging` = `false` |
| `financial` | `capex_eur`, `annual_fixed_opex_eur`, `project_life_years`, `discount_rate_fraction` | `annualization_factor` = 1.0, benefit degradation 0, opex escalation 0 |

The defaults most likely to catch you out are the **battery efficiencies at 0.95 each** —
a 90.25% round trip that you may not have intended to assert — and the
**`annualization_factor` of 1.0**, which means a modelled day is treated as the project's
entire year unless you say otherwise. That default is the safe direction: it under-claims
rather than over-claims, and the model refuses to guess your period's representativeness.

## Types are strict

Numbers must be JSON numbers, not strings, and `project_life_years` must be a JSON
integer rather than a float:

```text
error: energy_capacity_kwh must be a JSON number
error: project_life_years must be a JSON integer
```

The second catches `15.0`, which many templating tools emit for an integer. Booleans are
rejected where numbers are expected, and blank strings are rejected where text is required:

```text
error: source must be a non-blank string
```

Malformed JSON is reported with a position, which is usually faster to act on than the
message itself:

```text
error: invalid scenario JSON: Illegal trailing comma before end of object: line 39 column 1
```

## The bounds

These are conditioning guards, not statements about realistic projects. You will normally
never meet them, but they explain the error if you do.

| Resource | Limit |
| --- | ---: |
| Scenario JSON | 1 MB |
| Time-series CSV | 25 MB |
| Intervals | 100,000 |
| Interval duration | 24 hours |
| Power | 1,000,000,000 kW |
| Stored energy | 1,000,000,000,000 kWh |
| Absolute price and degradation cost | 1,000,000 EUR/MWh |
| Monetary inputs | 1,000,000,000,000,000 EUR |
| Project life | 1 to 100 years |
| Annualization factor | greater than 0, at most 1,000,000 |
| Default solve time | 60 seconds per phase |

A 100,002-row CSV is refused by the reader before any solve is attempted:

```text
error: CSV exceeds the 100000-row limit
```

Remember that the row limit is far above the practical solve limit. Accepting a file is not
a promise of solving it — see [benchmarks](../benchmarks.md) and
[solver status](24-solver-status.md).

## Validating before you solve

`pv-bess validate` reads and checks both files without solving anything. It is fast, and
it prints the two provenance hashes:

```bash
pv-bess validate --scenario sample-data/scenario.json
```

```json
{
  "analysis_input_sha256": "c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8",
  "dispatch_input_sha256": "76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491",
  "interval_count": 24,
  "interval_hours": 1.0,
  "scenario": "Synthetic 5 MW PV plus 5 MW / 20 MWh BESS",
  "status": "valid"
}
```

Read `interval_count` and `interval_hours` every time. They are the cheapest possible check
that the file you imported is the file you meant to import: a truncated CSV or a
misinterpreted timestamp column shows up here instantly.

## Two things validation does not catch

`status: valid` means the files are well-formed and every value is individually within its
domain. It does **not** mean the run will succeed, and it does not mean the values are
sensible. Two cases are worth knowing by name.

### Terminal SOC that the financial layer will reject

The battery accepts any `terminal_soc_fraction` inside the operating window. The financial
layer requires it to equal `initial_soc_fraction`, because valuing left-over stored energy
is not implemented. So a scenario with `initial_soc_fraction: 0.5` and
`terminal_soc_fraction: 0.6` validates cleanly:

```json
{ "status": "valid", "interval_count": 24, "...": "..." }
```

and then fails after the solver has already done its work:

```text
error: financial evaluation requires terminal SOC to equal initial SOC; inventory
valuation is not implemented
```

On a 24-hour scenario the wasted time is trivial. On a scenario near the practical solve
limit it is minutes. Until `validate` checks this, treat "terminal SOC equals initial SOC"
as a rule you enforce yourself.

### A discount rate entered as a percentage

`discount_rate_fraction` is a fraction, and its accepted range is `[-0.95, 10]`. The value
`8`, meaning someone typed "8%" as `8`, is inside that range. It validates, it solves, and
it produces a complete, confident, wrong answer:

| Figure | `discount_rate_fraction: 0.08` | `discount_rate_fraction: 8` |
| --- | ---: | ---: |
| NPV | EUR -3,467,411 | EUR -4,977,619 |
| LCOS | EUR 262.14/MWh | EUR 12,760.82/MWh |
| IRR | -0.0692 | -0.0692 |

Nothing warns you. The tell is that **IRR is unchanged** — IRR does not depend on the
discount rate — while NPV and LCOS move by orders of magnitude. If a scenario's LCOS looks
absurd and its IRR looks ordinary, check the discount rate first.

The same fraction-versus-percentage trap exists for `annual_benefit_degradation_fraction`
and `annual_opex_escalation_fraction`, though their tighter ranges catch most cases.

## Practical habits

1. Validate before every run, and read `interval_count` and `interval_hours`.
2. Keep the JSON and CSV together, and version them together.
3. Record the dispatch hash with any result you circulate.
4. Check `discount_rate_fraction < 1` by eye. It is the highest-consequence field with the
   loosest guard.
5. Keep `terminal_soc_fraction` equal to `initial_soc_fraction`, or omit it entirely and
   let the default do it.
