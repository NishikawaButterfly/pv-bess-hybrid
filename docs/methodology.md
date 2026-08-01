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
year n = annualized incremental operating value * benefit-degradation factor
         - fixed OPEX * escalation factor
```

NPV discounts year-end cash flows. Supported discount rates and the IRR search are bounded to `[-0.95, 10]` for numerical safety. IRR uses bisection and is reported only when the cash-flow signs change exactly once and a root exists in that domain. Payback interpolates within the crossing year. Discounted payback uses the same method after discounting.

LCOS divides the present value of CAPEX, fixed OPEX, grid-charging cost, foregone PV baseline revenue, and the degradation reserve by discounted AC battery discharge. The financial benefit-degradation haircut is not reused as physical capacity fade. LCOS is `null` when the scenario never discharges and can be affected by negative prices.

Taxes, debt, grants, replacements, salvage value, availability, and stochastic effects are outside this alpha.

## Solver evidence

Every summary records a canonical dispatch-input hash and a second hash covering the dispatch plus every financial assumption. It also records schema version, scientific model version, SciPy interface version, HiGHS backend version when the installed SciPy build exposes it, both phase statuses, requested and achieved relative MIP gap, and the per-phase time limit. A result is rejected unless both solver phases report success and post-solve invariants pass.
