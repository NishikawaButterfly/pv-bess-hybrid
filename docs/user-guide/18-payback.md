# 18. Payback

Two payback figures are reported: `simple_payback_years` on undiscounted cash flows, and
`discounted_payback_years` on the same flows discounted at your rate.

## The convention

| Property | This model |
| --- | --- |
| Scope | The same incremental, unlevered, pre-tax cash flows as NPV |
| Simple payback | Cumulative undiscounted flows first reach zero |
| Discounted payback | Cumulative **discounted** flows first reach zero |
| Within-year timing | Linear interpolation inside the crossing year |
| Reported when | The cumulative sum crosses zero on a positive flow within the project life |
| Otherwise | `null` |

Because CAPEX sits at time zero and benefits arrive at year end, a payback of 13.45 years
means the cumulative sum crossed zero 45% of the way through year 14 — the model
interpolates linearly inside the crossing year rather than rounding to whole years.

## `null` means "not reached", not "immediate"

Both fields are `null` when the cumulative sum never crosses zero inside
`project_life_years`. This is the common case for the scenarios in this guide, and it is
worth being precise about: a `null` payback and a payback of zero are opposite outcomes.
The web explorer renders `null` as `Not reached`, which is the correct reading.

## What the guide's runs produced

| Run | Simple payback | Discounted payback |
| --- | ---: | ---: |
| Sample day, 15 years | `null` | `null` |
| Sample without benefit haircut | `null` | `null` |
| Grid charging enabled | `null` | `null` |
| Monthly fixture | `null` | `null` |
| **200 MWh battery** | **13.45 years** | `null` |
| **Midday negative prices** | **13.87 years** | `null` |
| Two-interval analytical fixture | 1.01 years | 1.01 years |

The pattern in the middle two rows is the one to understand. Both recover their CAPEX in
undiscounted euros before year 15, and neither recovers it in discounted euros at 8%. The
project returns your money without returning the cost of the money.

That is exactly the information the pair is there to convey, and it is why quoting simple
payback alone is misleading. **Always quote the two together, or quote neither.**

The two-interval fixture is the exception, and it is a toy: EUR 1,000 of CAPEX against
EUR 990 a year at a zero discount rate. Simple and discounted payback coincide because the
discount rate is zero.

## What payback does not include

Everything NPV excludes — tax, debt, grants, replacements, salvage, availability, and all
revenue outside the price series. Plus three problems intrinsic to the metric:

**It ignores everything after the crossing.** A project paying back in year 13 of a 15-year
life and one paying back in year 13 of a 30-year life have the same payback and completely
different value. Payback is blind to the tail.

**It ignores the shape before the crossing.** Two projects reaching zero in the same year
via very different profiles are indistinguishable.

**Simple payback ignores the cost of capital entirely.** That is what the discounted figure
is for, and why the pair is more informative than either half.

## Reading them

**Read the sign pattern of `cash_flows_eur` first.** If the flows turn negative in later
years — as the monthly fixture's do from year 13 — a cumulative sum can cross zero and then
cross back. The reported payback is the first crossing on a positive flow, and it does not
tell you the project later fell below the line again. Payback and IRR both hide this; only
the cash-flow series shows it.

**Treat a payback near the project life as a warning.** A 13.45-year payback in a 15-year
project leaves 18 months of margin against every assumption in the model — none of which
includes battery replacement.

**Do not compare against a payback hurdle set for a levered post-tax investment.** These are
unlevered pre-tax flows, and the comparison is a category error.

## Why paybacks are mostly `null` in this guide

Every scenario here except the toy fixture carries a EUR 5,000,000 CAPEX against a battery
whose incremental value is a few hundred euro a day. That is the repository's deliberate
choice for its sample: the fixture demonstrates the calculation flow, and its financial
result is intentionally unfavourable so that nobody mistakes it for an investment case.

If your own scenario returns `null` for both, the useful next step is not to adjust the
discount rate but to check the three inputs that most often cause it: is `capex_eur` scoped
to the battery increment alone, is `annualization_factor` set for your period, and is the
price series one with enough spread to pay for the round trip? A run where the battery
barely cycles will never pay back, and [chapter 14](14-curtailment.md) and
[chapter 21](21-sensitivity.md) are the places to find out why.
