# Known limitations

## Model boundary

- One aggregated PV source, battery, and point of connection are modeled.
- Power is treated as constant within each interval.
- Network, inverter, transformer, auxiliary, and availability losses are absent except for directional battery efficiencies.
- No ramp rate, reserve, minimum dwell time, temperature dependence, or capacity replacement is modeled. Calendar and cycling capacity fade exist in the financial layer only; the dispatch schedule never sees them.
- Grid import is used only for battery charging; local load is not modeled.
- Buy and sell prices use the same input series. Tariffs, imbalance, fees, taxes, and market access constraints are absent.

## Financial boundary

- Cash flows are unlevered, pre-tax, and nominal.
- The bundled examples (an annualized synthetic day and an annualized synthetic month) are calculation demonstrations, not investment cases.
- LCOE is not implemented; LCOS follows the documented scenario convention.
- Multi-year capacity fade scales the single representative dispatch. Dispatch is not re-solved per year: every project year reuses the same schedule multiplied by that year's capacity fraction, although a genuinely faded battery would reshape its schedule rather than shrink it uniformly, and cycling fade accrues at the year-one cycle count in every year. Re-solving each project year at reduced capacity is future work because even one full-year solve is already slow and unreliable on modest hardware; see [benchmarks.md](benchmarks.md).
- IRR is intentionally omitted for absent or ambiguous conventional roots.
- Debt, covenants, tax, grants, depreciation, replacements, salvage, and probabilistic analysis are deferred.

## Engineering boundary

The supported package does not perform short-circuit, protection, cable, transformer, thermal, ventilation, EMF, arc-flash, harmonic, grid-code, equipment-selection, or certification calculations. Historical attempts were removed from the current tree; the migration note explains why.

## Operational boundary

- There is no API, UI, authentication, persistence, multi-user workflow, backup, or hosted service.
- The CLI is intended for trusted local execution with untrusted input files subject to documented bounds.
- A 100,000-row input limit does not guarantee that every accepted MILP will solve inside the default time limit. A full 8,760-hour year is already unreliable on modest hardware; measured timings per horizon are in [benchmarks.md](benchmarks.md).
- Result files are staged and rolled back as a pair on ordinary publication errors, but fixed-path multi-file replacement is not crash-atomic. Consumers must compare the hashes embedded in both artifacts.

## Interpretation

Outputs are not a substitute for licensed engineering judgment, market advice, site studies, vendor guarantees, applicable codes, or project-specific due diligence. A positive NPV does not demonstrate technical feasibility; a feasible dispatch does not demonstrate equipment or grid compliance.
