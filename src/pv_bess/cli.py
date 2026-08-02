"""Command-line interface for reproducible PV-BESS scenario runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NoReturn

from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import (
    ScenarioFileError,
    load_scenario,
    load_sensitivity_spec,
    write_results,
    write_sensitivity_results,
)
from pv_bess.provenance import analysis_sha256, scenario_sha256
from pv_bess.sensitivity import run_sensitivity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pv-bess",
        description="Validate and optimize auditable PV-BESS scenarios.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a scenario without solving it")
    validate.add_argument("--scenario", type=Path, required=True)

    run = subparsers.add_parser("run", help="solve a scenario and export immutable evidence")
    run.add_argument("--scenario", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--time-limit", type=float, default=60.0)
    run.add_argument("--mip-gap", type=float, default=1e-8)
    run.add_argument("--force", action="store_true")

    sensitivity = subparsers.add_parser(
        "sensitivity",
        help="rerun one scenario across bounded one-at-a-time parameter variants",
    )
    sensitivity.add_argument("--scenario", type=Path, required=True)
    sensitivity.add_argument("--spec", type=Path, required=True)
    sensitivity.add_argument("--output", type=Path, required=True)
    sensitivity.add_argument("--time-limit", type=float, default=60.0)
    sensitivity.add_argument("--mip-gap", type=float, default=1e-8)
    sensitivity.add_argument("--force", action="store_true")

    serve = subparsers.add_parser("serve", help="serve the optional dispatch API over HTTP")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    export_xlsx = subparsers.add_parser(
        "export-xlsx", help="export a completed run directory to an Excel workbook"
    )
    export_xlsx.add_argument("--input", type=Path, required=True)
    export_xlsx.add_argument("--output", type=Path, required=True)
    export_xlsx.add_argument("--force", action="store_true")
    return parser


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def _serve(host: str, port: int) -> int:
    """Import the web stack lazily so a kernel-only install stays web-free."""

    if not 0 <= port <= 65_535:
        _fail("port must be between 0 and 65535")
    try:
        import uvicorn

        from pv_bess.api import create_app

        application = create_app()
    except (ImportError, RuntimeError) as exc:
        _fail(
            "the API dependencies are not installed; install the 'api' extra "
            f"(pip install 'pv-bess-hybrid[api]'): {exc}"
        )
    uvicorn.run(application, host=host, port=port)
    return 0


def _export_xlsx(input_directory: Path, output_path: Path, *, force: bool) -> int:
    """Import the workbook writer lazily so a kernel-only install stays Excel-free."""

    try:
        from pv_bess.xlsx import export_workbook
    except ImportError as exc:
        _fail(
            "the Excel dependencies are not installed; install the 'xlsx' extra "
            f"(pip install 'pv-bess-hybrid[xlsx]'): {exc}"
        )
    try:
        workbook_path = export_workbook(input_directory, output_path, force=force)
    except (FileExistsError, ValueError) as exc:
        _fail(str(exc))
    print(f"workbook: {workbook_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        return _serve(args.host, args.port)
    if args.command == "export-xlsx":
        return _export_xlsx(args.input, args.output, force=args.force)
    try:
        scenario, financial_assumptions = load_scenario(args.scenario)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "status": "valid",
                        "scenario": scenario.name,
                        "interval_count": len(scenario.intervals),
                        "interval_hours": scenario.interval_hours,
                        "dispatch_input_sha256": scenario_sha256(scenario),
                        "analysis_input_sha256": analysis_sha256(scenario, financial_assumptions),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "sensitivity":
            spec = load_sensitivity_spec(args.spec)
            result = run_sensitivity(
                scenario,
                financial_assumptions,
                spec,
                time_limit_seconds=args.time_limit,
                relative_mip_gap=args.mip_gap,
            )
            json_path, csv_path = write_sensitivity_results(args.output, result, force=args.force)
            print(f"sensitivity_json: {json_path}")
            print(f"sensitivity_csv: {csv_path}")
            print(f"base_dispatch_input_sha256: {result.base.dispatch_input_sha256}")
            print(f"base_analysis_input_sha256: {result.base.analysis_input_sha256}")
            return 0

        dispatch = optimize_dispatch(
            scenario,
            time_limit_seconds=args.time_limit,
            relative_mip_gap=args.mip_gap,
        )
        financial = evaluate_financials(dispatch, scenario, financial_assumptions)
        summary_path, dispatch_path = write_results(
            args.output, dispatch, financial, force=args.force
        )
        print(f"summary: {summary_path}")
        print(f"dispatch: {dispatch_path}")
        print(f"dispatch_input_sha256: {dispatch.input_sha256}")
        print(f"analysis_input_sha256: {financial.analysis_input_sha256}")
        return 0
    except (DispatchOptimizationError, FileExistsError, ScenarioFileError, ValueError) as exc:
        _fail(str(exc))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
