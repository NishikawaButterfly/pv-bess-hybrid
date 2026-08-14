# 12. Reading the dispatch schedule

`dispatch.csv` is one row per interval. This chapter goes through the columns and then
reads a real schedule.

## The columns

```text
dispatch_input_sha256,analysis_input_sha256,timestamp,interval_hours,pv_power_kw,
market_price_eur_per_mwh,pv_export_kw,pv_charge_kw,grid_charge_kw,battery_export_kw,
grid_export_kw,curtailed_pv_kw,soc_start_kwh,soc_end_kwh,market_value_eur,
degradation_cost_eur,net_operating_value_eur
```

| Column | Unit | Meaning |
| --- | --- | --- |
| `dispatch_input_sha256` | — | Repeated on every row; ties the file to `summary.json` |
| `analysis_input_sha256` | — | As above, including the financial assumptions |
| `timestamp` | ISO 8601 | Interval **start**, with its offset |
| `interval_hours` | h | Duration, identical on every row |
| `pv_power_kw` | kW AC | Your input, echoed back |
| `market_price_eur_per_mwh` | EUR/MWh | Your input, echoed back |
| `pv_export_kw` | kW AC | PV sent to the grid |
| `pv_charge_kw` | kW AC | PV sent to the battery |
| `grid_charge_kw` | kW AC | Grid energy sent to the battery |
| `battery_export_kw` | kW AC | Battery discharge sent to the grid |
| `grid_export_kw` | kW AC | `pv_export_kw + battery_export_kw` |
| `curtailed_pv_kw` | kW AC | PV deliberately unused |
| `soc_start_kwh` | kWh DC | Stored energy at interval start |
| `soc_end_kwh` | kWh DC | Stored energy at interval end |
| `market_value_eur` | EUR | Value of the interval's net grid position |
| `degradation_cost_eur` | EUR | The reserve charged on DC energy discharged |
| `net_operating_value_eur` | EUR | `market_value_eur - degradation_cost_eur` |

Note the two mixed unit systems in one row: **powers are AC kW, stored energy is DC kWh.**
Every SOC change reflects an efficiency conversion, so SOC never moves by the same number
as the flow that caused it.

## The three identities that must hold

Any row can be checked by hand, and checking one or two is a good habit on an unfamiliar
scenario.

**PV allocation.** Every available kW is accounted for:

```text
pv_power_kw = pv_export_kw + pv_charge_kw + curtailed_pv_kw
```

**SOC transition.** Charging multiplies by the charge efficiency, discharging divides by
the discharge efficiency:

```text
soc_end = soc_start
        + charge_efficiency x (pv_charge_kw + grid_charge_kw) x interval_hours
        - battery_export_kw / discharge_efficiency x interval_hours
```

**Interval value.** Grid charging is a cost at the same price export is a revenue:

```text
market_value_eur = (pv_export_kw + battery_export_kw - grid_charge_kw)
                   x interval_hours x market_price_eur_per_mwh / 1000
```

The solver's output is re-checked against all three before a result is published, along
with the grid limits, the power limits, the exclusivity rules, and a global energy balance.
A result that fails any of them is rejected rather than reported.

## Reading a real schedule

Here is the repository's 24-hour sample, dispatched. Value columns to three decimals,
flows to one.

| Hour | PV | Price | PV exp | PV chg | Batt exp | Curt | SOC start | SOC end | Market value | Degr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 00:00 | 0 | 45 | 0 | 0 | 0 | 0 | 10,000.0 | 10,000.0 | 0.000 | 0.000 |
| 05:00 | 0 | 30 | 0 | 0 | 0 | 0 | 10,000.0 | 10,000.0 | 0.000 | 0.000 |
| 06:00 | 200 | 28 | 0 | 200 | 0 | 0 | 10,000.0 | 10,192.0 | 0.000 | 0.000 |
| 07:00 | 800 | 30 | 0 | 800 | 0 | 0 | 10,192.0 | 10,960.0 | 0.000 | 0.000 |
| 08:00 | 1,800 | 35 | 0 | 1,800 | 0 | 0 | 10,960.0 | 12,688.0 | 0.000 | 0.000 |
| 09:00 | 3,200 | 40 | 0 | 3,200 | 0 | 0 | 12,688.0 | 15,760.0 | 0.000 | 0.000 |
| 10:00 | 4,500 | 45 | 2,725 | 1,775 | 0 | 0 | 15,760.0 | 17,464.0 | 122.625 | 0.000 |
| 11:00 | 5,200 | 50 | 5,000 | 200 | 0 | 0 | 17,464.0 | 17,656.0 | 250.000 | 0.000 |
| 12:00 | 5,800 | 55 | 5,000 | 800 | 0 | 0 | 17,656.0 | 18,424.0 | 275.000 | 0.000 |
| 13:00 | 5,600 | 50 | 5,000 | 600 | 0 | 0 | 18,424.0 | 19,000.0 | 250.000 | 0.000 |
| 14:00 | 5,000 | 45 | 5,000 | 0 | 0 | 0 | 19,000.0 | 19,000.0 | 225.000 | 0.000 |
| 16:00 | 2,600 | 60 | 2,600 | 0 | 0 | 0 | 19,000.0 | 19,000.0 | 156.000 | 0.000 |
| 18:00 | 300 | 110 | 300 | 0 | 0 | 0 | 19,000.0 | 19,000.0 | 33.000 | 0.000 |
| 19:00 | 0 | 140 | 0 | 0 | 5,000 | 0 | 19,000.0 | 13,791.7 | 700.000 | 52.083 |
| 20:00 | 0 | 125 | 0 | 0 | 3,640 | 0 | 13,791.7 | 10,000.0 | 455.000 | 37.917 |
| 21:00 | 0 | 90 | 0 | 0 | 0 | 0 | 10,000.0 | 10,000.0 | 0.000 | 0.000 |
| 23:00 | 0 | 50 | 0 | 0 | 0 | 0 | 10,000.0 | 10,000.0 | 0.000 | 0.000 |

Four things to notice, in the order a reader usually notices them.

**The morning sells nothing.** From 06:00 to 09:00 every available kW goes into the
battery, at prices from EUR 28 to EUR 40/MWh, even though the grid is wide open. The
optimiser is not choosing between charging and idling — it is choosing between selling now
at EUR 28 and selling later at EUR 140. The foregone export revenue is the real cost of
charging, and here it is the smallest it will be all day.

**10:00 splits the flow.** 2,725 kW exported and 1,775 kW charged in the same interval.
Charging and *exporting* are not exclusive — only charging and discharging are. The split
is what the SOC ceiling requires: the battery has to arrive at 19,000 kWh, and no sooner.

**The midday hours are export-limited.** At 11:00–13:00 PV exceeds 5,000 kW and export
sits exactly at the limit, with the excess charged rather than curtailed. This is the
clipping-recovery value stream, and it is why optimised curtailment is 0 MWh against the
baseline's 1.6 MWh.

**The evening is the payoff, and it stops early.** 19:00 discharges at full 5,000 kW power
into EUR 140/MWh; 20:00 discharges the remaining 3,640 kW to land exactly on the 10,000 kWh
terminal target. Then the battery sits out 21:00 at EUR 90/MWh — a price it sold into
happily an hour before. Nothing is wrong: everything above the terminal SOC is gone, and
the terminal constraint forbids selling the opening inventory.

## Two formatting artifacts

Both are cosmetic, and both surprise people reading a CSV closely.

**Negative zero.** In a scenario with negative prices, an interval that exports nothing
records `-0.0` rather than `0.0`, because the value calculation multiplies a zero flow by
a negative price:

```text
...,2026-06-15T08:00:00+00:00,1.0,1800.0,-20.0,0.0,0.0,0.0,0.0,0.0,1800.0,...,-0.0,0.0,-0.0
```

Seven such rows appeared in one 24-hour run. It sums correctly and parses as zero
everywhere; it just reads oddly.

**Floating-point residue in SOC.** A battery holding steady may record
`4000.0000000000055` rather than `4000.0`. Flows are snapped to zero within 1e-6 kW, but
SOC values are not rounded, and the published energy-balance tolerance is 1e-4 kWh. Do not
mistake a 5e-12 kWh wobble for battery activity.

## Reading a schedule quickly

A four-step routine that catches most surprises:

1. **Where does SOC peak, and where does it bottom out?** That is the battery's one job in
   the period, and everything else supports it.
2. **Which hours sit exactly at `export_limit_kw`?** Those are the hours the connection is
   the binding constraint.
3. **Which hours have non-zero `curtailed_pv_kw`?** Compare against
   `baseline_curtailed_energy_mwh` in `summary.json` to see what the battery recovered.
4. **Which hours have non-zero `grid_charge_kw`?** If any do, read
   [chapter 15](15-grid-charging.md) before quoting the economics.
