# 28. Limitations

The [limitations document](../limitations.md) is the authoritative list of what the model
does not do. This chapter is the user-facing companion: which limitations bite in practice,
in which direction, and what to say about them.

## The direction that matters

Most of the model's simplifications flatter the result. That asymmetry is the single most
important thing to carry away.

| Simplification | Direction |
| --- | --- |
| Perfect foresight of every price | **Overstates** dispatch value |
| Single price series for buying and selling | **Overstates** grid-charging value |
| No network charges, levies, or imbalance costs | **Overstates** value |
| No battery replacement or augmentation | **Overstates** NPV |
| No availability or outage derating | **Overstates** value |
| No losses outside the battery efficiencies | **Overstates** delivered energy |
| No cycle-life limit | **Permits** schedules a warranty would not |
| Fade applied by scaling, not re-optimising | Slightly **understates** late-year value |
| No curtailment compensation | **Overstates** battery curtailment benefit |
| Terminal SOC equals initial SOC | **Understates** value on a short horizon |

Only two of eleven push downward, and both are second-order. **A result from this model
should be treated as an optimistic bound**, and the gap between it and reality is not
quantified anywhere in the output.

## Perfect foresight is the big one

The optimiser sees the entire price series before choosing anything. It charges at 06:00
knowing exactly what 19:00 will clear at. No real operator has that.

The model offers no forecast-error parameter, no rolling-horizon mode, and no stochastic
analysis, so there is no way to quantify the gap inside the tool. Published estimates of
the realisable fraction of perfect-foresight arbitrage value vary widely by market and
strategy; whichever haircut you apply, it is an assumption you own and must state.

The practical phrasing: *"EUR X is the perfect-foresight upper bound on dispatch value for
this price series."* Every word is doing work.

## What is completely absent

**Electrical engineering.** No protection, short-circuit, cable, transformer, EMF, thermal,
ventilation, arc-flash, harmonic, or grid-code calculation. A feasible dispatch demonstrates
nothing about whether the plant can be built or connected. The repository removed an
earlier prototype that mixed these concerns after an audit found material errors, and the
current boundary is deliberate.

**Forecasting.** No price forecast, no generation forecast, no market connection.

**Probabilistic analysis.** One deterministic scenario per run. No distributions, no Monte
Carlo, no confidence intervals. The [sensitivity layer](21-sensitivity.md) varies one
parameter at a time and is not a substitute.

**Financing and tax.** Unlevered and pre-tax throughout. No debt, no tax, no depreciation,
no grants, no capacity payments, no ancillary-service revenue.

**Local load.** Grid import serves the battery only. Self-consumption, behind-the-meter
supply, and demand charges are outside the model.

**Multiple assets.** One aggregated PV source, one aggregated battery, one point of
connection. No portfolio, no multiple batteries, no separate inverters.

## What is present but simplified

**Power is constant within an interval.** Sub-interval peaks are invisible. At hourly
resolution a fifteen-minute clipping event is smeared across the hour.

**Battery efficiency is fixed.** No dependence on state of charge, power level, temperature,
or age. Real efficiency varies with all four.

**No ramp rates, dwell times, or minimum run times.** The battery can go from full charge to
full discharge between consecutive intervals with no penalty.

**No degradation feedback into dispatch.** Calendar and cycling fade exist in the financial
layer only; the dispatch schedule never sees them. See
[chapter 20](20-degradation-multi-year.md).

**One grid limit for the whole horizon.** No time-of-day capacity, no curtailment
instructions, no interruptible connection.

## The horizon problem

A 100,000-row input is accepted, but the practical single-solve limit is far lower — around
2,000 intervals, roughly a quarter, on modest hardware. A full 8,760-hour year is
unreliable: one benchmark run finished in 191 seconds and an identical repeat found no
refinement solution within 1,200 seconds per phase.

This is not a minor inconvenience; it shapes how the tool can be used. Annual studies must
model a representative period and annualise, which means:

- the annualization factor carries a seasonality assumption that nothing validates;
- state of charge cannot be carried across seasons;
- a single peak-price week cannot be evaluated in the context of the year around it.

No rolling-horizon or chunked-solve mode exists. The repository names it as future work.

## Limitations you can partly work around

| Limitation | Partial workaround | Residual gap |
| --- | --- | --- |
| No import tariff | Raise the degradation reserve; run with and without grid charging as a bound | The reserve hits PV-charged cycles too |
| No forecast error | Apply an explicit external haircut | Unquantified by the model |
| No cycle-life limit | Check annualised EFC against the warranty by hand | Nothing enforces it |
| No replacement CAPEX | Shorten `project_life_years` to the pre-replacement period | Ignores post-replacement value |
| No financial sensitivity | Edit scenario files and run each | Manual, no combined table |
| No seasonality in a short period | Model several periods separately | No single annual figure |

## What to state alongside a result

A defensible result travels with its qualifications. The minimum:

1. **Scope.** "Battery increment against a PV-only baseline, unlevered and pre-tax."
2. **Foresight.** "Perfect-foresight upper bound on the given price series."
3. **Annualization.** "Modelled period X, scaled by factor Y, assuming representativeness."
4. **Exclusions.** "Excludes tax, debt, grants, replacement, salvage, availability, network
   charges, and all revenue outside the energy price."
5. **Fade treatment**, if used. "Capacity fade applied by scaling one representative
   dispatch, not by re-optimising each year."
6. **Provenance.** Both hashes and the solver versions.

The model writes three of these into every `summary.json` under `limitations`. They are
there to be quoted, not skipped:

> Results are scenario calculations, not a forecast or engineering certification.
> Financial metrics are unlevered and pre-tax.
> The model excludes network losses outside the stated battery efficiencies.

## The sentence that matters most

From the repository's own limitations document: a positive NPV does not demonstrate
technical feasibility, and a feasible dispatch does not demonstrate equipment or grid
compliance. This model answers one narrow question well. Everything else about the project
remains open.
