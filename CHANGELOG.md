# Changelog

All notable changes are documented here. The format follows Keep a Changelog and releases use Semantic Versioning.

## [Unreleased]

### Added

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
