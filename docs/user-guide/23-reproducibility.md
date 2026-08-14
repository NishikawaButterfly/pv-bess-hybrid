# 23. Reproducibility

A result is reproducible when someone else, later, can get the same numbers and prove it.
This chapter separates what the software fixes for you from what you must fix yourself.

## The two hashes

Every run records two SHA-256 values over a canonical serialization of its inputs.

| Hash | Covers |
| --- | --- |
| `dispatch_input_sha256` | Scenario name, dataset metadata, battery (excluding fade), grid, and every interval's timestamp, PV, and price |
| `analysis_input_sha256` | All of the above **plus** every financial assumption, plus the fade parameters when non-zero |

Both appear in `summary.json`, on every row of `dispatch.csv`, in the API response, in the
workbook, and in `pv-bess validate` output. Two runs with the same dispatch hash solved the
same optimisation problem.

The split is useful. Change `discount_rate_fraction` and the dispatch hash is unchanged
while the analysis hash moves — a signal that the schedule is the same and only the
financial layer differs. Verified: adding fade parameters to a scenario left the dispatch
hash at `2f7d715d83a02b049f2de285fa178f79e9732b15a437b1d70cf38119bfab04bf` and changed only
the analysis hash.

## What fixes a result

Run the sample twice into different directories, and `dispatch.csv` is **byte-identical**
while `summary.json` differs in exactly one field: `generated_at_utc`. That is the whole of
the software's non-determinism.

So a result is fixed by:

**The scenario JSON and the CSV, byte for byte.** Both are hashed. A trailing newline in
the CSV, a reordered JSON key, or a changed scenario `name` all change the hash — the name
in particular changes the dispatch hash without changing a single number.

**The solver stack.** SciPy's version and the HiGHS backend version are recorded in
`summary.json` and returned by `/health`. A different HiGHS build can select a different
optimal vertex when several are tied.

**The model version.** `dispatch-milp-1.0` identifies the formulation.

**The refinement phase.** This is the underappreciated one. A MILP often has many schedules
achieving the same optimal value — the battery could take the same energy from different
hours. The second solve minimises battery throughput subject to the economic optimum,
which collapses most of that ambiguity to a single answer. Without it, two runs could
report different schedules with identical economics.

## What does not fix a result

**`--mip-gap` and `--time-limit` are not hashed.** They are stopping criteria, not inputs.
Raising the gap to 0.1 on the sample produced a byte-identical `dispatch.csv`; the only
difference in `summary.json` was the recorded `requested_relative_mip_gap` itself.

That is a convenience and a trap. Two runs with the same dispatch hash *should* produce the
same schedule, but on a scenario where a loose gap stops the solver early, they might not.
The guard is `achieved_relative_mip_gap`, recorded per phase: if it reads 0.0, the solve was
proved optimal and the gap setting did not matter.

**`generated_at_utc` is not part of anything.** It records when a file was written and
nothing else.

**The output directory is not recorded.** Nothing in a result names the scenario file that
produced it, or where it was run.

## What would change a result

In descending order of likelihood:

| Change | Dispatch hash | Result |
| --- | --- | --- |
| Any input value | changes | changes |
| Scenario `name` | changes | unchanged |
| Dataset metadata text | changes | unchanged |
| Financial assumptions | unchanged | financials change |
| Fade parameters | unchanged | financials change |
| SciPy or HiGHS version | unchanged | may change among tied optima |
| `--mip-gap`, `--time-limit` | unchanged | should not change; verify the achieved gap |
| Platform, CPU, thread count | unchanged | may change among tied optima |

The rows where the hash is unchanged but the result can move are the ones worth guarding
against. Recording the solver versions alongside the hash covers them.

## The published anchors

The repository publishes expected values for both fixtures, and reproducing them is the
fastest way to validate an installation.

| Fixture | Dispatch hash | Analysis hash |
| --- | --- | --- |
| 24-hour sample | `76d3d912…d769b491` | `c8c1af3b…e97cdab8` |
| 744-hour month | `45d62c07…01964958` | `a9b25aae…b8a26e884` |

Both reproduced exactly on the guide's environment (SciPy 1.18.0, HiGHS 1.12.0), together
with the documented KPIs: 40.2 MWh PV, 1.6 MWh baseline curtailment, EUR 764.525 incremental
value, 0.45 equivalent full cycles, EUR -3,818,737.08 NPV, and EUR 265.97/MWh LCOS.

Note that the published anchors were originally recorded against SciPy 1.15.2 with HiGHS
1.8.0 and still hold on a much newer stack. That is meaningful evidence of stability, not a
guarantee.

## What to record with a result

The minimum for a number you expect to defend:

1. Both hashes.
2. The `solver` block from `summary.json` — interface version, backend version, both phase
   statuses, and both achieved MIP gaps.
3. `model_version` and `schema_version`.
4. The scenario file and its CSV, archived together.
5. The `annualization_factor` and what period it scales, in words.

Points 4 and 5 are the ones people skip. A hash proves two runs used the same inputs; it
cannot tell you what those inputs were. `summary.json` does not echo the scenario values,
so without the scenario file a hash is only a fingerprint of something you no longer have.

## Reproducing someone else's run

1. Get the scenario JSON and CSV.
2. `pv-bess validate` and compare both hashes against the original. If they differ, the
   files differ — stop and find out how.
3. Compare your `/health` or `summary.json` solver block against theirs.
4. Run, and compare `dispatch.csv` byte for byte.

If the hashes match, the solver versions match, and the dispatch differs, you have found
something worth reporting.
