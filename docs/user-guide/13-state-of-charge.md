# 13. Understanding state of charge

SOC is the only state variable in the model. Every other quantity is a flow within one
interval; SOC is what carries information from one interval to the next, and it is what
makes the problem an optimisation over a horizon rather than a sequence of independent
decisions.

## SOC is DC energy in kWh

Not a percentage, not AC energy. The `dispatch.csv` columns `soc_start_kwh` and
`soc_end_kwh` are absolute DC stored energy. The fractions in the scenario file are
multiplied by `energy_capacity_kwh` to get the bounds the solver uses:

| Scenario fraction | Sample value | kWh DC |
| --- | ---: | ---: |
| `minimum_soc_fraction` | 0.20 | 4,000 |
| `maximum_soc_fraction` | 0.95 | 19,000 |
| `initial_soc_fraction` | 0.50 | 10,000 |
| `terminal_soc_fraction` | 0.50 | 10,000 |
| usable energy | — | 15,000 |

Every SOC value in a valid result sits between 4,000 and 19,000. The first row's
`soc_start_kwh` is exactly 10,000 and the last row's `soc_end_kwh` is exactly 10,000, both
fixed as equalities rather than bounds.

## Why SOC never moves by the flow that caused it

Charging multiplies by the charge efficiency; discharging divides by the discharge
efficiency. The asymmetry is the point:

```text
soc_end = soc_start
        + charge_efficiency x (pv_charge_kw + grid_charge_kw) x interval_hours
        - battery_export_kw / discharge_efficiency x interval_hours
```

Two rows from the sample day, both at 96% efficiency both ways:

| Hour | Flow | Arithmetic | SOC change |
| --- | --- | --- | ---: |
| 08:00 | charge 1,800 kW | 1,800 x 0.96 x 1 h | +1,728.0 kWh |
| 19:00 | discharge 5,000 kW | 5,000 / 0.96 x 1 h | -5,208.3 kWh |

A battery that charges at 1,800 kW gains less than 1,800 kWh; one that discharges at
5,000 kW loses more than 5,000 kWh. Losses are taken on the way in *and* on the way out.

This is also why the degradation reserve and the cycle count are charged on the DC figure.
The 19:00 hour discharged 5,208.3 kWh DC, and at EUR 10/MWh that is the EUR 52.083 in the
`degradation_cost_eur` column — not the EUR 50.00 that the 5,000 kWh AC delivered would
suggest.

## The shape of a normal SOC curve

The sample day traces the classic single-cycle profile:

```text
19,000 |                    ___________
       |                  /            \
       |                /               \
       |              /                  \
10,000 |____________/                     \______________
       |
       00:00      06:00    13:00   19:00  20:00     23:00
       flat       charge   full    discharge      flat
```

Four phases, each with a cause:

**Flat overnight (00:00–05:00).** No PV, and discharging would mean selling stored energy
at EUR 30–45/MWh that can be sold at EUR 140 tomorrow evening — except the terminal
constraint means it cannot be sold at all without being replaced. The battery waits.

**Rising through the morning (06:00–13:00).** Every kW of PV goes to the battery while
prices are at their daily lowest, then the flow splits as the SOC ceiling approaches.

**Flat at the ceiling (13:00–18:00).** Full at 19,000 kWh. All PV now exports directly.
Note that this is where the *highest* PV output of the day occurs — the battery is already
full when the plant is at its best, which is a sizing signal.

**Falling into the evening peak (19:00–20:00).** Full-power discharge into EUR 140/MWh,
then a partial discharge that lands exactly on 10,000 kWh.

## What the terminal constraint costs you

The requirement that SOC end where it started is the constraint most likely to surprise
you, and it is worth seeing what it forbids.

In the sample day the battery is idle at 21:00 (EUR 90/MWh), 22:00 (EUR 65) and 23:00
(EUR 50) — all prices well above the EUR 28–40 at which it charged that morning. It has
15,000 kWh of usable window and it is sitting at 10,000. Why not sell more?

Because there is nothing left above the terminal target. Selling into 21:00 would end the
day below 10,000 kWh, and the constraint is an equality. The energy at 10,000 kWh is
opening inventory, and the model refuses to let a period's revenue be financed by selling
inventory it did not pay for.

That is the right default. The alternative — allowing the battery to end empty — would let
a 24-hour scenario book the value of energy that was there before the period started, and
annualising that figure by 365 would count the same stored energy 365 times.

The financial layer enforces the equality strictly:

```text
error: financial evaluation requires terminal SOC to equal initial SOC; inventory
valuation is not implemented
```

Note the consequence for your modelling choices. Because the period must be self-contained,
**the initial SOC you choose is an assumption about the state the battery is handed at the
start of every annualised period.** A scenario starting at 0.95 and ending at 0.95 asserts
a battery that begins each day full, which on a solar site means it arrives full without
having charged. Starting mid-window, as the sample does at 0.50, is the more neutral
choice.

## Reading an unusual SOC curve

**SOC never moves.** The battery found nothing worth doing. Either no price spread exceeds
the round-trip losses plus the degradation reserve, or there is no surplus PV to capture.
See [chapter 14](14-curtailment.md) for a run where exactly this happens.

**SOC discharges first, then charges.** Usually a negative-price signal: the battery is
making room before free energy arrives. In one run with midday negative prices the battery
discharged 5,000 kW in the very first hour of the day at EUR 45/MWh, purely to open up
capacity for PV that would otherwise be curtailed six hours later.

**SOC sits at a bound for most of the horizon.** The battery is too small for the
opportunity (pinned at the ceiling) or the opportunity is too small for the battery (pinned
near the floor). Both are sizing signals.

**SOC cycles several times a day.** Multiple price peaks, and worth checking your
`equivalent_full_cycles` against the warranty — the model has no cycle-life limit and will
happily cycle far more often than a real warranty permits.

**SOC changes by tiny amounts.** Values like `4000.0000000000055` are floating-point
residue, not activity. The published SOC tolerance is 1e-4 kWh.
