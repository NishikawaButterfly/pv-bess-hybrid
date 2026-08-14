# 22. Exporting results

Three artifacts exist: the run pair, the sensitivity pair, and an optional Excel workbook.
This chapter covers what each contains and what you cannot get out of the product.

## The run pair

`pv-bess run` writes `summary.json` and `dispatch.csv` into the output directory. They
belong together and both carry both provenance hashes.

`summary.json` contains, in sorted-key order:

| Block | Contents |
| --- | --- |
| `generated_at_utc` | Wall-clock time of the run — the only non-deterministic field |
| `scenario_name`, `schema_version`, `model_version` | Run identity |
| `dispatch_input_sha256`, `analysis_input_sha256` | Provenance |
| `solver` | Interface and backend versions, requested gap, per-phase status, message, achieved gap, objective |
| `units` | The unit of every reported quantity |
| `dispatch_summary` | 15 dispatch KPIs |
| `financial_summary` | Cash flows, NPV, IRR, both paybacks, LCOS, `warnings`, and `capacity_fade` when configured |
| `limitations` | Three sentences that should travel with any quoted figure |

`financial_summary.warnings` is always present and usually empty. When it is not, it names
an assumption that validated but is probably mistyped, and the Excel export renders it as a
`Warnings` section on the Summary sheet. Treat a non-empty array as something to resolve
before the figures leave your desk.

`dispatch.csv` carries the 15 per-interval columns described in
[chapter 12](12-reading-the-schedule.md), prefixed by the two hashes on every row.

Neither file is overwritten silently:

```text
error: refusing to overwrite summary.json, dispatch.csv; pass --force to replace them
```

The pair is staged and rolled back together on ordinary errors, but fixed-path replacement
of two files is not crash-atomic. **Compare the hashes in the two files before trusting
them as a pair** — that is exactly why the hashes are repeated on every CSV row.

## The Excel workbook

```bash
pv-bess export-xlsx --input results/sample --output results/sample/report.xlsx
```

```text
workbook: ...\results\sample\report.xlsx
```

It needs the optional `xlsx` extra. It re-reads a **completed run directory** — it does not
solve anything — and cross-checks that every `dispatch.csv` row's hashes match
`summary.json` before writing. A mismatched pair is rejected rather than exported.

Three sheets:

| Sheet | Contents |
| --- | --- |
| `Summary` | Run, Provenance, Solver, Dispatch KPIs, Financial KPIs, Capacity fade (when present), Limitations |
| `Cash flows` | Year and cash flow, one row per year including year 0 |
| `Dispatch` | The 15 per-interval columns, without the hash columns |

Verified on the sample: 52 rows on Summary, 17 on Cash flows (year 0 through 15 plus a
header), and 25 rows by 15 columns on Dispatch. Formatting is deliberately sober — bold
headers, number formats, frozen header rows — with no charts and no conditional colours.
Workbook metadata is set to `pv-bess-hybrid` for both creator and last-modified-by, so no
personal identity leaks into a file you circulate.

`null` values render as `n/a`, so a scenario with no IRR shows `n/a` rather than an empty
cell that could be mistaken for zero.

Like `run`, it refuses to overwrite:

```text
error: refusing to overwrite report.xlsx; pass --force to replace it
```

## The sensitivity pair

`pv-bess sensitivity` writes `sensitivity.json` and `sensitivity.csv`. The CSV is flat and
ready for a spreadsheet:

```text
label,parameter,mode,value,dispatch_input_sha256,analysis_input_sha256,market_value_eur,
npv_eur,irr_fraction,simple_payback_years,discounted_payback_years,lcos_eur_per_mwh
```

One row per run, base first. Null metrics are empty cells. There is no `export-xlsx`
equivalent for sensitivity results.

## What you cannot export

Worth knowing before you plan a deliverable around this tool.

**No per-interval data in the sensitivity output.** Each variant reports six scalars. The
schedules that produced them are solved, used, and discarded — so you cannot see *why* a
variant behaved differently, only that it did. Reproducing a variant's schedule means
rebuilding it as a standalone scenario and running it again.

**No workbook for sensitivity results.** `export-xlsx` handles run directories only.

**Nothing from the web explorer.** No download button, no copy-to-clipboard, no save. The
result exists in the browser until you navigate away. See
[chapter 11](11-running-web-explorer.md).

**No charts anywhere durable.** The explorer draws SVG charts on screen; the workbook
deliberately contains none. Any figure for a report is drawn by you from `dispatch.csv`.

**No comparison artifact.** Comparing two runs means opening two `summary.json` files. There
is no diff, no multi-run table, and no report that places scenarios side by side. Every
comparison table in this guide was assembled by hand from separate run directories.

**No scenario echo in the output.** `summary.json` records the scenario *name* and its
hashes but not the input values themselves. You cannot reconstruct the battery capacity or
the discount rate from a result — you need the scenario file that produced it. Keep them
together.

## A workable filing habit

Since the product provides no run index, impose one:

```text
studies/
  2026-06-baseline/
    scenario.json
    hourly.csv
    results/
      summary.json
      dispatch.csv
      report.xlsx
```

One directory per scenario, inputs and outputs together, and the dispatch hash recorded
wherever the result is quoted. That hash is the only thing that ties a number in a
presentation back to the files that produced it, and it is the first thing anyone checking
your work will ask for.
