# 19. Levelized cost of storage

LCOS is the discounted lifetime cost of the battery divided by the discounted lifetime
energy it discharges, in EUR per MWh.

## The convention

```text
        capex + PV(fixed opex + grid-charging cost
                   + foregone PV baseline revenue + degradation reserve)
LCOS = ------------------------------------------------------------------
                    PV(AC battery discharge energy)
```

| Property | This model |
| --- | --- |
| Numerator | CAPEX, fixed OPEX, grid-charging cost, foregone PV baseline revenue, degradation reserve |
| Denominator | **AC** energy discharged from the battery, discounted |
| Discounting | Both sides at `discount_rate_fraction`, year by year |
| Capacity fade | Scales the variable cost and the discharged energy together |
| `null` when | The scenario never discharges |

Two features of this definition are specific to this model and change how the number should
be read.

**Foregone PV baseline revenue is a cost.** When the battery charges from PV, the model
charges it with the revenue that PV would have earned by exporting instead — the true
opportunity cost. But only what the PV-only *baseline* would have earned: PV that the
baseline would have curtailed anyway is free. On a clipping site this makes charging cheap
and pulls LCOS down, correctly.

**The denominator is AC, the degradation reserve is DC.** Discharged energy is measured at
the point of connection; the reserve inside the numerator is charged on DC energy removed
from storage. The two differ by the discharge efficiency, and that is intentional — you pay
for what leaves the battery and get credit for what reaches the grid.

## The full range this guide produced

| Run | LCOS | Discharge |
| --- | ---: | ---: |
| 200 MWh battery | EUR 124.10/MWh | 27.92 MWh |
| Midday negative prices | EUR 140.58/MWh | 14.40 MWh |
| Grid charging enabled | EUR 141.47/MWh | 19.90 MWh |
| Monthly fixture | EUR 175.50/MWh | 444.40 MWh |
| Sample day (repository) | EUR 265.97/MWh | 8.64 MWh |
| Sample with capacity fade | EUR 302.79/MWh | 8.64 MWh |
| 9.5 MW PV, 2 MWh battery | EUR 1,312.07/MWh | 1.44 MWh |
| 50 kW / 200 kWh battery | EUR 10,073.96/MWh | 0.19 MWh |
| Idle battery | `null` | 0.00 MWh |

The spread from EUR 124 to EUR 10,074 across the same CAPEX is the whole story of the
metric: **LCOS is dominated by the denominator.** A battery that rarely discharges divides
a fixed cost by almost nothing.

The `null` at the bottom is the boundary case. A battery that never discharges has no
levelized cost of storage, because there is no storage delivered to levelize over. The
field is `null`, not zero and not infinity.

## LCOS is a cost metric, not a value metric

This is the trap, and the repository's own sensitivity table demonstrates it cleanly:

| Variant | NPV | LCOS |
| --- | ---: | ---: |
| base | EUR -3,818,737 | EUR 265.97/MWh |
| `market_price_level*0.8` | **EUR -4,297,302** | **EUR 259.02/MWh** |
| `market_price_level*1.2` | EUR -3,340,173 | EUR 272.93/MWh |

Lowering every price by 20% **improves** LCOS by EUR 6.95/MWh while destroying EUR 479,000
of NPV. Nothing is wrong: cheaper prices mean cheaper charging, and charging cost is in the
numerator. LCOS got better; the project got worse.

Never rank scenarios by LCOS alone. It answers "what does a delivered MWh cost", not "is
this worth building".

## What LCOS does not include

**Revenue of any kind.** By construction. LCOS is a cost, and a project with the lowest
LCOS in your comparison set may still have the worst NPV.

**Tax, debt, grants, replacement, salvage.** Same omissions as NPV.

**Any energy the battery did not discharge.** Curtailment avoided, capacity value, and
ancillary revenue are all outside both the numerator and the denominator.

**The financial benefit haircut.** `annual_benefit_degradation_fraction` reduces NPV and
leaves LCOS untouched — it is a haircut on benefit, and LCOS has no benefit term. Physical
capacity fade *does* affect LCOS, because it scales cost and energy together. If you set
the benefit haircut when you meant physical fade, NPV will fall while LCOS stays put, and
the two metrics will be telling inconsistent stories. See
[chapter 20](20-degradation-multi-year.md).

## What moves LCOS

In rough order of leverage on the scenarios here:

1. **Cycle count.** The denominator. A battery that cycles twice as often halves its LCOS.
2. **CAPEX.** Undiscounted and at time zero, so it dominates the numerator.
3. **Charging cost.** Free on a clipping site, expensive under grid charging.
4. **Discharge efficiency.** Directly scales AC energy out of a fixed DC store.
5. **Discount rate.** Both sides are discounted, but the numerator's CAPEX is not, so a
   higher rate raises LCOS.
6. **Capacity fade.** Scales both sides, but not equally against the undiscounted CAPEX:
   the sample's LCOS rose from EUR 262.14 to EUR 302.79/MWh with fade configured.

## Using it well

**Compare like with like.** LCOS comparisons are only meaningful between scenarios with
honestly scaled CAPEX. Two runs at the same CAPEX with different battery sizes produce an
LCOS ranking that means nothing.

**Quote it with the discharge energy.** EUR 265.97/MWh over 8.64 MWh a day and
EUR 10,073.96/MWh over 0.19 MWh a day are both "the LCOS", and the second is really a
statement that the battery is doing nothing.

**Read it with NPV, always.** The repository's sensitivity documentation says exactly this,
and the price-level rows above are why.

**Do not compare it to a published LCOS benchmark without checking the definition.** LCOS
has no standard definition. This one includes foregone PV revenue as a cost and excludes
replacement CAPEX entirely — both choices that a published figure may not share.
