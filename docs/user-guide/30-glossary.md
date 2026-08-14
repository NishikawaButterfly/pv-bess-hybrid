# 30. Glossary

Terms as this model uses them. Where a term has a broader industry meaning, the narrower
meaning here is stated.

## Units and sides

**AC side** — The point of connection. All powers in the model are AC kW: PV, both battery
power limits, both grid limits, and every flow in `dispatch.csv`.

**DC side** — Battery storage. `energy_capacity_kwh`, all SOC values, the degradation
reserve basis, and the equivalent-full-cycle count are DC.

**kW** — Power, AC, at the modelled point of connection.

**kWh** — Stored energy, DC, in SOC columns.

**MWh** — Energy over an interval or a period, in summary KPIs.

**EUR/MWh** — Market price, and the unit of LCOS and the degradation reserve.

## Model quantities

**Annualization factor** — The multiplier that scales the modelled period to one year. Set
by you; never inferred. 365 for a day, about 11.774 for a 31-day month, 1 for a full year.

**Baseline** — The PV-only comparison plant. Exports `min(PV, export_limit_kw)` whenever the
price is non-negative and curtails the rest. Every financial figure is measured against it.

**Curtailment** — Available PV that was not used. A decision variable, not a failure: the
optimiser curtails when using the energy is worth less than discarding it.

**Curtailment reduction** — `(baseline curtailed - optimised curtailed) / baseline
curtailed`. `null` when baseline curtailment is zero.

**Degradation reserve** — `degradation_cost_eur_per_mwh_dc_discharged`. An economic price
per DC MWh discharged, applied inside the dispatch objective. Not a physical model.

**Dispatch** — The schedule of flows and SOC over the horizon; the optimiser's output.

**Equivalent full cycles (EFC)** — DC energy discharged divided by nominal DC capacity, over
the **modelled period**, not per year. Multiply by the annualization factor for an annual
figure.

**Horizon** — The modelled period, from the first interval start to the end of the last.

**Incremental operating value** — Optimised operating value minus baseline market value.
The battery's contribution over the modelled period, and the basis of every cash flow.

**Interval** — One row of the time series. Duration is inferred from the first two
timestamps and must be uniform throughout.

**Market value** — `(pv_export + battery_export - grid_charge) x hours x price / 1000`.
Negative in an interval that imports.

**Operating value** — Market value less the degradation reserve.

**Point of connection** — The single modelled grid interface. Import and export cannot occur
in the same interval.

**State of charge (SOC)** — Stored DC energy in kWh. The model's only state variable.

**Usable energy** — `(maximum_soc_fraction - minimum_soc_fraction) x energy_capacity_kwh`.
Always less than nameplate capacity.

## Financial terms

**CAPEX** — `capex_eur`. The **battery increment's** capital cost, at time zero,
undiscounted.

**Capacity fraction** — The per-year multiplier from physical capacity fade. `1.0` in year
one, declining thereafter.

**Cash flows** — `cash_flows_eur`, one entry per year starting at year 0 (negative CAPEX).
Read the sign pattern before any headline metric.

**Discounted payback** — Years until cumulative **discounted** cash flows reach zero.
`null` if never.

**Financial benefit degradation** — `annual_benefit_degradation_fraction`. A compounding
haircut on incremental benefit only. **Not** a capacity model, and does not affect LCOS.

**IRR** — Internal rate of return, as a fraction per year. Reported only for exactly one
sign change with a root in `[-0.95, 10]`; otherwise `null`.

**LCOS** — Levelized cost of storage. Discounted lifetime cost divided by discounted AC
discharged energy, in EUR/MWh. A cost metric, not a value metric. `null` when the battery
never discharges.

**NPV** — Net present value of the incremental cash flows, unlevered, pre-tax, nominal.

**Physical capacity fade** — `calendar_fade_fraction_per_year` and
`cycling_fade_fraction_per_efc`. Scales benefit, variable cost, and discharged energy
together. Applied by scaling one representative dispatch, not by re-optimising each year.

**Simple payback** — Years until cumulative **undiscounted** cash flows reach zero. `null`
if never.

**Unlevered** — No debt in the cash flows. Not comparable to a levered equity return.

## Solver terms

**Achieved relative MIP gap** — The gap the solver proved, per phase. `0.0` means proved
optimal; values around 1e-15 are floating-point residue.

**Economic phase** — The first solve. Maximises operating value, reported as a minimised
negative.

**HiGHS** — The MILP solver behind `scipy.optimize.milp`. Its version is recorded in every
result.

**Infeasible** — No schedule satisfies every constraint. A statement about your scenario,
not the solver.

**MILP** — Mixed-integer linear program. The binaries enforce charge/discharge exclusivity
and import/export exclusivity.

**Refinement phase** — The second solve. Constrained to the first phase's economic optimum,
it minimises battery throughput. Makes results reproducible, and dominates runtime on long
horizons.

**Relative MIP gap** — The requested stopping criterion, `--mip-gap`. Not part of the input
hashes.

## Provenance

**Analysis input SHA-256** — Hash of the dispatch inputs plus every financial assumption,
plus the fade parameters when non-zero.

**Dispatch input SHA-256** — Hash of everything defining the optimisation problem: scenario
name, dataset metadata, battery (excluding fade), grid, and every interval. Two runs sharing
it solved the same problem.

**Model version** — `dispatch-milp-1.0`. Identifies the formulation.

**Schema version** — `1.0`. Identifies the scenario file format.

## Terms this model does **not** use

Worth listing, because their absence is often assumed to be an oversight rather than a
boundary.

**Capacity factor, LCOE, availability, degradation curve, round-trip efficiency** (as an
input field), **augmentation, replacement CAPEX, salvage value, WACC, levered IRR, DSCR,
tax equity, capacity payment, ancillary services, imbalance, tariff, self-consumption,
demand charge, forecast error, confidence interval.**

None of these exist anywhere in the inputs or outputs. If your analysis needs one, it lives
outside this model.
