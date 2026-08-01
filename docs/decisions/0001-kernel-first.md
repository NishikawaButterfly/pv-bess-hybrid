# ADR 0001: Rebuild the validated kernel before the product shell

- Status: accepted
- Date: 2026-08-01

## Context

The historical prototype generated attractive reports but mixed unrelated engineering domains, embedded inputs and claims in code, and did not reconcile its dispatch and financial outputs. Building a web interface around those calculations would amplify risk and make defects harder to isolate.

## Decision

The supported product begins as a typed Python package with a bounded file contract, sparse MILP, post-solve invariants, independent financial functions, deterministic sample, CLI, and evidence artifacts. FastAPI, React, PostgreSQL, Docker, and asynchronous jobs are deferred until the kernel meets its release gate.

Historical scripts were retired; a migration note records what was removed and why. Unsupported engineering and compliance domains are not ported.

## Consequences

- The first alpha has a smaller visible feature set but a defensible calculation boundary.
- API and UI work will reuse one tested domain implementation instead of duplicating formulas.
- Schema and scientific model versions can evolve independently from presentation code.
- Some original features may never return unless authoritative methods and independent fixtures become available.
