# Architecture

## Context

The product evaluates one bounded PV-BESS scenario locally. The first release deliberately keeps scientific code independent from web frameworks, databases, report templates, and vendor-specific engineering modules.

## Calculation flow

```mermaid
flowchart LR
    A["Versioned scenario JSON"] --> C["Bounded validator"]
    B["Uniform time-series CSV"] --> C
    C --> D["Immutable domain model"]
    D --> E["Sparse SciPy/HiGHS MILP"]
    E --> F["Post-solve physical invariants"]
    F --> G["Recomputed dispatch KPIs"]
    G --> H["Incremental financial model"]
    H --> I["Atomic summary.json"]
    F --> J["Atomic dispatch.csv"]
    D --> K["Canonical SHA-256 input hash"]
    K --> I
```

## Modules

| Module | Responsibility | Must not own |
| --- | --- | --- |
| `models.py` | immutable types, units, and domain validation | solver or file I/O |
| `provenance.py` | canonical scenario serialization and hashing | timestamps of result generation |
| `dispatch.py` | MILP construction, solve, invariant checks, and operating KPIs | financial assumptions or presentation |
| `finance.py` | cash flows and investment metrics | dispatch decisions |
| `io.py` | bounded input and failure-safe paired result publication | business formulas |
| `cli.py` | user-facing orchestration and exit behavior | duplicated calculations |
| `api.py` (optional) | HTTP transport for the same orchestration under `/api/v1` | calculations or validation rules |

## API boundary

`api.py` is an optional HTTP transport installed through the `api` extra and started with `pv-bess serve`. It stages the two uploaded files in a temporary directory and runs the exact `load_scenario`, `optimize_dispatch`, `evaluate_financials`, and `write_results` path the CLI runs, returning the resulting `summary.json` payload. Upload sizes are bounded by the same limits `io.py` enforces on disk, kernel errors map to 400 (defective file), 422 (well-formed file with impossible values), or 413 (oversized upload), and no calculation, validation rule, or state lives in the layer. FastAPI is imported nowhere outside `api.py`, so a kernel-only install remains web-free.

## Trust boundaries

1. JSON/CSV files are untrusted until bounded and validated.
2. Solver output is untrusted until all physical invariants are recomputed.
3. Financial calculations accept only a dispatch result whose input hash matches the supplied scenario.
4. Exported evidence distinguishes inputs, solver metadata, operating KPIs, cash flows, units, and limitations.

## Dependency policy

The domain package has two runtime dependencies: NumPy for numerical vectors and SciPy for sparse matrices and the HiGHS-backed MILP interface. No module opens a network connection. Direct runtime versions are pinned in `requirements.txt`; supported ranges are declared in `pyproject.toml`.

## Future boundaries

- PostgreSQL will persist scenario metadata and immutable result references, not solver internals.
- Long-running annual scenarios will use jobs only after benchmarks define the synchronous envelope.
- The Energy Asset Investment Lab may consume a versioned result bundle but will not import ORM models or share a database.
