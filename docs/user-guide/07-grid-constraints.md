# 7. Grid constraints

The grid block describes one point of connection with two directional limits and one
feature flag.

```json
"grid": {
  "export_limit_kw": 5000,
  "import_limit_kw": 0,
  "allow_grid_charging": false
}
```

Both limits are **non-negative magnitudes**, not signed powers. Direction is expressed by
which field you set, never by a minus sign.

## The export limit binds on the sum

`export_limit_kw` caps PV export **plus** battery export in every interval. The battery
cannot discharge past a saturated connection, which is the whole reason a battery on a
clipping plant earns anything: it moves energy from an hour when the connection is full to
an hour when it is empty.

This shows up plainly in the sample day. PV peaks at 5,800 kW against a 5,000 kW limit, and
the optimised schedule exports exactly 5,000 kW through the middle of the day while
diverting the excess into the battery:

| Hour | PV (kW) | PV export (kW) | PV charge (kW) | Grid export (kW) |
| --- | ---: | ---: | ---: | ---: |
| 11:00 | 5,200 | 5,000 | 200 | 5,000 |
| 12:00 | 5,800 | 5,000 | 800 | 5,000 |
| 13:00 | 5,600 | 5,000 | 600 | 5,000 |
| 19:00 | 0 | 0 | 0 | 5,000 |

At 19:00 the same 5,000 kW leaves the site, now entirely from the battery at EUR 140/MWh
instead of EUR 50–55/MWh. The connection is never exceeded and never idle when it is worth
using.

Set this field from the connection agreement, and set it to the **firm** limit. If your
agreement has time-varying or curtailable capacity, the model has no way to express that:
there is one constant number for the whole horizon.

## The import limit and the grid-charging flag

`import_limit_kw` caps grid import, and import is used for exactly one purpose: charging
the battery. **There is no local load in this model.** The plant does not consume anything;
imported energy either enters the battery or is not imported at all.

The flag and the limit must agree:

```text
error: import_limit_kw must be positive when grid charging is enabled
```

The reverse combination — a positive import limit with `allow_grid_charging: false` — is
accepted, and it is the correct way to describe a site that *can* import but is not
permitted to charge from the grid. It is also a useful control: the import limit is part of
the dispatch input hash, so a scenario with `import_limit_kw: 5000` and charging forbidden
produces a **different hash but an identical schedule** to one with `import_limit_kw: 0`.
Confirmed on the sample day: both give an incremental operating value of EUR 764.525, 0.45
equivalent full cycles, and byte-identical dispatch rows, under two different dispatch
hashes.

At least one limit must be positive:

```text
error: at least one grid limit must be greater than zero
```

## Import and export cannot coexist

A binary variable per interval enforces that the point of connection is either importing or
exporting, never both. This is why grid charging appears in the schedule as whole intervals
of import rather than as a net position: in an interval where the battery charges from the
grid, PV export must be zero.

That constraint has a cost the schedule makes visible. In the grid-charging run of
[chapter 15](15-grid-charging.md), the 06:00 and 07:00 hours import 4,800 kW and 2,943 kW
while the plant is producing 200 kW and 800 kW of PV — and that PV goes into the battery
rather than to market, because the connection is in import mode. The optimiser accepted
that trade, but it is a real physical restriction and not an artefact.

## Choosing the export limit deliberately

Two habits are worth keeping.

**Do not pre-clip the PV series.** If you clip the profile at the export limit before
import, baseline curtailment becomes zero, the clipping-recovery value disappears, and the
battery looks worthless on exactly the site where it is most valuable. Give the model the
unclipped profile and let `export_limit_kw` do the work.

**Model the limit you are contracted to, then test it.** A common study is whether a
battery lets a plant accept a smaller connection. That is two scenarios with different
`export_limit_kw` values, compared by hand — the model has no capability to optimise the
connection size, and `export_limit_kw` is not in the sensitivity parameter set, so this
comparison is manual scenario editing in every case.

## What the point of connection does not model

- **No local load.** Import serves the battery only. Self-consumption, behind-the-meter
  supply, and demand charges are all outside the model.
- **No network charges.** Import and export are both settled at the single market price,
  with no tariff, levy, or use-of-system charge in either direction.
- **No losses beyond the battery.** Transformer, cable, and auxiliary losses are absent.
  The only conversion losses the model knows are the battery's two efficiencies.
- **No dynamic limits.** One export number and one import number for the entire horizon.
  No time-of-day capacity, no curtailment instructions, no interruptible capacity.
- **No power quality or grid-code behaviour.** Reactive power, voltage support, frequency
  response, and ramp rates do not exist here.

Each of these makes the modelled connection more permissive than a real one. Where they
matter for your site, they matter in the direction of a worse result than the model shows.
