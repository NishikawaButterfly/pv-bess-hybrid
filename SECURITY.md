# Security policy

## Supported versions

This repository is an engineering alpha. Security fixes are applied to the latest commit on `main`; there is no supported deployed service yet.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or exposed secret. Email [nishikawa.butterfly@gmail.com](mailto:nishikawa.butterfly@gmail.com) with:

- affected commit and file;
- reproduction steps;
- expected impact;
- suggested remediation, if known.

Receipt should be acknowledged within seven days. No bounty or response-time guarantee is offered.

## Data handling

- The supported package performs no network calls.
- Scenario companions are restricted to the scenario directory.
- Scenario JSON is limited to 1 MB, CSV input to 25 MB and 100,000 rows.
- CSV schemas and timestamps are strict; NaN and infinite domain values are rejected.
- Result files are written atomically and are not silently overwritten.
- Never commit client, employer, site, credential, licensed market, or non-redistributable vendor data.

## Deployment boundary

There is no authentication, API, database, or hosted demo in this alpha. Any future service needs a separate threat review, least-privilege runtime, TLS termination, closed CORS, rate/resource limits, and secret management before network exposure.
