# 14. Understanding curtailment

Curtailment is available PV that was not used. In this model it is a decision variable, not
a failure — the optimiser curtails whenever using the energy is worth less than throwing it
away.

## Where curtailment comes from

Two causes, with opposite economics.

**The connection is full.** PV exceeds `export_limit_kw` and the battery cannot absorb the
excess — either it is full, or its charge power is too small, or it has nowhere useful to
put the energy. This is clipping, and it is a pure loss.

**The price is negative.** Exporting would mean paying to generate. Here curtailment is the
*correct* commercial decision, and the PV-only baseline does it too.

The distinction matters because the first kind is what a battery is bought to fix and the
second kind mostly is not.

## The two figures in `summary.json`

| Field | Meaning |
| --- | --- |
| `baseline_curtailed_energy_mwh` | What a PV-only plant would have curtailed |
| `curtailed_energy_mwh` | What the optimised plant with the battery curtails |
| `curtailment_reduction_fraction` | `(baseline - optimised) / baseline` |

The reduction fraction is the battery's headline curtailment claim. **It is `null`, not
zero, when baseline curtailment is zero** — there was nothing to reduce, so no percentage
exists. A run of four 24-hour intervals with PV always below the export limit reported
`curtailment_reduction_fraction: null` with `baseline_curtailed_energy_mwh: 0.0`. Treat a
null as "not applicable", and never render it as 0%.

## Four runs, four curtailment stories

All four use a 5 MW export limit. The differences are in the plant and the prices.

| Run | PV | Baseline curtailed | Optimised curtailed | Reduction |
| --- | ---: | ---: | ---: | ---: |
| Sample day, 20 MWh battery | 40.2 MWh | 1.60 MWh | 0.00 MWh | 100% |
| 200 kWh battery | 40.2 MWh | 1.60 MWh | 1.45 MWh | 9.4% |
| 9.5 MW PV peak, 2 MWh battery | 68.5 MWh | 20.50 MWh | 18.94 MWh | 7.6% |
| Midday negative prices | 40.2 MWh | 31.10 MWh | 15.48 MWh | 50.2% |

**100% is achievable and unremarkable.** The sample's 20 MWh battery absorbs all 1.6 MWh
of clipping without effort — the clipping is small relative to the battery. A 100%
reduction says the clipping was easy to catch, not that the battery is well sized.

**A small battery recovers almost nothing.** The 50 kW / 200 kWh battery recovers 0.15 MWh
of 1.60. Its constraint is power, not energy: the plant clips at up to 800 kW and the
battery can take 50.

**Massive curtailment can be untouchable.** The third run has a 9.5 MW peak on a 5 MW
connection — 20.5 MWh curtailed in a day — and a 500 kW / 2 MWh battery recovers 1.56 MWh
of it, 7.6%. The curtailment is a plant design problem. No battery this size fixes it, and
a battery large enough would need its own justification.

**Negative prices produce the largest reduction, and it is the least like the others.**
Read on.

## The negative-price case in detail

A run with midday prices from EUR -50 to EUR -10/MWh. The baseline curtails everything
during those hours — 31.1 MWh of 40.2 MWh, because exporting at a negative price is worse
than nothing. The optimised plant curtails 15.48 MWh, a 50.2% reduction, and the schedule
shows how:

| Hour | PV (kW) | Price | PV export | PV charge | Batt exp | Curtailed | SOC end |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00:00 | 0 | 45 | 0 | 0 | **5,000** | 0 | 4,791.7 |
| 01:00 | 0 | 42 | 0 | 0 | 760 | 0 | 4,000.0 |
| 08:00 | 1,800 | -20 | 0 | 0 | 0 | 1,800 | 4,000.0 |
| 09:00 | 3,200 | -35 | 0 | 1,125 | 0 | 2,075 | 5,080.0 |
| 10:00 | 4,500 | -40 | 0 | **4,500** | 0 | 0 | 9,400.0 |
| 11:00 | 5,200 | -45 | 0 | 0 | 0 | 5,200 | 9,400.0 |
| 12:00 | 5,800 | -50 | 0 | 0 | 0 | 5,800 | 9,400.0 |
| 13:00 | 5,600 | -30 | 0 | 5,000 | 0 | 600 | 14,200.0 |
| 14:00 | 5,000 | -10 | 0 | 5,000 | 0 | 0 | 19,000.0 |
| 19:00 | 0 | 140 | 0 | 0 | 5,000 | 0 | 13,791.7 |
| 20:00 | 0 | 125 | 0 | 0 | 3,640 | 0 | 10,000.0 |

Three behaviours worth naming.

**The battery empties itself before dawn.** 5,000 kW discharged in the first hour of the
day at EUR 45/MWh, taking SOC from 10,000 down to 4,000 — the floor. Not because EUR 45 is
a good price, but because the battery must be empty by mid-morning to catch free energy.
A schedule that appears to sell into a mediocre price is often making room.

**It charges hard at the most negative prices.** Note 10:00 at EUR -40 and 13:00 at
EUR -30: full-power charging. The energy is not merely free, it is energy the alternative
would have thrown away, and charging costs nothing at all in opportunity terms.

**It still curtails 15.48 MWh.** The 11:00 and 12:00 hours — 5,200 and 5,800 kW at the
most negative prices of the day — are curtailed entirely, because the battery is at 9,400
kWh and its charge power is 5,000 kW while nothing can be exported. There is more free
energy than there is room for it.

The 50.2% reduction is real, but notice what it is: the battery is capturing energy the
market was paying to reject. Whether that has commercial value depends entirely on whether
your offtake arrangement passes negative prices through — a question the model cannot see.

## When curtailment is the right answer

The optimiser will curtail rather than export whenever export value is negative, and this
is deliberate. Voluntary curtailment is allowed precisely so the model does not force
uneconomic export.

It follows that **a run showing zero curtailment is not automatically a good result**. On
a site with negative prices, zero optimised curtailment would mean the plant was exporting
into negative prices, which is worse.

## Reading curtailment honestly

1. **Separate clipping from negative-price curtailment** before quoting a reduction. They
   have different causes and different remedies.
2. **Quote the MWh alongside the percentage.** A 100% reduction of 1.6 MWh and a 7.6%
   reduction of 20.5 MWh are 1.6 and 1.56 MWh respectively — nearly identical in energy.
3. **Check whether the reduction is worth anything.** Curtailment reduction is an energy
   claim, not a revenue claim. Recovered energy sold into a low-price hour is worth little,
   and the incremental operating value already accounts for that properly. If the two
   figures tell different stories, believe the euros.
4. **Remember what is absent.** The model has no curtailment compensation. If your network
   operator pays for curtailed energy, curtailment is not free and the battery's recovery
   value is overstated here.
