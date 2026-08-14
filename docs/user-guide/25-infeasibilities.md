# 25. Common infeasibilities and how to fix the scenario

An infeasible scenario is one where no schedule satisfies every constraint. The model says
so and stops:

```text
error: dispatch optimization failed with status 2: The problem is infeasible.
(HiGHS Status 8: model_status is Infeasible; primal_status is None)
```

Exit code 1, no artifacts written. Over the API the same message arrives as a 422.

## The message tells you nothing about the cause

This is the practical difficulty. The message is identical for every infeasible scenario —
there is no indication of which constraint failed, no irreducible infeasible set, and no
hint about which parameter to change. Two structurally different infeasible scenarios,
built deliberately for this guide, produced character-for-character identical output.

So diagnosis is by reasoning, not by reading. The good news is that the model has few
constraints, and only a handful can conflict.

## Cause 1: the terminal SOC target cannot be reached

By far the most common. The battery must end at `terminal_soc_fraction`, and if there is no
way to get there, the problem is infeasible.

**Not enough energy.** A scenario with `initial_soc_fraction: 0.5`,
`terminal_soc_fraction: 0.9`, zero PV in every interval, and grid charging disabled has no
charging source at all. SOC can only fall or hold. Infeasible.

**Not enough power.** A scenario with `initial_soc_fraction: 0.2`,
`terminal_soc_fraction: 0.95`, four one-hour intervals, and `max_charge_power_kw: 100`
needs 15,000 kWh of DC energy and can deliver at most 4 x 100 x 0.96 = 384 kWh. Infeasible.

**Not enough time.** The same arithmetic on a short horizon. The energy required is
`(terminal - initial) x capacity / charge_efficiency`; the energy available is
`sum over intervals of min(PV, charge power) x interval_hours`, plus grid import if
allowed.

**The fix.** In order of preference:

1. Set `terminal_soc_fraction` equal to `initial_soc_fraction`, or omit it. The financial
   layer requires equality anyway, so any other value will be rejected later even if the
   dispatch solves.
2. Lengthen the horizon.
3. Raise `max_charge_power_kw`.
4. Enable grid charging, if the project permits it.

**The check to run first.** Compare the DC energy the terminal target demands against the
AC energy the horizon can supply. If demand exceeds supply, you have your answer without
running anything.

## Cause 2: the SOC window is inconsistent

Most window problems are caught by validation rather than by the solver, which is much
friendlier:

```text
error: minimum_soc_fraction must be less than maximum_soc_fraction
error: initial_soc_fraction must be inside the operating window
error: terminal_soc_fraction must be inside the operating window
```

A window that is *legal but too narrow* to accommodate a required SOC change reaches the
solver and comes back infeasible. If `minimum_soc_fraction` is 0.45 and
`maximum_soc_fraction` is 0.55, the battery has 10% of its capacity to work with, and any
terminal target outside that band is unreachable.

## Cause 3: grid limits conflict with the charging requirement

If the terminal target requires grid charging and `import_limit_kw` is too small — or
`allow_grid_charging` is false — the scenario is infeasible for the reason in cause 1, but
the parameter to change is in the grid block.

Two related conditions are caught earlier by validation:

```text
error: import_limit_kw must be positive when grid charging is enabled
error: at least one grid limit must be greater than zero
```

Note that a zero **export** limit is legal and does not by itself cause infeasibility: PV
can always be curtailed, and curtailment has no upper bound beyond the available PV. PV
alone can never make a scenario infeasible.

## Cause 4: a sensitivity variant

Variants that produce an *invalid* scenario are caught before anything is solved, and the
message names the offending variant:

```text
error: variant 'charge_efficiency*1.1' produces an invalid scenario: charge_efficiency
must be greater than zero and at most one
```

A variant that made the *dispatch* infeasible would be reported the same way, with the
variant label prefixed to the solver message. In practice this is nearly unreachable, and
the reason is worth understanding: since the financial layer requires terminal SOC to equal
initial SOC, an idle battery — every flow zero, all PV curtailed — always satisfies every
constraint. So no reduction in capacity, power, or efficiency can make a financially valid
scenario infeasible; the optimiser can always fall back on doing nothing. Reducing
`power_kw` to 1% of its base value on a working scenario solves normally and simply reports
a worse result.

The corollary is a useful diagnostic: **if a scenario is infeasible, the cause is almost
always a constraint the battery cannot satisfy by standing still** — which means the
terminal SOC target.

## A diagnostic routine

When a scenario comes back infeasible:

1. **Check `terminal_soc_fraction` first.** If it differs from `initial_soc_fraction`, set
   them equal and re-run. This resolves most cases, and any other value would fail the
   financial layer regardless.
2. **Compute the energy budget by hand.** DC energy demanded by the SOC change against AC
   energy available across the horizon. This is a two-line calculation and it is usually
   decisive.
3. **Bisect the horizon.** Run the first half of the CSV. If a short prefix solves and the
   full series does not, the conflict involves a specific stretch of data — often a gap in
   PV around a terminal target.
4. **Relax one constraint at a time.** Widen the SOC window, raise charge power, lengthen
   the horizon. The one that makes it feasible identifies the binding constraint.
5. **Re-run `validate`.** It catches the cheap problems, and it is free.

## Failures that are not infeasibility

Two error classes arrive after the solve and are easy to misread as infeasibility:

```text
error: financial evaluation requires terminal SOC to equal initial SOC; inventory
valuation is not implemented
```

The dispatch solved perfectly. The financial layer refused it. Set the two SOC fractions
equal.

```text
error: the fade parameters drive the year-5 capacity fraction to 0.84, below the validated
minimum_capacity_fraction of 0.85; reduce the fade parameters or shorten project_life_years
```

Also post-solve, and unusually helpful: it names the year, the value, and the two ways out.

And one that looks like infeasibility on a large scenario but is not:

```text
error: dispatch optimization failed with status 1: Time limit reached.
```

The problem may be perfectly feasible; the solver ran out of time. Different status, and a
completely different remedy — see [chapter 24](24-solver-status.md).

## Preventing infeasibility

Most of it is avoided by three habits:

- Omit `terminal_soc_fraction` and let it default to the initial value.
- Set the SOC window from the warranty, and keep the initial fraction near the middle of it.
- Sanity-check that the horizon contains enough PV to do whatever the SOC change requires,
  before running anything.
