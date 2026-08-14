# 27. A worked multi-year example

The 24-hour example demonstrates the mechanics. This one is closer to a real study: a
744-hour month at a realistic solver scale, carried across a 15-year project life, with and
without physical capacity fade.

```bash
pv-bess run --scenario sample-data/monthly/scenario.json --output results/monthly
```

Completed in 2.7 seconds. Dispatch hash
`45d62c07d58c8f381138cc54da10605c4a2fd5d75e38b84ef15ee45801964958`, analysis hash
`a9b25aaec1e112250cd3bf2b3dc024fa27e4f6e8e69fe6ea01a6306b8a26e884` — both matching the
repository's published anchors.

## The scenario

The same 5 MW / 20 MWh battery as the 24-hour example, on the same 5 MW connection, over a
deterministic synthetic March (744 hours, UTC). `annualization_factor` is
`8760 / 744 ≈ 11.774`. March was chosen because it sits near the annual average of the
generator's seasonal PV curve rather than at a solstice.

## The month's dispatch

| Figure | Value |
| --- | ---: |
| PV energy | 771.06 MWh |
| Export energy | 733.26 MWh |
| Battery discharge | 444.40 MWh |
| Curtailed energy | 0.00 MWh |
| Baseline curtailed energy | 0.00 MWh |
| Curtailment reduction | `null` |
| Market value | EUR 46,727.95 |
| Degradation cost | EUR 4,629.16 |
| Operating value | EUR 42,098.79 |
| Baseline market value | EUR 28,723.25 |
| **Incremental operating value** | **EUR 13,375.54** |
| Equivalent full cycles | 23.15 |

Both solver phases optimal; the economic phase proved a gap of 0.0 and refinement
1.8e-15, which is numerically zero.

Two features distinguish this from the summer day.

**There is no curtailment at all**, in the baseline or optimised. A March profile on a
5 MW connection never clips, so `curtailment_reduction_fraction` is `null` — not
applicable rather than zero. **The entire benefit is time shifting**, with none of the
clipping recovery that made up part of the 24-hour example's value.

**The battery works much harder**: 23.15 equivalent full cycles in 31 days, roughly 0.75 a
day against the summer day's 0.45, because the month contains 31 evening peaks rather than
one.

## Scaling to a year

```text
annualized benefit = 13,375.54 x 11.774 = EUR 157,486.23
annual EFC         = 23.146 x 11.774 = 272.52 cycles per year
```

The cycle figure is worth pausing on: 272 cycles a year against a warranty that may permit
fewer. The model has no cycle-life limit and will not warn you.

## Fifteen years without capacity fade

The scenario carries a 2% annual benefit haircut and 2% OPEX escalation:

| Year | Cash flow (EUR) |
| ---: | ---: |
| 0 | -5,000,000.00 |
| 1 | 57,486.23 |
| 2 | 52,336.51 |
| 3 | 47,209.78 |
| 5 | 37,017.07 |
| 10 | 11,794.54 |
| 12 | **1,766.73** |
| 13 | **-3,242.10** |
| 14 | -8,250.22 |
| 15 | -13,259.65 |

| Metric | Value |
| --- | ---: |
| NPV at 8% | EUR -4,751,352.98 |
| IRR | `null` |
| Simple payback | not reached |
| Discounted payback | not reached |
| LCOS | EUR 175.50/MWh |

**The IRR is withheld, and that is the most useful thing in the table.** The cash flows
change sign twice — negative to positive at year 1, positive to negative at year 13 —
because a 2% compounding benefit haircut falls faster than a 2% compounding OPEX escalation
rises against a shrinking base. From year 13 the battery no longer covers its own fixed
costs.

That is a design finding, and neither NPV nor LCOS surfaces it. It is visible only in
`cash_flows_eur`, which is why [chapter 17](17-irr.md) recommends reading the sign pattern
before either headline metric. A project whose economics turn negative two years before the
end of its stated life needs either a shorter stated life, a different OPEX assumption, or
an explanation.

## Fifteen years with capacity fade

The same month, with physical fade configured:

```json
"calendar_fade_fraction_per_year": 0.02,
"cycling_fade_fraction_per_efc": 0.00005,
"minimum_capacity_fraction": 0.5
```

```text
annual EFC    = 272.52
fade per year = 0.02 + 0.00005 x 272.52 = 0.033626
```

| Year | Capacity fraction |
| ---: | ---: |
| 1 | 1.0000 |
| 5 | 0.8655 |
| 10 | 0.6974 |
| 15 | 0.5292 |

| Metric | No fade | With fade |
| --- | ---: | ---: |
| Dispatch hash | `45d62c07…` | `45d62c07…` (identical) |
| Analysis hash | `a9b25aae…` | `14eebf9b…` |
| Every dispatch KPI | — | identical |
| NPV at 8% | EUR -4,751,352.98 | EUR -4,964,549.26 |
| IRR | `null` | `null` |
| LCOS | EUR 175.50/MWh | EUR 206.34/MWh |

Fade costs EUR 213,196 of NPV and raises LCOS by EUR 30.83/MWh. Note that **LCOS rises**,
because both sides of the ratio shrink while the undiscounted CAPEX in the numerator does
not — the consistency that the physical fade model provides and the financial benefit
haircut does not.

Note also that the **dispatch hash is unchanged**. Fade is a financial-layer transformation
of a single schedule, and the two runs solved the identical optimisation problem.

## The limitation this example must carry

**The dispatch is not re-solved per year.** Year 12 in this calculation is year 1's
schedule with every flow multiplied by 0.6301. A real battery at 63% of its original
capacity would dispatch differently — it would keep its most valuable cycles and drop its
least valuable ones, work within a smaller usable window, and shift when it charges. It
would not simply do the same thing 37% smaller.

Compounding this, **cycling fade accrues at the year-one cycle count in every year**. A
faded battery moves less energy per cycle, so charging it 272 times in year 12 causes less
wear than the model assumes. The repository's own methodology notes that this slightly
overstates fade late in the project life.

Both are first-order simplifications the software documents, and the reason is published:
re-solving each project year is deferred because even one full-year solve is already slow
and unreliable on modest hardware, and a 15-year life would need fifteen of them.

Quote a multi-year result with that sentence attached: *"Capacity fade is applied by
scaling one representative dispatch, not by re-optimising each project year."*

## Why a month and not a year

The repository benchmarks a full 8,760-hour year and deliberately does not ship it as a
fixture. On the reference hardware one run finished in 191 seconds and an identical repeat
found no feasible refinement solution within a 1,200-second per-phase limit. The month
solves in about a second.

So the practical modelling choice for an annual study is a representative period plus an
explicit annualization factor — which is what this example does — while accepting that the
factor carries the seasonal assumption. A March month annualised by 11.774 ignores every
seasonal effect outside March: no summer clipping, no winter price shape, and no seasonal
correlation between PV and price.

## What this example is and is not

**It is** a realistic demonstration of the solver at working scale, a complete multi-year
calculation, and a clean illustration of a null IRR carrying real information.

**It is not** an investment case. The data is synthetic — invented PV and invented prices
from a seeded generator — and the financial result is intentionally unfavourable. The
repository's fixture documentation says exactly this, and the negative NPV is evidence that
the model reports its inputs rather than manufacturing a conclusion.
