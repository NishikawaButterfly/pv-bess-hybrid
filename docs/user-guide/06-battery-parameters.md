# 6. Battery parameters

The battery block is where most of the modelling judgement lives. This chapter takes the
fields in the order they bind.

## Energy and power are independent

```json
"energy_capacity_kwh": 20000,
"max_charge_power_kw": 5000,
"max_discharge_power_kw": 5000
```

`energy_capacity_kwh` is **nominal DC stored energy**. The two power limits are **AC-side
magnitudes at the modelled bus**. Mixing the sides here is the most common specification
error: a datasheet quoting DC power needs converting through the power conversion system
before it goes in these fields.

Charge and discharge power are separate fields and may differ. Together with the energy
capacity they set the duration: 20,000 kWh at 5,000 kW is a nominal four-hour battery, but
the *usable* duration is shorter because the SOC window and the discharge efficiency both
bite.

## The SOC window sets the energy you actually have

```json
"minimum_soc_fraction": 0.2,
"maximum_soc_fraction": 0.95,
"initial_soc_fraction": 0.5,
"terminal_soc_fraction": 0.5
```

All four are fractions of nominal DC capacity. Usable energy is
`(maximum - minimum) x capacity`, so the sample's 20,000 kWh battery has 15,000 kWh usable
— 75% of its nameplate.

Widening the window is the cheapest way to make a scenario look better, and the least
defensible. Running the guide's sample day with the window opened from 0.20–0.95 to
0.05–1.00, changing nothing else:

| Figure | Window 0.20–0.95 | Window 0.05–1.00 |
| --- | ---: | ---: |
| Usable energy | 15,000 kWh | 19,000 kWh |
| Battery discharge | 8.64 MWh | 9.60 MWh |
| Equivalent full cycles | 0.45 | 0.50 |
| Incremental operating value | EUR 764.53 | EUR 827.65 |
| NPV | EUR -3,467,411 | EUR -3,270,196 |
| LCOS | EUR 262.14/MWh | EUR 241.85/MWh |

An 8% improvement in incremental value for a parameter change costing nothing in the
model — and costing warranty coverage and cycle life in reality. **The model has no cycle-life
model.** Deep cycling has no consequence here beyond the degradation reserve you set
yourself. Take the SOC window from the warranty document, not from what improves the
answer.

`initial_soc_fraction` and `terminal_soc_fraction` must both sit inside the window:

```text
error: initial_soc_fraction must be inside the operating window
```

`terminal_soc_fraction` defaults to `initial_soc_fraction`, and the financial layer
**requires** them to be equal. Setting them differently passes validation and then fails
after the solve:

```text
error: financial evaluation requires terminal SOC to equal initial SOC; inventory
valuation is not implemented
```

The cleanest habit is to omit `terminal_soc_fraction` entirely.

The terminal constraint is a real economic constraint, not bookkeeping. It forces the
modelled period to be self-contained: the battery must end as it started, so it cannot
finance the period's revenue by selling down its opening inventory. In the sample day's
schedule the battery sits idle through the 21:00 hour at EUR 90/MWh — a price it happily
sold into an hour earlier — because everything above the terminal target is already gone.

## The degradation reserve is a price, not physics

```json
"degradation_cost_eur_per_mwh_dc_discharged": 10
```

This is an **economic reserve applied inside the dispatch objective**, charged on DC energy
removed from storage. It is what stops the optimiser cycling the battery for a margin too
thin to be worth the wear.

It is not a degradation model. It does not reduce capacity, does not accumulate, and does
not appear in any year but through the operating value it suppresses. Physical capacity
fade is a separate mechanism — see [degradation and the multi-year run](20-degradation-multi-year.md).

Setting it to zero is legitimate and explicit; it means "cycle whenever there is any
positive margin". Its effect on the sample scenario, from the repository's own sensitivity
run:

| Reserve | Market value | NPV | LCOS |
| ---: | ---: | ---: | ---: |
| EUR 0/MWh | EUR 2,754.63 | EUR -3,566,721 | EUR 255.56/MWh |
| EUR 10/MWh (base) | EUR 2,754.63 | EUR -3,818,737 | EUR 265.97/MWh |
| EUR 20/MWh | EUR 2,754.62 | EUR -4,070,753 | EUR 276.39/MWh |

Market value barely moves while NPV moves by half a million euro. On this scenario the
reserve is not changing *what the battery does* — the spread between charging in the
morning and discharging into the evening peak is wide enough to survive EUR 20/MWh — it is
simply being subtracted from the value. On a scenario with thinner spreads the reserve
would start suppressing cycles, and market value would move too.

## Sizing: what "too small" and "too big" look like

The model evaluates the battery you specify; it never proposes one. Sizing means running
several and comparing. Two runs against the same 5 MW plant and the same day show the shape
of the trade-off. Both keep CAPEX at EUR 5,000,000, which is the point at which the
comparison stops being a real cost comparison — more on that below.

### Too small to matter

A 50 kW / 200 kWh battery on a 5 MW plant:

| Figure | Value |
| --- | ---: |
| Battery discharge | 0.186 MWh |
| Equivalent full cycles | 0.97 |
| Curtailment, baseline to optimised | 1.60 → 1.45 MWh |
| Curtailment reduction | 9.4% |
| Incremental operating value | EUR 12.64 |
| LCOS | EUR 10,073.96/MWh |

The battery works hard — nearly a full cycle in one day, the highest cycle count of any run
in this guide — and achieves almost nothing, because it is power-limited at 50 kW against
a plant whose clipping runs to 800 kW. It recovers a tenth of the curtailed energy. The
absurd LCOS is the honest signal: a fixed cost divided by a negligible discharged energy.

### Too big for the energy available

A 200 MWh battery, ten times the sample's, on the same 5 MW plant:

| Figure | Value |
| --- | ---: |
| Battery discharge | 27.92 MWh |
| Equivalent full cycles | 0.145 |
| Incremental operating value | EUR 1,292.61 |
| NPV | EUR -1,817,559 |
| IRR | 1.40% |
| Simple payback | 13.45 years |
| LCOS | EUR 124.10/MWh |

The battery now stores essentially all the day's PV and sells it into the evening peak,
and it is the only run in this guide with a simple payback at all. But it turns over 0.145
of a cycle a day: 86% of the asset is idle. The plant, not the battery, is the binding
constraint — with 40.2 MWh of PV and a 5 MW export limit, there is nothing more to capture.

The comparison is deliberately unfair, and it is worth naming why: **both runs charge
EUR 5,000,000 of CAPEX.** A tenfold larger battery at the same price is not an engineering
option. The same caveat applies to the `energy_capacity_kwh` variants in
[sensitivity analysis](21-sensitivity.md), which vary the battery while holding CAPEX
fixed. To size honestly, change the capacity **and** the CAPEX together in separate
scenario files, and compare those.

## Reading the cycle count

`equivalent_full_cycles` is DC energy discharged divided by nominal DC capacity, over the
modelled period — **not per year**. The sample day's 0.45 becomes 164.25 annualised cycles
at a factor of 365, which is the number a warranty conversation needs. The model reports
the period figure; the annualisation is yours to do, and the multi-year fade calculation
does it internally.

## A specification checklist

1. Energy in DC kWh, power in AC kW, both from the datasheet.
2. SOC window from the warranty, not from what helps the answer.
3. `terminal_soc_fraction` omitted.
4. Efficiencies as two separate directional values — see [efficiencies](08-efficiencies.md).
5. Degradation reserve set deliberately, even if to zero.
6. Capacity and CAPEX varied together when sizing.
