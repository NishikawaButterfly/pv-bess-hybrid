# 15. Understanding grid charging

By default the battery may only charge from PV. Setting `allow_grid_charging: true` with a
positive `import_limit_kw` lets it buy energy from the market as well. This chapter shows
what that does, and why the resulting economics need a caveat every time you quote them.

## The two flags

```json
"grid": {
  "export_limit_kw": 5000,
  "import_limit_kw": 5000,
  "allow_grid_charging": true
}
```

Enabling the flag without import capacity is rejected as a contradiction:

```text
error: import_limit_kw must be positive when grid charging is enabled
```

The reverse — import capacity present, charging forbidden — is the correct way to describe
a site that can import but is not permitted to charge from the grid, and it is worth
knowing that this changes nothing about the schedule. Verified on the sample day: a
scenario with `import_limit_kw: 5000` and `allow_grid_charging: false` produced
byte-identical dispatch rows to one with `import_limit_kw: 0`, under a different dispatch
hash. The import limit is part of a run's identity even when it does nothing.

## The same day, both ways

One 24-hour profile, one 5 MW / 20 MWh battery, one difference: the flag.

| Figure | Grid charging **off** | Grid charging **on** |
| --- | ---: | ---: |
| Grid charge energy | 0.00 MWh | 18.99 MWh |
| Battery discharge | 8.64 MWh | 19.90 MWh |
| Export energy | 39.47 MWh | **57.50 MWh** |
| PV energy | 40.20 MWh | 40.20 MWh |
| Equivalent full cycles | 0.45 | 1.04 |
| Degradation cost | EUR 90.00 | EUR 207.29 |
| Incremental operating value | EUR 764.53 | **EUR 1,115.67** |
| NPV | EUR -3,467,411 | EUR -2,370,355 |
| IRR | -6.92% | -1.00% |
| LCOS | EUR 262.14/MWh | EUR 141.47/MWh |

Grid charging raises incremental value by 46%, more than doubles the cycle count, and cuts
LCOS by 46%. Note that **export energy exceeds PV energy** — 57.50 MWh out of a plant that
generated 40.20 MWh. The difference is bought energy resold, which is exactly what
arbitrage is, and it is the clearest signal in the summary that a run allowed imports.

## What the schedule does

| Hour | PV | Price | PV exp | PV chg | **Grid chg** | Batt exp | SOC end | Market value |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00:00 | 0 | 45 | 0 | 0 | 0 | 5,000 | 4,791.7 | 225.000 |
| 05:00 | 0 | 30 | 0 | 0 | **5,000** | 0 | 9,591.7 | **-150.000** |
| 06:00 | 200 | 28 | 0 | 200 | **4,800** | 0 | 14,391.7 | **-134.400** |
| 07:00 | 800 | 30 | 0 | 800 | **2,942.9** | 0 | 17,984.8 | **-88.286** |
| 08:00 | 1,800 | 35 | 1,800 | 0 | 0 | 0 | 17,984.8 | 63.000 |
| 10:00 | 4,500 | 45 | 4,500 | 0 | 0 | 500 | 17,464.0 | 225.000 |
| 13:00 | 5,600 | 50 | 5,000 | 600 | 0 | 0 | 19,000.0 | 250.000 |
| 18:00 | 300 | 110 | 300 | 0 | 0 | 4,400 | 14,416.7 | 517.000 |
| 19:00 | 0 | 140 | 0 | 0 | 0 | 5,000 | 9,208.3 | 700.000 |
| 20:00 | 0 | 125 | 0 | 0 | 0 | 5,000 | 4,000.0 | 625.000 |
| 22:00 | 0 | 65 | 0 | 0 | **1,250** | 0 | 5,200.0 | **-81.250** |
| 23:00 | 0 | 50 | 0 | 0 | **5,000** | 0 | 10,000.0 | **-250.000** |

Four behaviours the PV-only schedule never shows.

**Negative market value is normal now.** The `market_value_eur` column goes negative in
every importing hour — that is the cost of energy bought, and it is correct. The interval
identity is `(pv_export + battery_export - grid_charge) x hours x price / 1000`, so an
importing hour books a cost at the same price an exporting hour books revenue.

**The cheapest hours get bought.** 05:00 at EUR 30/MWh, 23:00 at EUR 50, 22:00 at EUR 65.
The battery buys into the daily troughs and sells into the 18:00–20:00 peak at EUR 110–140.

**PV goes into the battery instead of to market during import hours.** At 06:00 and 07:00
the plant produces 200 and 800 kW, and all of it charges rather than exporting — because
import and export cannot coexist at the point of connection, and those intervals are in
import mode. A real cost of the exclusivity constraint, visible in the schedule.

**The day ends by buying back to the terminal target.** 22:00 and 23:00 import 1,250 and
5,000 kW purely to restore SOC to 10,000 kWh. The battery discharged past its starting
point into the evening peak and must buy the inventory back before midnight. That
end-of-horizon repurchase is an artefact of the terminal constraint on a short horizon; on
a longer horizon it would be spread across many days instead of forced into one evening.

## Why these economics are an upper bound

The model settles imports and exports **at the same price**. Real grid charging does not
work that way, and three absent costs all push the same direction:

1. **No import tariff or network charge.** In most markets, buying a MWh costs the energy
   price *plus* use-of-system charges, levies, and taxes. The model charges the bare energy
   price.
2. **No spread between buy and sell.** One series serves both directions, so the round-trip
   arbitrage margin is as wide as it can possibly be.
3. **No market access constraints.** No minimum bid, no gate closure, no imbalance
   exposure, and perfect foresight of every price in the horizon.

Add to those the fact that **grid charging often changes a project's regulatory or tax
status** — in several markets a plant that imports for storage loses a renewable
classification, an incentive, or a grid-connection category — and the EUR 1,115.67 figure
above should be read as a ceiling on a well-specified case, not as a forecast.

The honest way to quote it: *"With grid charging permitted and settled at the same
day-ahead price in both directions, with no import tariffs modelled, the incremental value
rises from EUR 764.53 to EUR 1,115.67 per modelled day."* Every clause in that sentence is
load-bearing.

## Making it more realistic

The model has no field for an import tariff. Two partial workarounds, both imperfect and
both worth stating in your report:

**Raise the degradation reserve.** Increasing
`degradation_cost_eur_per_mwh_dc_discharged` charges every discharged MWh, which suppresses
marginal cycles much as a real cost would. It is not a tariff — it hits PV-charged cycles
just as hard as grid-charged ones — but it stops the optimiser chasing thin spreads.

**Run both ways and take the difference as a bound.** The gap between the grid-charging-off
and grid-charging-on results (here EUR 351.15 per modelled day) is the maximum the arbitrage
capability could be worth. Whatever tariff analysis you do outside the model reduces that
number; nothing increases it.

## When to enable it

**Enable it** when the project genuinely intends and is permitted to charge from the grid,
and you are prepared to caveat the result.

**Leave it off** when the battery is there to capture clipping and shift PV — the common
case for a co-located solar-plus-storage project — or when the regulatory position is
unresolved. Off is the default, and it is the conservative direction.

Either way, check `grid_charge_energy_mwh` in the summary before quoting anything. If it is
non-zero, the number you are about to quote depends on an arbitrage margin the model has
flattered.
