# 11. Running a dispatch: the web explorer

The API server also serves a static results page at its root. Open
`http://127.0.0.1:8000/` after `pv-bess serve`, upload the two files, and the page renders
the financial summary next to hand-drawn SVG charts. A public demonstration instance runs
the same page.

It is plain HTML, CSS, and JavaScript with no frontend dependencies. It calls the same
`/api/v1/dispatch` endpoint you could call yourself.

## What the page does

Two file inputs, one button. The button stays disabled until both files are chosen:

> **Waiting for input files** — Choose a scenario JSON and its time-series CSV to enable
> the run.

Once both are selected it reports readiness, naming the files:

> **Ready to run** — scenario.json and hourly.csv will be posted to the dispatch API.

and on success:

> **Dispatch complete** — Synthetic 5 MW PV plus 5 MW / 20 MWh BESS was solved; the charts
> below show this scenario only.

The result header restates the run's shape, which is a useful check that the file you
uploaded is the one you meant:

> Synthetic 5 MW PV plus 5 MW / 20 MWh BESS · 24 intervals of 1 h · solver status: optimal

## The metric cards

Seven cards, with an eighth appearing only when the scenario configures capacity fade.
Running the repository sample through the page produced:

| Card | Displayed | Underlying value |
| --- | --- | ---: |
| NPV | `-3,818,737 EUR` | -3,818,737.07961859 |
| IRR | `-11.25%` | -0.11248640232702162 |
| Simple payback | `Not reached` | `null` |
| Discounted payback | `Not reached` | `null` |
| LCOS | `265.97 EUR/MWh` | 265.9735362230494 |
| Curtailment reduction | `100%` | 1.0 |
| Equivalent full cycles | `0.45 cycles` | 0.45 |
| End-of-life capacity | hidden | no fade configured |

The cards are rounded for display; the API response behind them carries full precision.
**Never transcribe a figure from the page into a report** — take it from the JSON or from
`summary.json`. The NPV card alone drops eight significant figures.

Two label choices are worth knowing. A `null` IRR displays as `Not defined`, and a `null`
payback as `Not reached` — both are real outcomes with specific meanings, covered in
[chapter 17](17-irr.md) and [chapter 18](18-payback.md), not display errors. The cycles
card is explicitly captioned "over the uploaded series, not per year", which is the
distinction most likely to be misread.

## The charts

Three panels, each with a "View as a table" disclosure beneath it:

| Panel | Series |
| --- | --- |
| PV production and market price | PV production, market price |
| Battery charge, discharge, and state of charge | Battery charge (PV plus grid), battery discharge, SOC at interval end |
| Grid export, grid import, and curtailment | Grid export, grid import for charging, curtailed PV |

The tables are the more useful half for checking a schedule, and they carry the same
per-interval numbers to two decimals. They are **truncated at 1,000 rows**, so a monthly
scenario's tables show the first 1,000 of 744 — fine — while a quarterly one silently shows
you a prefix. The charts themselves plot the whole series.

## Client-side limits

The page checks file sizes before uploading and reports the limit in bytes rather than
making you discover a 413. It gives up on a slow solve after 180 seconds — a client
timeout, not a server one; the solve continues server-side.

## Two things the page will not do

### There is no export

There is no download button, no "save result", and no copy-to-clipboard anywhere on the
page. The result exists only in the browser until you navigate away. To keep a result, use
the CLI, or post to the API yourself and save the response.

The tables can be selected and copied by hand, at two decimal places and up to 1,000 rows.
That is the entire export story.

### A failed run leaves the previous result on screen

This one can mislead, and is worth stating plainly.

Uploading a defective file after a successful run updates the status panel to an error:

> **Dispatch failed** — The uploaded files were rejected as defective. CSV header must be
> exactly: timestamp,pv_power_kw,market_price_eur_per_mwh

but the results block below it is **not cleared, hidden, or dimmed**. Verified after a
deliberate failure: the NPV card still read `-3,818,737 EUR`, the charts still showed 25
table rows, and the result header still named the previous scenario — all at full opacity,
with no visual distinction of any kind. The only indication that these numbers belong to a
different file is the status panel above them.

A user who scrolls past the status line, or who does not notice the change, will read the
old scenario's economics as the new one's. When you use the page, after any failure,
**reload before reading anything**.

## When to use which interface

| Interface | Good for | Poor for |
| --- | --- | --- |
| Web explorer | First look at a scenario, seeing the shape of a schedule, showing someone the model | Anything you need to keep, precise figures, batches |
| API | Integration, scripted runs, getting intervals in one response | Durable evidence — nothing is stored |
| CLI | Everything that must be reproducible or filed | Quick visual inspection |

The explorer is a demonstration surface. Real work goes through the CLI, and every number
that leaves your desk should come from a `summary.json` you still have.
