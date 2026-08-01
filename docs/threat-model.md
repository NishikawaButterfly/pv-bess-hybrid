# Threat model

## Scope

This model covers the local CLI, JSON/CSV ingestion, optimization, and JSON/CSV export. There is no network service, identity system, database, or cloud deployment in the alpha.

## Assets

- integrity of calculation inputs and outputs;
- confidentiality of user-supplied time series;
- availability of the local workstation;
- provenance linking a result to the exact input and model;
- credibility of public engineering claims.

## Trust boundaries and mitigations

| Threat | Current mitigation | Residual risk |
| --- | --- | --- |
| oversized input exhausts memory | JSON/CSV byte and row limits | accepted MILP can still consume material memory/time |
| path traversal reads another file | companion path must be relative and remain under scenario directory | symlink behavior depends on host filesystem and resolved target |
| malformed or non-finite numbers corrupt math | typed parsing and finite/range validation | extreme finite magnitudes may still degrade conditioning |
| solver returns partial/invalid result | success required; domain invariants independently recomputed | solver/library defects remain possible |
| stale result is paired with another scenario | canonical SHA-256 input hash checked before finance | hash does not prove input authorship |
| output silently destroys or mixes prior evidence | exact targets require `--force`; both files are staged and the prior pair is restored if publication fails | a process or host crash cannot provide a portable multi-file atomicity guarantee |
| CSV formula injection | exported dispatch fields are numeric or ISO timestamps | future free-text exports need explicit neutralization |
| confidential data is published | public policy permits only fictional/redistributable inputs | repository review and contributor judgment remain necessary |
| unsupported legacy claims are mistaken as current | historical scripts removed from the current tree; migration warning retained | old source is not distributed with this repository |

## Future service requirements

Before any API or UI is exposed: authenticate users, authorize server-side, isolate jobs, rate-limit uploads and solve time, store secrets externally, close CORS, terminate TLS, scan artifacts, log request IDs without input data, define retention/deletion, and test backup/restore and incident runbooks.
