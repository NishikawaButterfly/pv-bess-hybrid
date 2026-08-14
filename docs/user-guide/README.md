# PV-BESS Dispatch & Investment Analysis User Guide

A working guide for the engineer or analyst sizing a solar-plus-storage project with this
model: how to prepare the inputs, configure a scenario, run the dispatch, and read the
economics without over-claiming.

This guide sits above the reference documents. It does not restate the mathematics — the
[methodology](../methodology.md) holds the formulation, the [data contract](../data-contract.md)
holds the field-by-field schema, and [limitations](../limitations.md) holds the model
boundary. What this guide adds is the path a user actually walks, and the judgement needed
at each step.

Every number, message, and status quoted in these chapters was produced by running the
software. The [reproducibility](23-reproducibility.md) chapter records the exact versions.

## Chapters

### Understanding the model

| # | Chapter | What it answers |
| --: | --- | --- |
| 1 | [Introduction and scope](01-introduction-and-scope.md) | What the model decides, and what it takes as given |

### Preparing inputs

| # | Chapter | What it answers |
| --: | --- | --- |
| 2 | [Preparing PV production data](02-preparing-pv-data.md) | Where the PV series comes from and how to shape it |
| 3 | [Preparing market prices](03-preparing-market-prices.md) | Which price series to use and what it must represent |
| 4 | [The data contract in user terms](04-data-contract-in-practice.md) | What the validator will and will not accept |
| 5 | [Scenario configuration](05-scenario-configuration.md) | Assembling a scenario file section by section |
| 6 | [Battery parameters](06-battery-parameters.md) | Capacity, power, SOC window, and the degradation reserve |
| 7 | [Grid constraints](07-grid-constraints.md) | Export and import limits at the point of connection |
| 8 | [Charge and discharge efficiencies](08-efficiencies.md) | The two directional efficiencies, and the round-trip trap |

### Running a dispatch

| # | Chapter | What it answers |
| --: | --- | --- |
| 9 | [Running a dispatch: the CLI](09-running-cli.md) | The command line, options, and exit behaviour |
| 10 | [Running a dispatch: the API](10-running-api.md) | The HTTP transport and its status codes |
| 11 | [Running a dispatch: the web explorer](11-running-web-explorer.md) | The browser page and what it will not do |

### Reading the dispatch

| # | Chapter | What it answers |
| --: | --- | --- |
| 12 | [Reading the dispatch schedule](12-reading-the-schedule.md) | Column by column through `dispatch.csv` |
| 13 | [Understanding state of charge](13-state-of-charge.md) | Why SOC moves the way it does |
| 14 | [Understanding curtailment](14-curtailment.md) | When curtailment is a loss and when it is the right answer |
| 15 | [Understanding grid charging](15-grid-charging.md) | What allowing imports does to the schedule and the economics |

### Reading the economics

| # | Chapter | What it answers |
| --: | --- | --- |
| 16 | [Net present value](16-npv.md) | The NPV convention and what it excludes |
| 17 | [Internal rate of return](17-irr.md) | Why IRR is sometimes withheld |
| 18 | [Payback](18-payback.md) | Simple and discounted payback, and their blind spots |
| 19 | [Levelized cost of storage](19-lcos.md) | What goes into the ratio, and why it is not a value metric |
| 20 | [Degradation and the multi-year run](20-degradation-multi-year.md) | Capacity fade, and the scaling simplification behind it |
| 21 | [Sensitivity analysis](21-sensitivity.md) | Moving one parameter at a time |

### Working with results

| # | Chapter | What it answers |
| --: | --- | --- |
| 22 | [Exporting results](22-exporting-results.md) | The artifacts, the workbook, and what cannot be exported |
| 23 | [Reproducibility](23-reproducibility.md) | What fixes a result, and what would change it |
| 24 | [Solver status and what each means](24-solver-status.md) | Reading the two solver phases |
| 25 | [Common infeasibilities](25-infeasibilities.md) | Why a scenario has no solution, and how to fix it |

### Worked examples

| # | Chapter | What it answers |
| --: | --- | --- |
| 26 | [A worked 24-hour example](26-worked-example-24h.md) | One day, hour by hour, with the arithmetic shown |
| 27 | [A worked multi-year example](27-worked-example-multi-year.md) | A 744-hour month carried across a 15-year life |

### Reference

| # | Chapter | What it answers |
| --: | --- | --- |
| 28 | [Limitations](28-limitations.md) | What the numbers do not cover |
| 29 | [Troubleshooting](29-troubleshooting.md) | Symptom, cause, fix |
| 30 | [Glossary](30-glossary.md) | Terms and units as this model uses them |

## Before you quote a number

Three sentences worth internalising before any output leaves your desk:

1. A result is a **scenario calculation**, not a forecast. The model optimises against the
   price series you gave it, with perfect foresight over the whole horizon.
2. The financial metrics are **unlevered and pre-tax**, and exclude tax, debt, grants,
   replacements, and salvage value.
3. A positive NPV demonstrates nothing about technical feasibility, grid-code compliance,
   or equipment suitability. Those are outside the model entirely.
