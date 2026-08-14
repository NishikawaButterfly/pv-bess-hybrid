# 9. Running a dispatch: the CLI

The command line is the primary interface and the only one that writes durable artifacts.

## Installing

Python 3.12 or 3.13.

```bash
python -m venv .venv
source .venv/bin/activate           # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install --no-deps -e .
```

The kernel needs only NumPy and SciPy. The HTTP API and the Excel export are optional
extras (`requirements-api.txt`, `requirements-xlsx.txt`), and neither is imported unless
you use it.

## The five subcommands

```text
pv-bess [-h] {validate,run,sensitivity,serve,export-xlsx} ...
```

| Subcommand | Purpose |
| --- | --- |
| `validate` | Read and check a scenario without solving it |
| `run` | Solve one scenario and write the evidence pair |
| `sensitivity` | Rerun one scenario across one-at-a-time variants |
| `serve` | Start the optional HTTP API |
| `export-xlsx` | Re-read a completed run directory as an Excel workbook |

## Validate first

```bash
pv-bess validate --scenario sample-data/scenario.json
```

```json
{
  "analysis_input_sha256": "c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8",
  "dispatch_input_sha256": "76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491",
  "interval_count": 24,
  "interval_hours": 1.0,
  "scenario": "Synthetic 5 MW PV plus 5 MW / 20 MWh BESS",
  "status": "valid",
  "warnings": []
}
```

Costs nothing, catches most input mistakes, and gives you the hashes before you commit to a
long solve. `warnings` is empty when nothing looks mistyped; a non-empty array names an
input that is inside its validated range but probably wrong, such as a discount rate
entered as a percentage. What `status: valid` still does not promise is covered in
[the data contract chapter](04-data-contract-in-practice.md#two-things-status-valid-does-not-mean).

## Run

```bash
pv-bess run \
  --scenario sample-data/scenario.json \
  --output results/sample
```

```text
summary: ...\results\sample\summary.json
dispatch: ...\results\sample\dispatch.csv
dispatch_input_sha256: 76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491
analysis_input_sha256: c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8
```

The four lines are the complete output for a clean run. No NPV, no solver status: to see
any number you open `summary.json`. That the hashes appear here and in both artifacts is
deliberate: it is what lets you tie a transcript to a file later.

The one thing that is printed about the run itself is a warning, and only when there is
one. Warnings come first, above the paths, so a long output does not scroll them away:

```text
warning: discount_rate_fraction is 8, which the model read as 800% per year; a value
above 1.0 is usually a percentage entered as a fraction, and 8% would be 0.08. NPV,
discounted payback, and LCOS use 800%.
summary: ...\results\sample\summary.json
```

The same warnings are written to `summary.json` under `financial_summary.warnings`, so
they survive the terminal.

Measured wall clock on the guide's reference machine, including interpreter start-up:
3.3 seconds for the 24-hour sample, 2.7 seconds for the 744-hour month.

### Options

| Option | Default | Notes |
| --- | ---: | --- |
| `--scenario` | required | Path to the scenario JSON |
| `--output` | required | Directory for `summary.json` and `dispatch.csv` |
| `--time-limit` | 60.0 | Seconds **per solver phase**, so the worst case is twice this |
| `--mip-gap` | 1e-8 | Requested relative MIP gap |
| `--force` | off | Replace existing artifacts |

Both numeric options are validated:

```text
error: time_limit_seconds must be finite and greater than zero
error: relative_mip_gap must be in [0, 1)
```

`--time-limit` applies to each of the two phases separately. The throughput-refinement
phase is the one that dominates on long horizons, so a scenario that survives its economic
phase can still fail on refinement — see [solver status](24-solver-status.md).

Loosening `--mip-gap` is the usual first move on a slow scenario, but note that it does not
change the run's identity: raising it to 0.1 on the sample produced a **byte-identical**
`dispatch.csv`, with the only difference in `summary.json` being the recorded
`requested_relative_mip_gap` itself. The gap is a stopping criterion, not an input to the
problem, and the hashes do not cover it.

### Overwrite protection

Both artifacts are written together or not at all, and neither is replaced silently:

```text
error: refusing to overwrite summary.json, dispatch.csv; pass --force to replace them
```

Pass `--force` when you mean it. Publication is staged and rolled back as a pair on
ordinary errors, but fixed-path replacement of two files is not crash-atomic — which is
precisely why both files carry both hashes. Compare them before trusting a pair.

## Sensitivity

```bash
pv-bess sensitivity \
  --scenario sample-data/scenario.json \
  --spec sample-data/sensitivity-spec.json \
  --output results/sensitivity
```

```text
sensitivity_json: ...\results\sensitivity\sensitivity.json
sensitivity_csv: ...\results\sensitivity\sensitivity.csv
base_dispatch_input_sha256: 76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491
base_analysis_input_sha256: c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8
```

Seven runs — a base plus six variants — in 2.4 seconds on the reference machine. The base
row's hashes match a plain `run` of the same scenario exactly, which is the check that the
sensitivity layer is not a different calculation. Covered in
[chapter 21](21-sensitivity.md).

## Exit behaviour

Success is exit code 0. Every error path is exit code 1 with a single line on stderr
prefixed `error: `. There are no warning-level messages and no partial successes: a run
either produces both artifacts or produces neither.

```bash
pv-bess run --scenario broken/scenario.json --output results/x
# error: CSV header must be exactly: timestamp,pv_power_kw,market_price_eur_per_mwh
# exit 1
```

For scripting, the exit code is the reliable signal. The message text is stable enough to
read but is not a documented interface.

## Scripting a batch

There is no built-in batch mode, no scenario library, and no run index. A sweep is a shell
loop, and everything about organising the outputs is yours:

```bash
for s in scenarios/*/scenario.json; do
  name=$(basename "$(dirname "$s")")
  pv-bess run --scenario "$s" --output "results/$name" || echo "FAILED: $name"
done
```

Two things worth building into any such loop: capture the exit code, because a failed
scenario prints one line and disappears; and record the dispatch hash next to each result,
because nothing in the output directory names the scenario that produced it.
