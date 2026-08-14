# 20. Degradation and the multi-year run

The model has **three** different things called degradation. Confusing them is the easiest
way to produce a defensible-looking number that is internally inconsistent.

## The three mechanisms

| Field | Where it lives | What it does |
| --- | --- | --- |
| `degradation_cost_eur_per_mwh_dc_discharged` | battery | A price per DC MWh discharged, inside the **dispatch objective**. Suppresses marginal cycling. Affects the schedule. |
| `annual_benefit_degradation_fraction` | financial | A compounding **haircut on incremental benefit** only. Does not touch LCOS. |
| `calendar_fade_fraction_per_year` and `cycling_fade_fraction_per_efc` | battery | **Physical capacity fade.** Scales benefit, variable cost, and discharged energy together. |

The first is a within-period cost. The second is a financial adjustment. Only the third is
a capacity model.

**Use the third one when you mean battery ageing.** The benefit haircut reduces NPV while
leaving LCOS untouched, so a scenario using it to represent capacity loss will show a
falling NPV alongside an unchanged cost per MWh — a combination that is hard to defend in
review. Setting both compounds them, which is rarely intended.

## How capacity fade is computed

```text
annual EFC          = representative-period EFC x annualization_factor
fade per year       = calendar_fade + cycling_fade x annual EFC
capacity fraction(n) = 1 - fade per year x (n - 1)
```

Year 1 always runs at full capacity. Each subsequent year's benefit, variable cost, and
discharged energy are all multiplied by that year's fraction, so the NPV cash flows and
both sides of the LCOS ratio follow one trajectory.

`minimum_capacity_fraction` is a validated floor. If any project year would fall below it,
the evaluation stops rather than silently flooring:

```text
error: the fade parameters drive the year-5 capacity fraction to 0.84, below the validated
minimum_capacity_fraction of 0.85; reduce the fade parameters or shorten project_life_years
```

This is a useful guard rather than an obstacle: it forces the fade assumptions and the
stated project life to be consistent with each other.

All three fade fields default to zero, and a zero-fade scenario reproduces the pre-fade
model exactly — the fade parameters are excluded from the dispatch hash and only enter the
analysis hash when non-zero.

## An analytical example you can check by hand

A two-interval fixture: a 2,000 kWh battery with unit efficiencies and a EUR 1/MWh DC
reserve receives 2,000 kW of PV at EUR 20/MWh, then discharges at EUR 100/MWh through a
1,000 kW grid limit. CAPEX EUR 1,000, zero OPEX, four-year life, zero discount rate,
`annualization_factor` 10, `calendar_fade_fraction_per_year` 0.02,
`cycling_fade_fraction_per_efc` 0.004, `minimum_capacity_fraction` 0.85.

The representative period earns EUR 99.00 incremental, discharges 1.0 MWh AC, and runs 0.5
equivalent full cycles. So:

```text
annual EFC    = 0.5 x 10 = 5
fade per year = 0.02 + 0.004 x 5 = 0.04
```

| Year | Capacity fraction | Cash flow (EUR) |
| ---: | ---: | ---: |
| 1 | 1.00 | 990.00 |
| 2 | 0.96 | 950.40 |
| 3 | 0.92 | 910.80 |
| 4 | 0.88 | 871.20 |

```text
NPV  = -1,000 + 990.00 + 950.40 + 910.80 + 871.20 = EUR 2,722.40
LCOS = (1,000 + 10 x 3.76) / (10 x 3.76) = 1,037.60 / 37.60 = EUR 27.5957/MWh
```

Run, the model returns `npv_eur: 2722.4`, `lcos_eur_per_mwh: 27.595744680851055`,
`capacity_fraction_by_year: [1.0, 0.96, 0.92, 0.88]`, and
`annualized_equivalent_full_cycles: 5.0`. The same scenario with fade removed returns
`npv_eur: 2960.0` and `lcos_eur_per_mwh: 26.0`.

## A realistic multi-year run

The repository's sample day, with `calendar_fade_fraction_per_year: 0.02`,
`cycling_fade_fraction_per_efc: 0.00005`, `minimum_capacity_fraction: 0.6`, over the same
15-year life. The sample runs 0.45 EFC per day, so annualised at 365 that is 164.25 cycles
a year and `fade per year = 0.02 + 0.00005 x 164.25 = 0.0282125`.

| Figure | No fade | With fade |
| --- | ---: | ---: |
| Dispatch (all KPIs) | identical | identical |
| Year 1 capacity | 1.0000 | 1.0000 |
| Year 15 capacity | 1.0000 | 0.6050 |
| Year 2 cash flow | EUR 179,051.63 | EUR 171,178.88 |
| NPV | EUR -3,467,411 | EUR -3,844,403 |
| IRR | -6.92% | -11.74% |
| LCOS | EUR 262.14/MWh | EUR 302.79/MWh |

Note that **LCOS rises** with fade, unlike with the financial benefit haircut. Both sides
of the ratio shrink, but the undiscounted CAPEX in the numerator does not, so the cost per
delivered MWh goes up. That is the consistency the fade model buys you.

Note also that the dispatch is byte-for-byte identical between the two runs, and that the
**dispatch hash is unchanged** while the analysis hash differs. Fade is a financial-layer
transformation of one schedule.

## The limitation you must state

**The dispatch is not re-solved per year.** Every project year reuses the year-one
schedule, multiplied by that year's capacity fraction. A genuinely faded battery would
*reshape* its schedule — shifting when it charges, giving up its least valuable cycles
first, working around a smaller usable window — rather than shrinking every flow uniformly.

The repository is explicit about this in [limitations](../limitations.md), and about why:
re-solving each project year is deferred because even one full-year solve is already slow
and unreliable on modest hardware. With a 15-year life that would be fifteen solves.

A second simplification compounds it: **cycling fade accrues at the year-one cycle count in
every year.** A faded battery in year 12 delivers less energy per cycle, so charging it the
same number of times causes less wear than the model assumes. The published methodology
notes that this slightly overstates fade late in the project life.

Both simplifications are first-order and both are stated by the software's own
documentation. When you quote a multi-year result, quote them too. The honest phrasing:
*"Capacity fade is applied by scaling a single representative dispatch, not by re-optimising
each year; the schedule shape is held constant."*

## Choosing fade parameters

`calendar_fade_fraction_per_year` and `cycling_fade_fraction_per_efc` are both fractions of
the **original usable energy**, and both come from the vendor's warranty or degradation
curve. A typical warranty states an end-of-life capacity at a given year and cycle count;
solving for the two coefficients from two points on that curve is the usual approach, and
the assumption you made belongs in your report.

Set `minimum_capacity_fraction` to the warranty's end-of-life threshold. When the run fails
against it, that is the model telling you your fade assumptions and your stated project
life disagree — which is a finding, not an inconvenience.

Finally, note what fade does **not** model: no augmentation, no replacement, no
temperature dependence, no calendar-versus-cycling interaction, and no change in efficiency
or power capability as the battery ages. Capacity is the only thing that fades.
