# 2. Preparing PV production data

The PV column is the plant's available AC power at the point of connection, interval by
interval. It is the one input the model treats as a hard physical fact: every kW you
declare must be exported, stored, or curtailed. There is no slack.

## What the column means

`pv_power_kw` is **AC power at the modelled point of connection, before any grid limit is
applied**. That phrase carries three decisions.

**AC, not DC.** If your yield simulation gives DC array output, apply the inverter model
first. The dispatch model has no inverter: the only conversion losses it knows about are
the battery's two directional efficiencies. Feeding DC power into this column silently
inflates every energy and revenue figure.

**Before the grid limit, not after.** Do not pre-clip the series to the export limit. The
model needs to see the full available power to compute curtailment and to know how much
energy the battery could capture. A series already clipped at 5,000 kW makes the baseline
curtailment zero and hides the entire clipping-recovery value stream. Set
`export_limit_kw` and let the optimiser do the clipping.

**Available, not delivered.** This is the power the plant *could* produce. Whether it is
delivered, stored, or thrown away is the model's decision, not yours.

## Units and bounds

| Property | Rule |
| --- | --- |
| Unit | kW AC |
| Sign | Zero or positive; a negative value is rejected |
| Finiteness | Must be finite; `NaN` and `inf` are rejected |
| Ceiling | 1,000,000,000 kW (a conditioning guard, not a realistic scale) |

Night hours are zeros, not blanks. An empty cell is rejected:

```text
error: invalid CSV row 2: could not convert string to float: ''
```

as is any non-numeric placeholder:

```text
error: invalid CSV row 2: could not convert string to float: 'n/a'
```

and a negative value:

```text
error: invalid CSV row 2: pv_power_kw must be greater than or equal to zero
```

If your data source writes `-0.5 kW` for night-time inverter self-consumption, clamp it to
zero before import. The model has no concept of parasitic load, so a negative PV value has
no meaning it could honour.

## Choosing the resolution

The interval duration is inferred from the first two timestamps and must then hold for
every subsequent pair. Anything from sub-hourly up to 24 hours is accepted.

Resolution matters when the battery's power limit binds. At hourly resolution a
5,000 kW battery can absorb 5,000 kWh in an hour; the model cannot see that the real PV
peak lasted twenty minutes. Finer resolution captures short peaks and short price spikes,
at the cost of a larger problem.

To show that resolution alone changes nothing when the profile does not, the guide's
24-hour sample profile was re-expressed at 30-minute resolution by repeating each hourly
value twice — 48 intervals describing exactly the same day. The results are the same
within floating-point noise:

| Figure | 60-minute intervals | 30-minute intervals |
| --- | ---: | ---: |
| Intervals | 24 | 48 |
| PV energy | 40.2 MWh | 40.2 MWh |
| Incremental operating value | EUR 764.525 | EUR 764.525 |
| Equivalent full cycles | 0.45 | 0.45 |
| NPV | EUR -3,467,411.4317739154 | EUR -3,467,411.4317739145 |

The NPV agreement to the ninth significant figure, with a difference only in the last two
digits, is the expected signature of the same calculation performed over a different
number of terms. A real half-hourly series would *not* reproduce its hourly aggregate,
because the intra-hour shape is exactly the information hourly data has lost.

Note also that the two runs have **different input hashes**: they are different scenarios
that happen to describe the same day. Resolution is part of a run's identity.

## Timestamps

Timestamps are interval **starts**, must carry an explicit UTC offset, must be strictly
increasing, and must be uniformly spaced with no gaps. The final row represents a full
interval of the same duration as its predecessors.

A naive timestamp is rejected at the row that contains it:

```text
error: invalid CSV row 2: timestamp must include an explicit UTC offset
```

Both `2026-06-15T00:00:00+00:00` and `2026-06-15T00:00:00Z` are accepted; the trailing
`Z` is normalised on read.

**Daylight saving is where real series break.** A local-time series across a spring
transition is missing an hour; across an autumn transition it has a duplicate. Both are
rejected:

```text
error: timestamps must have a uniform interval with no gaps
error: timestamps must be strictly increasing
```

The fix is to carry a genuine UTC offset on every row — `+01:00` before the transition,
`+02:00` after — so that the underlying instants stay uniform even though the local clock
does not. Converting the whole series to UTC before export achieves the same thing. Do not
"fix" a DST gap by inventing a row or deleting one; that shifts every subsequent interval
against its price.

## Horizon length

Two rows is the minimum, because the interval duration is inferred from a pair:

```text
error: at least two intervals are required to infer interval duration
```

The hard ceiling is 100,000 rows, but the practical ceiling is much lower and is set by
the solver, not the reader. The published [benchmarks](../benchmarks.md) show a 744-hour
month solving in about a second while a full 8,760-hour year is unreliable — one measured
run finished in 191 seconds and an identical repeat found no refinement solution within a
1,200-second limit. Plan on roughly a quarter (about 2,000 intervals) as the dependable
single-solve horizon on modest hardware.

This forces a choice for annual studies: model a representative period and annualise it, or
split the year and lose the state-of-charge continuity between windows. The model offers no
rolling-horizon mode, so the first option is the supported one. Choose the representative
period deliberately — the repository's monthly fixture uses March precisely because it sits
near the annual average of its synthetic seasonal curve rather than at a solstice.

## A sanity checklist before you import

1. Column is AC kW at the point of connection, unclipped.
2. Night values are `0`, not blank.
3. Timestamps carry offsets and survive any DST transition in the period.
4. Interval spacing is uniform end to end.
5. Peak value is plausible against the plant's nameplate rating.
6. Total energy over the period matches your yield study to within a percent or two.

Point 6 is the one people skip. `pv_energy_mwh` in `summary.json` is the model's own total,
and comparing it against your yield model catches unit errors, timezone shifts, and
truncated files in a single glance.
