# 3. Preparing market prices

The price column drives every decision the battery makes. The PV series says what is
possible; the price series says what is worth doing.

## What the column means

`market_price_eur_per_mwh` is the price at which a MWh is both **sold and bought** in that
interval. One series, both directions.

That is the model's most consequential simplification on the revenue side. It means:

- Battery export earns the same price PV export earns in that interval.
- Grid charging costs exactly that price, with no import tariff, no network charge, no
  levy, no imbalance exposure, and no spread between buy and sell.
- There is no bid-ask, no market access constraint, and no minimum bid size.

For a real project the buy price is usually materially above the sell price once network
charges and levies are added. The model has no field for that difference, so a
grid-charging scenario run against a single series **overstates the arbitrage margin**.
The honest workaround is to treat grid-charging results as an upper bound, and to note
the omission wherever you quote them. See [grid charging](15-grid-charging.md) for what
this does to a worked case.

## Units and bounds

| Property | Rule |
| --- | --- |
| Unit | EUR/MWh |
| Sign | Negative values are allowed and meaningful |
| Finiteness | Must be finite |
| Ceiling | Absolute value at most 1,000,000 EUR/MWh |
| Currency | EUR only |

The currency check is absolute. A scenario declaring anything else is rejected:

```text
error: the current model supports EUR market and financial inputs only
```

Convert prices and monetary assumptions to EUR before import, and record the rate you used
in the `dataset.source` field — it is provenance, and nothing else in the pipeline will
remember it for you.

Note the unit asymmetry that trips people up: **prices are per MWh, power is in kW.** The
model divides by 1,000 in the right places, but a series accidentally supplied in
EUR/kWh will be a thousand times too small and will simply produce an uninteresting
result rather than an error.

## Which series to use

The model dispatches against the series you give it with perfect foresight over the whole
horizon. That makes the choice of series a statement about what you are measuring:

**Historical day-ahead prices** answer "what would this battery have earned last year if it
had known the prices in advance". This is the standard benchmark and the usual choice. It
is an upper bound on a day-ahead-only strategy, because a real bidder commits before the
clearing price is known.

**Forward or scenario prices** answer "what would it earn under this view of the future".
Legitimate for appraisal, provided the view is documented. The model will not distinguish
a carefully constructed forward curve from a guess.

**Synthetic prices** answer "how does the machinery behave". The repository's own fixtures
are synthetic and say so loudly. Use them to learn the tool, never to support a decision.

Whichever you choose, the dispatch value you get is a **perfect-foresight upper bound**.
Real operation under uncertainty earns less, and the gap widens as the price series becomes
more volatile. If you need a number to defend, quote it as an upper bound and apply an
explicit haircut you can justify — the model has no parameter for forecast error.

## Negative prices

Negative prices are supported and they change behaviour in ways worth understanding before
you see them in a schedule.

The PV-only baseline curtails *everything* at a negative price, because exporting would
mean paying to generate. The optimised plant does something more interesting: it stops
exporting, and if there is room in the battery it charges from PV that would otherwise be
thrown away — capturing energy at zero cost, since curtailed PV has no opportunity cost.

Two consequences follow, and both are visible in the [curtailment](14-curtailment.md)
chapter's worked run:

1. Negative-price periods can be the battery's most valuable charging windows.
2. The battery may **discharge early, before the negative period**, purely to make room.
   In a run with midday negative prices, the battery discharged 5,000 kW in the very first
   hour at EUR 45/MWh — not because that hour was a peak, but because the SOC had to fall
   before the free energy arrived.

A schedule that appears to sell into a mediocre price is often doing exactly this.

## What is not in the price

The single series carries the energy price and nothing else. Absent from the model
entirely:

- capacity, ancillary-service, or balancing-market revenue;
- network charges, levies, and taxes in either direction;
- imbalance costs and penalties;
- PPA structures, floors, caps, or contract-for-difference settlement;
- curtailment compensation from the network operator.

The last one deserves attention. If your grid operator pays for curtailed energy, the
model's curtailment is free when it should be costly, and the battery's clipping-recovery
value is overstated. There is no field to express this; it has to be handled outside the
model and stated alongside the result.

## A sanity checklist before you import

1. Units are EUR/MWh, not EUR/kWh and not cents.
2. The series covers exactly the same instants as the PV series, row for row.
3. Negative prices, if present, are genuine and not a sign convention error.
4. The price series and the PV series come from the same market and the same year.
5. You can state in one sentence what question this series makes the run answer.

Point 4 sounds obvious and is routinely violated: pairing a typical-meteorological-year PV
profile with a specific historical price year produces a correlation between sun and price
that never existed. The model cannot detect the mismatch, and the resulting number will
look perfectly reasonable.
