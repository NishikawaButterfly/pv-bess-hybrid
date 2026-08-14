# 29. Troubleshooting

Every message below was produced by running the software. Errors go to stderr with an
`error: ` prefix and exit code 1; over the API they arrive as `detail` with the status code
noted.

## Time-series CSV

| Message | Cause | Fix |
| --- | --- | --- |
| `CSV header must be exactly: timestamp,pv_power_kw,market_price_eur_per_mwh` | Renamed, reordered, or semicolon-delimited header; also an empty file | Use the exact header, comma-delimited, in that order |
| `invalid CSV row N: could not convert string to float: ''` | Blank cell | Night hours are `0`, never blank |
| `invalid CSV row N: could not convert string to float: 'n/a'` | Text placeholder | Remove placeholders; use `0` where zero is meant |
| `invalid CSV row N: pv_power_kw must be greater than or equal to zero` | Negative PV, often night-time self-consumption | Clamp to zero |
| `invalid CSV row N: timestamp must include an explicit UTC offset` | Naive timestamp | Add `+00:00` or `Z` to every row |
| `invalid CSV row N: row contains more fields than the declared header` | Extra column, or an unquoted comma | Remove the extra field |
| `timestamps must have a uniform interval with no gaps` | Missing row, or a DST spring-forward in local time | Fill the gap; carry real UTC offsets across DST |
| `timestamps must be strictly increasing` | Unsorted rows, or a DST fall-back duplicate | Sort; use real offsets |
| `at least two intervals are required to infer interval duration` | Single data row | Provide at least two |
| `CSV exceeds the 100000-row limit` | Too many rows | Shorten the horizon — and note the solver limit is far lower |
| `hourly.csv exceeds the 25000000-byte limit` | File too large | Shorten or reduce precision |
| `interval duration must not exceed 24 hours` | Spacing over one day | Use 24-hour intervals or finer |

## Scenario JSON

| Message | Cause | Fix |
| --- | --- | --- |
| `unknown scenario key(s): X` | Extra root key | Remove it; there is no free-text field |
| `unknown battery key(s): round_trip_efficiency` | Field that does not exist | Use `charge_efficiency` and `discharge_efficiency` |
| `unknown financial key(s): discount_rate` | Misspelling | Use `discount_rate_fraction` |
| `duplicate JSON key: name` | Same key twice | Remove the duplicate |
| `schema_version must be '1.0'; received '1.1'` | Wrong version | Set the string `"1.0"` |
| `invalid scenario JSON: Illegal trailing comma ...` | Malformed JSON | Fix at the reported line and column |
| `scenario must be a JSON object` | Top level is an array or scalar | Wrap in an object |
| `energy_capacity_kwh must be a JSON number` | Number quoted as a string | Remove the quotes |
| `project_life_years must be a JSON integer` | `15.0` instead of `15` | Use an integer literal |
| `source must be a non-blank string` | Empty provenance field | Fill it in |
| `the current model supports EUR market and financial inputs only` | Non-EUR currency | Convert everything to EUR |
| `time_series_csv must be a relative path` | Absolute path | Use a path relative to the scenario file |
| `time_series_csv must stay inside the scenario directory` | `../` in the path | Move the CSV beside the scenario |
| `cannot access ...: [WinError 2] The system cannot find the file specified` | Missing companion CSV | Check the filename and location |

## Battery and grid values

| Message | Cause | Fix |
| --- | --- | --- |
| `charge_efficiency must be greater than zero and at most one` | Efficiency above 1, or a percentage | Use a fraction in `(0, 1]` |
| `minimum_soc_fraction must be less than maximum_soc_fraction` | Inverted window | Swap them |
| `initial_soc_fraction must be inside the operating window` | Start outside the window | Move it inside |
| `terminal_soc_fraction must be inside the operating window` | End outside the window | Move it inside |
| `energy_capacity_kwh must be greater than zero` | Zero or negative capacity | Positive value |
| `import_limit_kw must be positive when grid charging is enabled` | Flag on, no import capacity | Set an import limit, or turn the flag off |
| `at least one grid limit must be greater than zero` | Both limits zero | Set at least one |
| `discount_rate_fraction must be in [-0.95, 10]` | Rate far out of range | Use a fraction |
| `annual_benefit_degradation_fraction must be in [0, 1)` | Percentage instead of fraction | `0.02`, not `2` |
| `calendar_fade_fraction_per_year must be in [0, 1)` | Out of range | Use a fraction |

## After the solve

| Message | Status | Cause | Fix |
| --- | --- | --- | --- |
| `dispatch optimization failed with status 2: The problem is infeasible. (HiGHS Status 8: ...)` | 422 | No schedule satisfies the constraints | See [chapter 25](25-infeasibilities.md); check terminal SOC first |
| `dispatch optimization failed with status 1: Time limit reached. (HiGHS Status 13: ...)` | 422 | Solver ran out of time in one phase | Shorten the horizon; raise `--time-limit`; loosen `--mip-gap` |
| `financial evaluation requires terminal SOC to equal initial SOC; inventory valuation is not implemented` | 422 | Terminal differs from initial | Set them equal, or omit `terminal_soc_fraction` |
| `the fade parameters drive the year-N capacity fraction to X, below the validated minimum_capacity_fraction of Y; reduce the fade parameters or shorten project_life_years` | 422 | Fade crosses the floor within the project life | Do exactly what the message says |
| `dispatch refinement changed the economic optimum` | 422 | Numerical conditioning | Rescale extreme inputs |
| `refusing to overwrite summary.json, dispatch.csv; pass --force to replace them` | — | Output directory already used | Use a new directory, or `--force` |
| `refusing to overwrite report.xlsx; pass --force to replace it` | — | Workbook exists | As above |
| `time_limit_seconds must be finite and greater than zero` | — | Bad `--time-limit` | Positive number |
| `relative_mip_gap must be in [0, 1)` | — | Bad `--mip-gap` | Value in `[0, 1)` |
| `the API dependencies are not installed; install the 'api' extra ...` | — | Missing extra | `pip install -r requirements-api.txt` |
| `the Excel dependencies are not installed; install the 'xlsx' extra ...` | — | Missing extra | `pip install -r requirements-xlsx.txt` |

## Results that are surprising rather than wrong

| Symptom | Likely cause | Check |
| --- | --- | --- |
| **NPV absurdly negative, IRR ordinary** | `discount_rate_fraction` entered as a percentage | IRR does not depend on the discount rate, so this pattern is diagnostic. Verify the rate is below 1 |
| **NPV meaninglessly negative** | Whole-plant CAPEX against battery-only benefit | `capex_eur` must be the battery increment |
| **LCOS in the thousands** | Battery barely discharges | Read `battery_discharge_energy_mwh`; the battery may be too small or the spreads too thin |
| **LCOS is `null`** | Battery never discharges | Expected. Check `equivalent_full_cycles` is 0 |
| **IRR is `null`** | Two sign changes, or no root in `[-0.95, 10]` | Read `cash_flows_eur`; late negative flows are a real finding |
| **Payback `null` but NPV improving** | CAPEX not recovered within the project life | Expected on most scenarios here |
| **Simple payback exists, discounted does not** | Money returned but not the cost of money | Correct behaviour; quote both |
| **`curtailment_reduction_fraction` is `null`** | Baseline curtailment was zero | Not applicable, not 0% |
| **Battery does nothing at all** | No price spread exceeding round-trip losses plus the reserve, and no surplus PV | Check `equivalent_full_cycles`, price range, and whether PV ever exceeds the export limit |
| **Export energy exceeds PV energy** | Grid charging enabled | Bought energy resold; caveat the economics |
| **Battery discharges before dawn** | Making room for negative-price or clipped PV later | Read the SOC curve alongside prices |
| **Battery idle at a high price late in the horizon** | Terminal SOC constraint | Expected; inventory cannot be sold |
| **Annual figures ten times too large or small** | `annualization_factor` wrong for the period | 365 for a day, ≈11.774 for a 31-day month, 1 for a year |
| **`-0.0` in the CSV** | Zero flow times a negative price | Cosmetic |
| **SOC reads `4000.0000000000055`** | Floating-point residue | Cosmetic; tolerance is 1e-4 kWh |

## Web explorer

| Symptom | Cause | Fix |
| --- | --- | --- |
| **Results shown after a failed run belong to the previous file** | The results block is not cleared on failure | **Reload the page after any failure before reading anything** |
| `The dispatch request timed out after 180 seconds.` | Client-side timeout | Use the CLI for long scenarios; the solve continues server-side |
| Table stops at 1,000 rows | Deliberate truncation | Use `dispatch.csv` |
| No way to save the result | No export exists | Use the CLI, or save the API response |

## When nothing above fits

Collect the scenario JSON, the CSV, both hashes from `pv-bess validate`, and the `solver`
block or `/health` payload. Those five things are what anyone diagnosing the problem will
ask for, and the hashes are what make the report reproducible.
