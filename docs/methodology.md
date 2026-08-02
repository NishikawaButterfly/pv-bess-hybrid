# Methodology

## Electrical boundary and units

The alpha models one AC-coupled PV plant, one aggregated battery, and one point of connection. PV, grid, and battery powers are kW AC. SOC is kWh DC. Market prices are EUR/MWh and interval duration is hours.

This is an energy-dispatch model. It does not calculate voltage, current, protection, losses outside the stated battery efficiencies, or equipment compliance.

## Decision variables

For every interval `t`:

- `pv_export[t]`: PV exported to the grid;
- `pv_charge[t]`: PV sent to the battery;
- `grid_charge[t]`: optional grid energy sent to the battery;
- `battery_export[t]`: battery discharge exported to the grid;
- `curtailment[t]`: unused PV;
- `soc[t]`, `soc[t+1]`: stored energy;
- `charge_mode[t]`: binary charge/discharge direction;
- `import_mode[t]`: binary point-of-connection direction.

## Energy equations

PV allocation:

```text
pv_export[t] + pv_charge[t] + curtailment[t] = pv_available[t]
```

SOC transition:

```text
soc[t+1] = soc[t]
           + charge_efficiency * (pv_charge[t] + grid_charge[t]) * interval_hours
           - battery_export[t] / discharge_efficiency * interval_hours
```

SOC remains inside its operating window at every state. Initial and terminal SOC are fixed. Charge and discharge cannot coexist in an interval. Grid import and export cannot coexist in an interval. Combined PV and battery export never exceed the grid export limit.

## Objective

SciPy minimizes the negative of operating value:

```text
market value = (PV export + battery export - grid charge)
               * interval hours * market price / 1000

degradation reserve = battery export / discharge efficiency
                      * interval hours
                      * EUR per MWh DC discharged / 1000
```

The optimizer therefore maximizes market value less the explicit degradation reserve. A second MILP is constrained to the first phase's economic optimum within EUR 0.0000001 and minimizes battery throughput; curtailment is only a final, negligible refinement. This prevents arbitrary zero-value cycling without embedding a hidden commercial penalty in the primary objective.

Negative prices are supported. Voluntary curtailment is allowed, so the model does not force uneconomic export.

## Baseline and KPIs

The PV-only baseline exports up to the point-of-connection limit at nonnegative prices and curtails the remainder; at negative prices it may curtail all PV. Incremental battery value equals optimized operating value minus baseline market value.

Equivalent full cycles are:

```text
DC discharged energy / nominal DC energy capacity
```

Curtailment reduction is reported only when baseline curtailment is nonzero.

## Financial model

The model creates the following cash-flow sequence:

```text
year 0 = -CAPEX
year n = annualized incremental operating value
         * capacity fraction(n) * benefit-degradation factor
         - fixed OPEX * escalation factor
```

`capacity fraction(n)` is one for every year unless the optional fade parameters described in the next section are set.

NPV discounts year-end cash flows. Supported discount rates and the IRR search are bounded to `[-0.95, 10]` for numerical safety. IRR uses bisection and is reported only when the cash-flow signs change exactly once and a root exists in that domain. Payback interpolates within the crossing year. Discounted payback uses the same method after discounting.

LCOS divides the present value of CAPEX, fixed OPEX, grid-charging cost, foregone PV baseline revenue, and the degradation reserve by discounted AC battery discharge. When capacity fade is configured, each year's variable cost and discharged energy scale by the same capacity fraction as the NPV benefit, so the ratio's numerator and denominator follow one trajectory. The financial benefit-degradation haircut remains a pure benefit haircut: it is not reused as physical capacity fade and does not alter LCOS. LCOS is `null` when the scenario never discharges and can be affected by negative prices.

Taxes, debt, grants, replacements, salvage value, availability, and stochastic effects are outside this alpha.

## Multi-year capacity fade

Two optional battery parameters model usable-capacity loss over the project life. Both are fractions of the original usable energy and default to zero, which reproduces the pre-fade financial model and its hashes exactly:

- `calendar_fade_fraction_per_year`: loss per year of calendar aging;
- `cycling_fade_fraction_per_efc`: loss per equivalent full cycle.

The capacity fraction applied during project year `n` is:

```text
annual EFC = representative-period EFC * annualization factor
fade per year = calendar fade + cycling fade * annual EFC
capacity fraction(n) = 1 - fade per year * (n - 1)
```

Year 1 always runs at full capacity, and cycling fade accrues at the year-one annualized cycle count in every year — a first-order simplification that slightly overstates fade late in the project life. The dispatch is not re-solved per year: each year reuses the representative schedule and scales its incremental operating benefit, its variable cost, and its discharged energy by the same capacity fraction, so the NPV cash flows and both sides of the LCOS ratio follow one trajectory ([limitations.md](limitations.md) explains why re-solving is deferred). If any project year's fraction would fall below the validated `minimum_capacity_fraction`, the evaluation stops with an error instead of silently flooring.

### Worked example

The analytical two-interval fixture: a 2,000 kWh battery with unit efficiencies and a EUR 1/MWh DC degradation reserve receives 2,000 kW of PV at EUR 20/MWh, then discharges at EUR 100/MWh, all through a 1,000 kW grid limit. The representative period earns an incremental EUR 99.00, discharges 1.0 MWh AC, and runs 0.5 equivalent full cycles. Take `annualization_factor = 10`, `calendar_fade_fraction_per_year = 0.02`, `cycling_fade_fraction_per_efc = 0.004`, `minimum_capacity_fraction = 0.85`, CAPEX EUR 1,000, zero OPEX, a 4-year life, and a discount rate of zero. Then:

```text
annual EFC = 0.5 * 10 = 5
fade per year = 0.02 + 0.004 * 5 = 0.04
```

| Year | Capacity fraction | Benefit (EUR) | Discharged energy (MWh) |
| ---: | ---: | ---: | ---: |
| 1 | 1.00 | 990.00 | 10.00 |
| 2 | 0.96 | 950.40 | 9.60 |
| 3 | 0.92 | 910.80 | 9.20 |
| 4 | 0.88 | 871.20 | 8.80 |

NPV is `-1,000 + (990.00 + 950.40 + 910.80 + 871.20) = EUR 2,722.40`. The representative-period battery cost is only the EUR 1 degradation reserve (the charged PV would otherwise have been curtailed, so no export revenue is foregone), giving an annualized variable cost of EUR 10 before fade. With the capacity fractions summing to 3.76, LCOS is `(1,000 + 10 * 3.76) / (10 * 3.76) = 1,037.60 / 37.60 = EUR 27.5957/MWh`. `tests/test_finance.py` asserts this table.

## Solver evidence

Every summary records a canonical dispatch-input hash and a second hash covering the dispatch plus every financial assumption. It also records schema version, scientific model version, SciPy interface version, HiGHS backend version when the installed SciPy build exposes it, both phase statuses, requested and achieved relative MIP gap, and the per-phase time limit. A result is rejected unless both solver phases report success and post-solve invariants pass.
