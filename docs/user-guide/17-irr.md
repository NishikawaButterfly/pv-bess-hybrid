# 17. Internal rate of return

IRR is the discount rate at which the incremental cash flows have zero NPV, reported as a
fraction per year. `irr_fraction: -0.11248640232702162` means -11.25% per year.

## The convention

| Property | This model |
| --- | --- |
| Scope | Same incremental, unlevered, pre-tax cash flows as NPV |
| Method | Bisection to a tolerance of 1e-10, up to 200 iterations |
| Domain | `[-0.95, 10]` — the search never looks outside it |
| Reported when | The cash flows have **exactly one sign change** and a root exists in the domain |
| Otherwise | `null` |

The two-condition rule is the important part, and it is a deliberate refusal rather than a
limitation.

## Why IRR is sometimes `null`

A cash-flow sequence with more than one sign change can have several mathematically valid
IRRs, or none. Reporting one of them without saying which would be worse than reporting
nothing. So the model checks the sign pattern first and returns `null` if it is not
conventional.

This is not rare in battery projects, and the repository's own monthly fixture demonstrates
it. Its cash flows start positive and turn negative in year 13, because a 2% annual benefit
haircut compounds downward while a 2% OPEX escalation compounds upward:

| Year | Cash flow (EUR) |
| ---: | ---: |
| 0 | -5,000,000.00 |
| 1 | 57,486.23 |
| 5 | 37,017.07 |
| 10 | 11,794.54 |
| 12 | 1,766.73 |
| **13** | **-3,242.10** |
| 14 | -8,250.22 |
| 15 | -13,259.65 |

Two sign changes: negative to positive at year 1, positive to negative at year 13. The
result is `irr_fraction: null`.

**A null IRR here is a finding, not a gap.** It says the project's late years destroy
value — the battery stops covering its own fixed costs around year 12. That is a more
important fact about this scenario than any single rate would have been, and it is
invisible if you only read NPV.

The other reason for a `null` is that no root exists inside `[-0.95, 10]`. The repository's
sensitivity table shows this for the `energy_capacity_kwh*0.5` variant: one sign change,
but the project is so far from breaking even that no discount rate above -95% brings NPV to
zero.

## The values this guide's runs produced

| Run | IRR | Why |
| --- | ---: | --- |
| Sample day, 15 years | -11.25% | One sign change, root found |
| Sample without benefit haircut | -6.92% | Same, less pessimistic |
| Sample with capacity fade | -11.74% | Fade reduces later benefits further |
| Grid charging enabled | -1.00% | Arbitrage nearly closes the gap |
| 200 MWh battery | **+1.40%** | The only positive IRR in the guide |
| Two-interval analytical fixture | +91.66% | A toy scenario, not a project |
| Monthly fixture | `null` | Two sign changes |
| Flat-price day | `null` | No root in the domain |

The 200 MWh run's +1.40% is worth pausing on. It is positive, and it is nowhere near any
plausible hurdle rate — and it comes from a scenario that charges a 200 MWh battery at a
20 MWh battery's CAPEX. A positive IRR is not a good IRR.

## What IRR does not include

Everything NPV excludes, IRR excludes identically: tax, debt, grants, replacements,
salvage, availability, and every revenue stream outside the price series. See
[chapter 16](16-npv.md) for the full list.

Two additions specific to IRR:

**It is an unlevered, pre-tax rate.** Comparing it to a levered post-tax equity hurdle is a
category error. If your hurdle is an equity IRR, this number is not comparable to it
without a financing and tax model that lives outside this software.

**It assumes reinvestment at the IRR itself.** That is the standard critique of IRR and it
applies here unchanged. For a project with a long tail of small flows, MIRR would be more
defensible — and is not implemented.

## Reading IRR alongside NPV

The two can disagree, and when they do the disagreement is informative.

IRR is scale-free, so it survives comparisons between differently sized projects that NPV
cannot make — provided each scenario's CAPEX is real. NPV is scale-dependent and answers
"how much value", which is what actually matters to an investor with a fixed budget.

The useful habit: **read the sign pattern of `cash_flows_eur` before either metric.** It
takes seconds, it tells you immediately whether IRR will exist, and it surfaces the
late-life problem that both headline metrics can hide. A project whose cash flows turn
negative before the end of its stated life has a design question to answer, whatever its
NPV says.
