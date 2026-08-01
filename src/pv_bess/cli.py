"""Command-line interface for reproducible PV-BESS scenario runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NoReturn

from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import ScenarioFileError, load_scenario, write_results
from pv_bess.provenance import analysis_sha256, scenario_sha256


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
    return parser


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
