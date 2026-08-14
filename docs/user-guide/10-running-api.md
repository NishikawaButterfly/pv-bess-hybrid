# 10. Running a dispatch: the API

The HTTP layer is an optional transport around the unchanged kernel. It performs no
calculation and holds no state; it stages the two uploaded files and runs exactly the path
the CLI runs.

## Starting it

```bash
python -m pip install -r requirements-api.txt
python -m pip install --no-deps -e .
pv-bess serve --host 127.0.0.1 --port 8000
```

Without the extra, the command tells you so rather than failing obscurely:

```text
error: the API dependencies are not installed; install the 'api' extra
(pip install 'pv-bess-hybrid[api]'): ...
```

The default host is `127.0.0.1`, which is the right default. This is a single-process
server with no authentication, no rate limiting, and no request quota — see
[the deployment note](#what-this-server-is-not) below.

## GET /health

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "kernel_version": "0.1.0",
  "schema_version": "1.0",
  "model_version": "dispatch-milp-1.0",
  "solver_interface_name": "scipy.optimize.milp",
  "solver_interface_version": "1.18.0",
  "solver_backend_name": "HiGHS",
  "solver_backend_version": "1.12.0"
}
```

More useful than a liveness probe: it is the fastest way to read the exact solver stack a
result came from. If two environments disagree about a number, compare their `/health`
payloads first.

## POST /api/v1/dispatch

Two file parts, `scenario` and `time_series`, the same pair the CLI reads:

```bash
curl -F scenario=@sample-data/scenario.json \
     -F time_series=@sample-data/hourly.csv \
     http://127.0.0.1:8000/api/v1/dispatch
```

A 200 response carries the whole `summary.json` payload plus one addition:

| Key | Contents |
| --- | --- |
| `dispatch_input_sha256`, `analysis_input_sha256` | Provenance hashes |
| `scenario_name`, `schema_version`, `model_version`, `generated_at_utc` | Run identity |
| `solver` | Interface and backend versions, requested gap, per-phase status |
| `units` | The unit of every reported quantity |
| `dispatch_summary` | The dispatch KPIs |
| `financial_summary` | Cash flows and the financial metrics |
| `limitations` | The short limitations list |
| `dispatch_intervals` | **The per-interval series, which the CLI puts in `dispatch.csv`** |

`dispatch_intervals` is the API's one departure from the CLI's output shape, and it is the
reason the web page can draw charts from a single request. The fields match `dispatch.csv`
column for column, minus the two per-row hashes.

Verified against the sample: the API returns dispatch hash
`76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491` and NPV
EUR -3,818,737.07961859 — identical to the CLI, as it must be, since it is the same code.
The request completed in 0.15 seconds and returned 11,735 bytes for 24 intervals.

## Status codes

The split between 400 and 422 is meaningful and worth using.

| Code | Meaning | Example |
| ---: | --- | --- |
| 200 | Solved and evaluated | — |
| 400 | The file itself is defective | `CSV header must be exactly: ...` |
| 400 | " | `unknown battery key(s): round_trip_efficiency` |
| 422 | Well-formed file, impossible values | `charge_efficiency must be greater than zero and at most one` |
| 422 | " | `timestamps must have a uniform interval with no gaps` |
| 422 | " | `the current model supports EUR market and financial inputs only` |
| 422 | No feasible dispatch | `dispatch optimization failed with status 2: The problem is infeasible. ...` |
| 422 | Rejected by the financial layer | `financial evaluation requires terminal SOC to equal initial SOC; ...` |
| 413 | Upload beyond the size limits | 1 MB scenario, 25 MB time series |
| 500 | Unhandled error, detail suppressed | `{"detail": "internal server error"}` |

All the above except 413 and 500 were exercised directly; the messages are verbatim.

The practical reading: **400 means fix the file, 422 means fix the project.** A 400 is a
schema or syntax problem. A 422 means the software understood you perfectly and what you
described cannot be done — an impossible parameter, a contradictory scenario, or a battery
that cannot meet its terminal target.

Note that a 422 costs a full solve when the cause is infeasibility, because the solver has
to prove it. On a large scenario that is not a cheap error.

## No persistence

Nothing is stored. The uploads are staged in a temporary directory, the results are written
to a temporary directory, the payload is returned, and all of it is deleted. There is no
run history, no job queue, no way to retrieve a previous result, and no artifact on disk.

If you need durable evidence, use the CLI, or save the JSON response yourself. The response
contains everything `summary.json` contains, plus the intervals, so it is a complete record
— it simply is not written down for you.

## Long solves

The request is synchronous: the connection stays open for the whole solve, with the
kernel's default 60-second-per-phase limit applying. There is no job submission and no
polling. A scenario near the practical solve limit will hold a connection for minutes and
may exceed any proxy timeout between you and the server.

The bundled web page gives up at 180 seconds:

```text
The dispatch request timed out after 180 seconds.
```

That is a client-side timeout, not a server one. The solve continues on the server until
its own limit expires.

## What this server is not

Run it on localhost or on a trusted network. It has no authentication, no authorisation,
no rate limiting, no request logging, and no protection against a single expensive request
occupying the process — a MILP solve is CPU-bound and the server is single-process, so one
large scenario blocks everything else.

The [architecture](../architecture.md) document is explicit that the HTTP layer is a
transport for local and trusted use, not a hosted service. Treat the public demonstration
instance the same way: a place to see the output shape, not a place to send a real
project's data.
