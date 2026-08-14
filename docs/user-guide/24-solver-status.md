# 24. Solver status and what each means

Every run solves the scenario **twice**, and `summary.json` records both phases separately
under `solver.phases`. Understanding the two-phase structure explains most of what you will
see when a run misbehaves.

## The two phases

**Economic phase.** Maximises operating value — market value less the degradation reserve.
Its objective is reported as a minimised negative, so the sample's `-2664.625` means
EUR 2,664.625 of operating value.

**Refinement phase.** Constrained to the first phase's economic optimum within
EUR 1e-7, it then minimises battery throughput. Its objective is in MWh-equivalent
throughput: the sample's `18.375`.

The second phase exists because a MILP usually has many schedules achieving the same
optimal value. Without it, the model could report a schedule that cycles the battery for no
gain, and two identical runs could report different schedules. It is what makes the output
[reproducible](23-reproducibility.md), and it is also the phase that dominates runtime on
long horizons.

**A result is published only if both phases succeed** and the post-solve invariants pass.

## Reading a successful phase block

```json
"economic": {
  "status": "optimal",
  "status_code": 0,
  "message": "Optimization terminated successfully. (HiGHS Status 7: Optimal)",
  "achieved_relative_mip_gap": 0.0,
  "objective_value": -2664.625,
  "objective_unit": "EUR minimized (negative operating value)"
}
```

| Field | What to check |
| --- | --- |
| `status` | Always `optimal` in a published result — a failure raises instead |
| `status_code` | `0` on success |
| `message` | The verbatim SciPy/HiGHS message |
| `achieved_relative_mip_gap` | **The one to read.** `0.0` means proved optimal |
| `objective_value` | Economic: negative operating value. Refinement: MWh throughput |

`achieved_relative_mip_gap` is the field worth building a habit around. A `0.0` in both
phases means the solver proved optimality and your `--mip-gap` setting was irrelevant. A
non-zero value means the solver stopped at a proved bound rather than a proved optimum, and
the reported schedule may not be the best one.

Small non-zero gaps are normal floating-point residue rather than a real optimality gap:
one run reported `1.1887324003652197e-16` in its economic phase, another
`1.804324164673518e-15` in refinement. Both are numerically zero. A gap of `1e-3` would be
a different matter.

## The failure statuses

A failed solve raises and the run exits 1 with no artifacts written.

### Infeasible

```text
error: dispatch optimization failed with status 2: The problem is infeasible.
(HiGHS Status 8: model_status is Infeasible; primal_status is None)
```

There is no schedule satisfying all the constraints. This is a statement about your
scenario, not about the solver. [Chapter 25](25-infeasibilities.md) covers the causes.

Note that proving infeasibility still costs a solve. On a large scenario this is not a
cheap error.

### Time limit reached

```text
error: dispatch optimization failed with status 1: Time limit reached.
(HiGHS Status 13: model_status is Time limit reached; primal_status is None)
```

Reproduced by giving the 744-hour month a `--time-limit` of 0.01 seconds. The limit applies
**per phase**, so the worst case is twice what you set.

This is the failure you will meet on long horizons, and it usually strikes the *refinement*
phase rather than the economic one. The published [benchmarks](../benchmarks.md) show the
economic phase scaling roughly linearly while refinement grows super-linearly beyond about
2,000 intervals: at 8,760 hours one measured run spent 13.72 s on economics and 176.69 s on
refinement, and an identical repeat found no refinement solution at all within 1,200 s per
phase.

A run whose economic phase succeeded and whose refinement phase timed out is the
characteristic long-horizon failure. You have no partial result: nothing is published.

### Refinement changed the economic optimum

```text
error: dispatch refinement changed the economic optimum
```

An internal consistency check. The refinement phase is constrained to hold the first
phase's objective within EUR 1e-7, and this fires if the achieved value drifts outside
that. It indicates a numerical problem — very large or very small coefficients — rather than
a modelling one. Rescaling extreme inputs is the remedy.

### Post-solve invariant failures

Before publication the result is re-checked against physics, and any of these raises:

```text
optimized dispatch contains a negative flow
optimized SOC states are not continuous
optimized PV allocation does not conserve energy
optimized dispatch exceeds the grid export limit
optimized dispatch exceeds the grid import limit
optimized dispatch exceeds battery charge power
optimized dispatch exceeds battery discharge power
battery charges and discharges simultaneously
grid import and export occur simultaneously
optimized SOC transition does not conserve energy
optimized SOC leaves the operating window
optimized dispatch misses the terminal SOC target
optimized dispatch fails global energy conservation
```

None of these should ever appear. The solver's output is treated as untrusted and
recomputed against the domain rules, so any of these messages means the solver returned
something physically wrong. Report it with the scenario attached.

## What is not a solver failure

Two error classes are easy to mistake for solve problems because they arrive after a long
wait:

**Financial-layer rejections.** The solve succeeded and the financial evaluation refused
the result:

```text
error: financial evaluation requires terminal SOC to equal initial SOC; inventory
valuation is not implemented

error: the fade parameters drive the year-5 capacity fraction to 0.84, below the validated
minimum_capacity_fraction of 0.85; reduce the fade parameters or shorten project_life_years
```

**Option validation.** Rejected before any solve:

```text
error: time_limit_seconds must be finite and greater than zero
error: relative_mip_gap must be in [0, 1)
```

## Practical timing

Measured on the guide's reference machine, wall clock including interpreter start-up:

| Scenario | Intervals | Wall clock |
| --- | ---: | ---: |
| Sample day | 24 | 3.3 s |
| Synthetic month | 744 | 2.7 s |
| Sensitivity, 7 runs of 24 intervals | 168 total | 2.4 s |

The published per-phase benchmarks give the shape beyond that: 2.75 s at a quarter, 22.5 s
at half a year, and an unreliable 191 s at a full year.

**Practical advice for long horizons:** start with the default 60 s and watch which phase
fails. If refinement is the problem, the options are to shorten the horizon, or to accept
that a year-long single solve is not supported on modest hardware. Raising `--time-limit`
helps only when the solve was going to finish anyway; the published evidence is that at
8,760 intervals it often is not.
