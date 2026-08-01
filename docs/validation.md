# Validation evidence

## Strategy

The test suite verifies analytical outcomes, input failure paths, post-solve physical invariants, finance reconciliation, provenance matching, path confinement, output overwrite protection, and a complete public sample run.

## Independent fixtures

| Fixture | Expected result |
| --- | --- |
| Flat positive price | all available PV below the grid limit exports directly; battery remains idle |
| Asymmetric efficiency | 1,000 kW charged for one hour at 80% followed by discharge at 90% returns 720 kWh AC and restores terminal SOC |
| Grid arbitrage | with unit efficiencies, 1 MWh bought at EUR 10/MWh and sold at EUR 100/MWh produces EUR 90 |
| Terminal SOC | initial stored energy cannot be sold unless an energy source restores the terminal target |
| Negative prices | PV may curtail instead of accepting negative export value |
| 30-minute intervals | 1,000 kW changes energy by 500 kWh before efficiency adjustments |
| NPV | `[-100, 60, 60]` at 10% reconciles to the direct discounted-cash-flow equation |
| IRR | `[-100, 60, 60]` reconciles to the positive quadratic root; multiple-sign-change cash flows return no IRR |

Seeded random scenarios assert energy allocation, SOC bounds, terminal SOC, grid limits, and exclusivity without depending on a particular optimal binary pattern.

## Public sample anchor

With SciPy 1.15.2 and its bundled HiGHS 1.8.0, the committed sample produces:

| Evidence | Expected value |
| --- | ---: |
| Dispatch input SHA-256 | `76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491` |
| Complete analysis SHA-256 | `c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8` |
| PV energy | 40.2 MWh |
| Baseline curtailment | 1.6 MWh |
| Optimized curtailment | 0 MWh |
| Incremental operating value | EUR 764.525 per modeled day |
| Equivalent full cycles | 0.45 |
| 15-year NPV | EUR -3,818,737.08 |
| LCOS | EUR 265.97/MWh |

The negative sample NPV is intentional evidence that the software reports the configured assumptions instead of forcing a favorable investment conclusion. The fixture is synthetic and its 365x annualization is only a calculation demonstration.

## Numerical tolerances

- flow values within `1e-6 kW` of zero are normalized to zero;
- interval energy-balance and SOC residuals must be within `1e-4 kWh`;
- tests use analytical tolerances appropriate to each expected value;
- achieved MIP gap is persisted with each result.

## Commands

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

CI additionally requires Ruff formatting/linting, strict mypy, branch coverage, package build, and runtime dependency audit.

## Release evidence still required

Before the first tagged alpha release:

1. an independent reviewer must approve equations, sign conventions, and LCOS treatment;
2. CI must be green on Python 3.12 and 3.13;
3. an 8,760-interval benchmark must publish runtime, hardware, solver gap, versions, and input hash;
4. the release must include an SBOM, checksums, and notes tied to the exact commit.
