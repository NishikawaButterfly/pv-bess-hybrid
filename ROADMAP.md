# Product roadmap

## Current release gate — auditable kernel

- [x] explicit units, time base, provenance, and schema version;
- [x] validated PV, price, battery, grid, and financial inputs;
- [x] sparse MILP with charge/discharge and import/export exclusivity;
- [x] terminal SOC, PV-only baseline, solver evidence, and immutable result artifacts;
- [x] analytical, failure-path, end-to-end, and seeded invariant tests;
- [ ] independent review of equations and financial conventions;
- [ ] CI green on Python 3.12 and 3.13 with at least 90% branch coverage in the scientific and financial kernel;
- [ ] benchmark a complete 8,760-interval scenario and publish the hardware, runtime, solver gap, and input hash;
- [ ] tag the first alpha release with SBOM, checksums, and release notes.

## Next — scenario analysis

- full-year licensed or synthetic fixtures with DST and missing-data policies;
- sensitivity tables for price spread, CAPEX, efficiency, degradation cost, and discount rate;
- deterministic stress cases and seeded Monte Carlo assumptions;
- replacement schedules and explicitly versioned degradation models;
- workbook and PDF evidence generated only from result objects.

## Later — product shell

- versioned `/api/v1` contract and RFC 9457 errors;
- bounded asynchronous jobs only after measured workloads justify them;
- responsive, keyboard-accessible review interface;
- PostgreSQL persistence, migrations, container hardening, health checks, and deployment runbooks.

## Deferred specialist modules

Electrical protection, transformer, cable, thermal, EMF, grid-code, equipment-selection, and certification features require separate validated methods and independent domain review. They will not be reintroduced merely by porting the historical formulas.
