# Changelog

All notable changes are documented here. The format follows Keep a Changelog and releases use Semantic Versioning.

## [Unreleased]

### Added

- warnings for financial assumptions that validate but are probably mistyped. A `discount_rate_fraction` above `1.0` — most often a percentage typed as a fraction, such as `8` for 8% — is now reported with the value and how the model read it, instead of silently producing an NPV and LCOS wrong by orders of magnitude. Warnings are generated once in the financial kernel and carried on the result, so `pv-bess validate`, `pv-bess run`, `pv-bess sensitivity`, `summary.json` (`financial_summary.warnings`), `sensitivity.json`, the HTTP API, and the Excel Summary sheet all report the same text. A rate above 100% is legal and occasionally intended, so it is warned about and calculated, never refused; no calculated value, provenance hash, or exit status changes.

- a warning for a percentage-typed `annual_opex_escalation_fraction`: a value above `0.25` — most often `1` typed for 1% — is reported with the value and how the model read it, on the same surfaces as the discount-rate warning, and the two coexist when both inputs are mistyped. No calculated value, provenance hash, or exit status changes.

- `capex_eur` and `discount_rate_fraction` as sensitivity parameters. Neither enters the dispatch optimization, so their variants share the base solve: the row keeps the base `dispatch_input_sha256` while `analysis_input_sha256` and the financial metrics move, and nothing is re-solved for effect. Every sensitivity row now also reports the `capex_eur` it was evaluated under and the kernel's `warnings` for its own assumptions (appended `capex_eur` and `warnings` columns in `sensitivity.csv`, matching fields on each row of `sensitivity.json`), and the CLI prints a warning a scanned value introduced labelled with its variant. Existing specs without capacity variants gain only these appended fields; every existing value, threshold, warning text, and provenance hash is unchanged.

- a `not_provable_without_solving` array in the `pv-bess validate` output, naming the failure classes only a solve can rule out: the solver's per-phase time limit, its numerical failure modes, the post-solve invariant validation of every returned dispatch, and — only when `cycling_fade_fraction_per_efc` is above zero — the capacity-fade floor that depends on the solved dispatch's cycling. Purely additive to the validate JSON; no calculated value, provenance hash, or exit code changes.

### Changed

- `pv-bess validate` now refuses two scenarios it previously accepted, with the same message the run produces, because both refusals are decidable from the inputs alone: a `terminal_soc_fraction` different from `initial_soc_fraction` (the financial layer requires equality; previously discovered only after a full solve), and a calendar-only fade projection that breaches `minimum_capacity_fraction` within the project life. `run`, `sensitivity`, and the API refuse the same preconditions before solving instead of after — same error type, text, and status, only earlier — so the most expensive operation in the product is never spent discovering a predictable refusal. A consequence worth naming: a scenario that passes `validate` can no longer be MILP-infeasible, since every structural infeasibility requires a terminal target different from the initial SOC, and with equality the idle battery satisfies every constraint.

- an `energy_capacity_kwh` sensitivity entry now requires `capex_eur_per_kwh`, the marginal cost of capacity: each variant's CAPEX is derived as the base CAPEX plus the capacity delta times the declared cost, and reported on its row. A capacity entry without the declaration — previously accepted, with every size inheriting the base CAPEX — is refused with a message naming the field, because a sweep that prices a bigger battery the same as a smaller one biases every sizing conclusion toward the larger battery. The bundled `sample-data/sensitivity-spec.json` declares `250` (the linear cost implied by its own base pair) and also scans both new financial axes.

## [0.1.0] - 2026-08-02

### Added

- optional multi-year battery capacity fade (`calendar_fade_fraction_per_year`, `cycling_fade_fraction_per_efc`, `minimum_capacity_fraction`): per-year capacity fractions scale operating benefit and discharged energy consistently across NPV and LCOS, surface in `summary.json`, the web page, and the Excel Summary sheet, and default to zero so existing scenarios, results, and hashes are byte-identical;

- bounded one-at-a-time sensitivity layer (`pv-bess sensitivity`) with a JSON spec, a 32-run cap, per-variant input hashes, and paired `sensitivity.json`/`sensitivity.csv` outputs (`docs/sensitivity.md`);

- `pv-bess export-xlsx`, an Excel export of a completed run directory (Summary, Cash flows, and Dispatch sheets) behind the optional `xlsx` extra;
- deterministic synthetic monthly sample (`sample-data/monthly/`) generated by the seeded `tools/make_synthetic_year.py`, with byte-for-byte reproducibility and hash-anchored tests;
- published solver benchmarks per horizon, including the 8,760-interval measurement required by the roadmap (`docs/benchmarks.md`);
- typed and validated scenario, battery, grid, dataset, and financial models;
- sparse hourly MILP with SOC, efficiency, power, POI, direction, and terminal constraints;
- PV-only baseline and independently recomputed operating metrics;
- unlevered pre-tax NPV, conventional IRR, payback, and LCOS calculations;
- bounded local ingestion, staged pair publication with rollback, artifact hashing, solver evidence, and a CLI;
- deterministic synthetic example, analytical/invariant tests, CI, and engineering documentation.

### Changed

- public project language is now US English and all supported calculations live under `src/pv_bess/`.

### Removed from supported scope

- historical electrical-design, thermal, EMF, equipment-selection, compliance, and hard-coded report claims. The old source is not distributed in this repository.
