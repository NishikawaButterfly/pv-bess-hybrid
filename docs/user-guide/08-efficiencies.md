# 8. Charge and discharge efficiencies

Two fields, one for each direction:

```json
"charge_efficiency": 0.96,
"discharge_efficiency": 0.96
```

Both must be greater than zero and at most one:

```text
error: charge_efficiency must be greater than zero and at most one
```

They default to 0.95 each, which asserts a 90.25% round trip whether or not you meant to.

## What each one converts

| Field | Converts |
| --- | --- |
| `charge_efficiency` | AC charging energy → stored DC energy |
| `discharge_efficiency` | stored DC energy → exported AC energy |

The SOC transition makes the asymmetry explicit. Charging multiplies; discharging divides:

```text
soc[t+1] = soc[t]
           + charge_efficiency x (pv_charge + grid_charge) x interval_hours
           - battery_export / discharge_efficiency x interval_hours
```

So to deliver 1,000 kW AC for an hour at 96% discharge efficiency, the battery must remove
1,000 / 0.96 = 1,041.67 kWh DC from storage. This is visible in any dispatch row: in the
sample day's 19:00 hour, 5,000 kW of battery export drops SOC from 19,000.0 to 13,791.7
kWh — a fall of 5,208.3 kWh, which is 5,000 / 0.96.

The degradation reserve is charged on that **DC** figure, not the AC energy delivered. So is
the equivalent-full-cycle count.

## Never copy a round-trip efficiency into both fields

This is the error the data contract explicitly warns about, and it is worth showing what it
costs. A datasheet quoting "72% round trip" invites two wrong moves and one right one.

All three runs below use the same 24-hour profile, the same 20 MWh battery, and identical
everything else:

| charge / discharge | Implied round trip | Battery discharge | Incremental value | LCOS |
| --- | ---: | ---: | ---: | ---: |
| 1.00 / 1.00 | 100.00% | 9.00 MWh | EUR 826.40 | EUR 249.78/MWh |
| 0.96 / 0.96 | 92.16% | 8.64 MWh | EUR 764.53 | EUR 262.14/MWh |
| **0.80 / 0.90** | **72.00%** | 8.10 MWh | EUR 612.65 | EUR 290.03/MWh |
| **0.8485 / 0.8485** | **72.00%** | 7.64 MWh | EUR 583.70 | EUR 303.83/MWh |
| 0.72 / 0.72 | 51.84% | 6.48 MWh | EUR 353.90 | EUR 371.22/MWh |

Two findings.

**Copying the round trip into both fields is catastrophic.** The last row asserts a 51.84%
round trip — the square of the number you meant — and returns EUR 353.90 against the correct
EUR 612.65. That is 42% of the value destroyed by a copy-paste, with no warning of any kind,
because 0.72 is a perfectly legal efficiency.

**Even a correct round trip is not enough.** The two bold rows have *identical* round-trip
efficiency and differ by EUR 28.95, or 4.7%. The square-root split is not a neutral
assumption.

## Why the split matters, not just the product

The reason is worth understanding, because it tells you when the split will matter most.

In all five runs above the SOC window is the binding constraint, so the battery moves the
same DC energy every time — 9,000 kWh, an unchanging 0.45 equivalent full cycles. What
changes is how much AC energy comes out of that fixed DC store:

```text
AC discharged = 9,000 kWh DC x discharge_efficiency
```

which reproduces all five discharge figures exactly: 9.00, 8.64, 8.10, 7.64, and 6.48 MWh.
The charge efficiency, meanwhile, only determines how much PV is consumed to fill the
window — energy that on this site would otherwise have been curtailed, and so nearly free.

**When the energy window binds, discharge efficiency dominates and charge efficiency is
nearly free.** When the *charging energy* is the scarce resource — a site without clipping,
or a grid-charging scenario where every kWh in is bought — charge efficiency starts to
matter as much or more. The split matters; which half matters depends on what is scarce.

## Getting the numbers right

**Ask for the directional pair.** A vendor able to quote a round-trip figure can usually
quote the split, or the AC-to-DC and DC-to-AC conversion steps you can derive it from.

**If you only have the round trip, document the split you assume.** The square root is the
conventional symmetric assumption. It is *an assumption*, it is not neutral, and it belongs
in your report next to the result — record it in `dataset.source` if nowhere else.

**Check which boundary the datasheet uses.** These fields are AC-side at the modelled bus,
so they must include the power conversion system. A DC-to-DC cell efficiency will overstate
the plant. Auxiliary loads — thermal management, controls — are not modelled at all and are
best folded into these efficiencies rather than ignored.

**Be consistent with the power fields.** The efficiencies are AC-side, and so are
`max_charge_power_kw` and `max_discharge_power_kw`. Only `energy_capacity_kwh` and the SOC
figures are DC.

## Sensitivity

Both efficiencies are in the [sensitivity](21-sensitivity.md) parameter set as
`charge_efficiency` and `discharge_efficiency`, and can be varied by multiplier or absolute
value. A variant that pushes an efficiency above one is rejected before anything is solved,
with the variant named in the message. Given how much the split moves the answer, running a
directional sensitivity on the efficiency you are least sure of is usually a better use of
32 runs than another price scan.
