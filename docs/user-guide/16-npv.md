# 16. Net present value

NPV is the headline financial output: the discounted sum of the battery's incremental cash
flows, in EUR.

## The convention

| Property | This model |
| --- | --- |
| Scope | The **battery increment** against a PV-only baseline, not the whole plant |
| Leverage | Unlevered — no debt, no interest, no covenants |
| Tax | Pre-tax — no corporate tax, no depreciation shield, no allowances |
| Basis | Nominal EUR, not real |
| CAPEX timing | Entirely at time zero, undiscounted |
| Benefit timing | Year end, once per project year |
| Discount rate | Your `discount_rate_fraction`, applied to year-end flows |

`discount_rate_fraction` is a **fraction**: 8% is `0.08`, not `8`. The accepted range is
`[-0.95, 10]`, which is wide enough that `8` — meaning 800% per year — validates and runs.
Any value above `1.0` therefore produces a warning naming the value and how it was read.
It is a warning and not a rejection: a rate above 100% is occasionally intended, and the
model calculates whatever rate you give it. See
[the discount rate as a percentage](04-data-contract-in-practice.md#a-discount-rate-entered-as-a-percentage)
for the size of the error and where the warning appears.

`annual_opex_escalation_fraction` is a fraction the same way and carries the same trap: `1`
means 100% escalation per year, not 1%. Its range is `[-0.95, 1]`, so it cannot reach 800%,
but a mistyped percentage is still ruinous — it is the input that quietly compounds a fixed
OPEX line to 26x over this sample's 15-year life. A value above `0.25` (25% a year), already
beyond any plausible sustained escalation of an operating-cost line, now produces a warning
naming the value and how it was read, exactly as the discount rate does. The two warnings
share one channel, so a scenario that mistypes both shows both.

The cash-flow sequence is:

```text
year 0 = -capex_eur
year n = annualized incremental operating value
         x capacity fraction(n)
         x (1 - annual_benefit_degradation_fraction)^(n-1)
         - annual_fixed_opex_eur x (1 + annual_opex_escalation_fraction)^(n-1)
```

and NPV discounts them at `1 / (1 + r)^n`.

## Worked, from the sample

The repository sample produces an incremental operating value of EUR 764.525 per modelled
day, with `annualization_factor` 365, `annual_benefit_degradation_fraction` 0.02,
`annual_fixed_opex_eur` 100,000, `annual_opex_escalation_fraction` 0.02,
`capex_eur` 5,000,000, `discount_rate_fraction` 0.08, and a 15-year life.

```text
annualized benefit = 764.525 x 365            = 279,051.625
year 1 = 279,051.625 x 1.00 - 100,000 x 1.00  = 179,051.625
year 2 = 279,051.625 x 0.98 - 100,000 x 1.02  = 171,470.5925
year 3 = 279,051.625 x 0.9604 - 100,000 x 1.0404 = 163,961.18065
```

which are exactly the first three entries of `cash_flows_eur` in `summary.json`. The full
series declines to EUR 78,357.13 in year 15, and

```text
NPV = -5,000,000 + sum of the 15 discounted flows = EUR -3,818,737.08
```

The sample's NPV is deeply negative and deliberately so. The repository is explicit that
this is evidence the software reports the assumptions it was given rather than manufacturing
a favourable conclusion. A synthetic day annualised by 365, against a EUR 5,000,000 CAPEX,
was never going to pay.

## What the NPV does not include

Everything below is absent from the calculation. Each one moves the number, and most move
it upward — which is why an NPV from this model is not a project NPV.

**Financing.** No debt, no gearing, no interest, no debt service coverage. An unlevered NPV
says nothing about equity returns.

**Tax.** No corporate tax, no depreciation, no capital allowances, no tax equity. In most
jurisdictions the depreciation shield on a capital-intensive asset is material.

**Grants and incentives.** No capital grants, no investment tax credits, no capacity
payments, no ancillary-service revenue.

**Replacements and salvage.** No battery replacement or augmentation at any point in the
project life, and no residual value at the end. For a 15-year life on a technology whose
useful life is often shorter, the absence of an augmentation CAPEX is a significant
omission in the optimistic direction.

**Availability.** The battery is assumed available in every interval of every year. No
forced outage, no maintenance downtime, no derating.

**Anything the price series omits.** Capacity markets, balancing services, network
charges, imbalance costs, and PPA structures. See [chapter 3](03-preparing-market-prices.md).

**Inflation, other than what you put in.** Flows are nominal, so your discount rate must be
nominal too. The only escalation modelled is `annual_opex_escalation_fraction` on fixed
OPEX; the benefit stream does not inflate with prices unless you build that into the
benefit degradation fraction, which is a strange place to put it.

## Reading NPV honestly

**It is an increment, so the costs must be too.** The most common way to produce a
meaningless NPV here is to enter whole-plant CAPEX against battery-only benefit. Check that
`capex_eur` is the battery system's cost before reading the result.

**It inherits every input assumption, including the annualization factor.** An NPV built on
one summer day scaled by 365 is an arithmetic exercise. The factor is the largest single
lever in the whole calculation and it is entirely yours.

**It is a perfect-foresight upper bound on the operating side.** The dispatch that produced
the benefit knew every price in advance. Real operation earns less.

**Its sign is not a decision.** A positive NPV under these conventions is a necessary
condition for a project, not a sufficient one — it says nothing about financeability,
technical feasibility, or compliance.

## Sanity checks

Before you quote an NPV, three checks that take a minute and catch most errors:

1. **Reconstruct year 1 by hand.** `incremental_operating_value_eur x annualization_factor
   - annual_fixed_opex_eur` must equal `cash_flows_eur[1]`. If it does not, you have
   misunderstood one of the fields.
2. **Read `warnings` before you read the NPV.** A rate entered as a percentage still
   validates and still runs; what it no longer does is stay silent. An empty `warnings`
   array means the assumptions were checked and nothing looked mistyped — see
   [chapter 4](04-data-contract-in-practice.md#a-discount-rate-entered-as-a-percentage).
3. **Look at the last cash flow.** If it is negative while the first is positive, OPEX
   escalation has overtaken the degrading benefit, IRR will be withheld, and the project's
   late years are destroying value. That is a real finding, and it is easy to miss when you
   only read the NPV.

## When NPV is the wrong metric

NPV scales with project size, so it cannot compare a 20 MWh and a 200 MWh battery unless
their CAPEX values are both real. In this model it is easy to vary capacity while leaving
CAPEX fixed — the sensitivity layer does exactly that — and the resulting NPV comparison is
meaningless as a sizing tool.

For sizing, vary capacity and CAPEX together in separate scenarios, and read
[LCOS](19-lcos.md) alongside NPV. For comparing against a hurdle rate, read
[IRR](17-irr.md), remembering that it is sometimes withheld.
