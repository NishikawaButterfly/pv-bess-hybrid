from __future__ import annotations

import json
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pv_bess.cli import main

_SERVE_STACK_AVAILABLE = all(
    find_spec(name) is not None for name in ("fastapi", "uvicorn")
) and any(find_spec(name) is not None for name in ("python_multipart", "multipart"))


class ValidateRunnabilityTests(unittest.TestCase):
    """validate implies runnability, or names precisely what it cannot prove."""

    def setUp(self) -> None:
        self.sample = Path(__file__).resolve().parents[1] / "sample-data" / "scenario.json"

    def _scenario_with_battery(self, directory: Path, **overrides: float) -> Path:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["battery"].update(overrides)
        scenario_path = directory / "scenario.json"
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")
        (directory / "hourly.csv").write_text(
            self.sample.with_name("hourly.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return scenario_path

    def test_the_issues_terminal_soc_case_is_caught_or_declared(self) -> None:
        expected = (
            "error: financial evaluation requires terminal SOC to equal initial SOC; "
            "inventory valuation is not implemented"
        )
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = self._scenario_with_battery(Path(directory), terminal_soc_fraction=0.6)
            with self.assertRaises(SystemExit) as validated:
                main(["validate", "--scenario", str(scenario_path)])
            output = Path(directory) / "results"
            with (
                patch("pv_bess.cli.optimize_dispatch") as solver,
                self.assertRaises(SystemExit) as ran,
            ):
                main(["run", "--scenario", str(scenario_path), "--output", str(output)])
            # validate and run refuse with the run's own message, and run no
            # longer pays for a solve to discover it.
            self.assertEqual(str(validated.exception), expected)
            self.assertEqual(str(ran.exception), expected)
            self.assertEqual(solver.call_count, 0)
            self.assertFalse(output.exists())

    def test_validate_refuses_the_calendar_fade_floor_the_run_would_refuse(self) -> None:
        expected = (
            "error: the fade parameters drive the year-7 capacity fraction to 0.4, below "
            "the validated minimum_capacity_fraction of 0.5; reduce the fade parameters "
            "or shorten project_life_years"
        )
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = self._scenario_with_battery(
                Path(directory),
                calendar_fade_fraction_per_year=0.1,
                minimum_capacity_fraction=0.5,
            )
            with self.assertRaises(SystemExit) as validated:
                main(["validate", "--scenario", str(scenario_path)])
            with (
                patch("pv_bess.cli.optimize_dispatch") as solver,
                self.assertRaises(SystemExit) as ran,
            ):
                main(
                    [
                        "run",
                        "--scenario",
                        str(scenario_path),
                        "--output",
                        str(Path(directory) / "results"),
                    ]
                )
        self.assertEqual(str(validated.exception), expected)
        self.assertEqual(str(ran.exception), expected)
        self.assertEqual(solver.call_count, 0)

    def test_validate_names_what_it_cannot_prove(self) -> None:
        always = [
            "solver resource limits: the optimizer may stop at its per-phase time limit "
            "without producing a dispatch",
            "solver numerical failure: the optimizer may fail numerically or miss its tolerances",
            "returned-solution validation: every dispatch is re-checked against the "
            "model's invariants after the solve and refused if it violates them",
        ]
        output = StringIO()
        with redirect_stdout(output):
            status = main(["validate", "--scenario", str(self.sample)])
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["not_provable_without_solving"], always)

        with tempfile.TemporaryDirectory() as directory:
            scenario_path = self._scenario_with_battery(
                Path(directory), cycling_fade_fraction_per_efc=0.0001
            )
            cycling_output = StringIO()
            with redirect_stdout(cycling_output):
                cycling_status = main(["validate", "--scenario", str(scenario_path)])
        cycling_payload = json.loads(cycling_output.getvalue())
        self.assertEqual(cycling_status, 0)
        self.assertEqual(
            cycling_payload["not_provable_without_solving"],
            [
                *always,
                "capacity-fade floor: with cycling_fade_fraction_per_efc above zero, the "
                "year-by-year capacity floor depends on the solved dispatch's cycling and "
                "only the solve proves it holds",
            ],
        )

    def test_bundled_samples_still_validate_and_run(self) -> None:
        spec = self.sample.with_name("sensitivity-spec.json")
        validate_output = StringIO()
        with redirect_stdout(validate_output):
            self.assertEqual(main(["validate", "--scenario", str(self.sample)]), 0)
        payload = json.loads(validate_output.getvalue())
        self.assertEqual(payload["status"], "valid")
        self.assertIn("not_provable_without_solving", payload)
        with tempfile.TemporaryDirectory() as directory:
            run_output = Path(directory) / "run"
            sensitivity_output = Path(directory) / "sensitivity"
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--scenario",
                            str(self.sample),
                            "--output",
                            str(run_output),
                            "--time-limit",
                            "10",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "sensitivity",
                            "--scenario",
                            str(self.sample),
                            "--spec",
                            str(spec),
                            "--output",
                            str(sensitivity_output),
                            "--time-limit",
                            "10",
                        ]
                    ),
                    0,
                )
            self.assertTrue((run_output / "summary.json").exists())
            self.assertTrue((sensitivity_output / "sensitivity.json").exists())


class CommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = Path(__file__).resolve().parents[1] / "sample-data" / "scenario.json"

    def test_validate_command_returns_machine_readable_evidence(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = main(["validate", "--scenario", str(self.sample)])
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["interval_count"], 24)
        self.assertEqual(len(payload["analysis_input_sha256"]), 64)
        self.assertEqual(payload["warnings"], [])

    def test_validate_warns_about_a_percentage_like_rate_before_solving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = self._scenario_with_rate(Path(directory), 8)
            output = StringIO()
            with redirect_stdout(output):
                status = main(["validate", "--scenario", str(scenario_path)])
        self.assertEqual(status, 0)
        # Still one JSON document on stdout: the warning must not break parsers.
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 0)
        self.assertEqual(payload["status"], "valid")
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("800%", payload["warnings"][0])

    def test_run_command_writes_results_and_enforces_overwrite_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--scenario",
                        str(self.sample),
                        "--output",
                        str(output),
                        "--time-limit",
                        "10",
                        "--mip-gap",
                        "0.000001",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertTrue((output / "summary.json").is_file())
            self.assertTrue((output / "dispatch.csv").is_file())
            self.assertIn("analysis_input_sha256:", stdout.getvalue())

            with self.assertRaisesRegex(SystemExit, "refusing to overwrite"):
                main(
                    [
                        "run",
                        "--scenario",
                        str(self.sample),
                        "--output",
                        str(output),
                    ]
                )
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "run",
                            "--scenario",
                            str(self.sample),
                            "--output",
                            str(output),
                            "--force",
                        ]
                    ),
                    0,
                )

    def _scenario_with_rate(self, directory: Path, rate: float) -> Path:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["financial"]["discount_rate_fraction"] = rate
        scenario_path = directory / "scenario.json"
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")
        (directory / "hourly.csv").write_text(
            self.sample.with_name("hourly.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return scenario_path

    def _scenario_with_escalation(self, directory: Path, escalation: float) -> Path:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["financial"]["annual_opex_escalation_fraction"] = escalation
        scenario_path = directory / "scenario.json"
        scenario_path.write_text(json.dumps(payload), encoding="utf-8")
        (directory / "hourly.csv").write_text(
            self.sample.with_name("hourly.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return scenario_path

    def test_validate_warns_about_a_percentage_like_opex_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenario_path = self._scenario_with_escalation(Path(directory), 1)
            output = StringIO()
            with redirect_stdout(output):
                status = main(["validate", "--scenario", str(scenario_path)])
        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "valid")
        # The sample's discount rate is ordinary, so escalation is the only entry.
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertIn("annual_opex_escalation_fraction", payload["warnings"][0])
        self.assertIn("100%", payload["warnings"][0])

    def test_percentage_like_opex_escalation_is_reported_on_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = self._scenario_with_escalation(directory_path, 1)
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--scenario",
                        str(scenario_path),
                        "--output",
                        str(directory_path / "evidence"),
                    ]
                )
        self.assertEqual(status, 0)
        printed = stdout.getvalue()
        self.assertIn("warning: annual_opex_escalation_fraction", printed)
        self.assertIn("100%", printed)

    def test_percentage_like_discount_rate_is_reported_on_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = self._scenario_with_rate(directory_path, 8)
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--scenario",
                        str(scenario_path),
                        "--output",
                        str(directory_path / "evidence"),
                    ]
                )
        self.assertEqual(status, 0)
        printed = stdout.getvalue()
        self.assertIn("warning: discount_rate_fraction", printed)
        self.assertIn("800%", printed)

    def test_ordinary_discount_rate_prints_no_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "run",
                        "--scenario",
                        str(self.sample),
                        "--output",
                        str(Path(directory) / "evidence"),
                    ]
                )
        self.assertEqual(status, 0)
        self.assertNotIn("warning:", stdout.getvalue())

    def test_invalid_file_is_reported_as_cli_error(self) -> None:
        with self.assertRaisesRegex(SystemExit, "error: cannot access"):
            main(["validate", "--scenario", "missing-scenario.json"])

    def test_invalid_solver_option_is_reported_as_cli_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(SystemExit, "time_limit_seconds"),
        ):
            main(
                [
                    "run",
                    "--scenario",
                    str(self.sample),
                    "--output",
                    directory,
                    "--time-limit",
                    "0",
                ]
            )

    def test_serve_without_api_dependencies_reports_a_clear_error(self) -> None:
        with (
            patch.dict(sys.modules, {"uvicorn": None}),
            self.assertRaisesRegex(SystemExit, r"pip install 'pv-bess-hybrid\[api\]'"),
        ):
            main(["serve"])

    def test_serve_rejects_an_out_of_range_port(self) -> None:
        with self.assertRaisesRegex(SystemExit, "port must be between"):
            main(["serve", "--port", "70000"])

    @unittest.skipUnless(_SERVE_STACK_AVAILABLE, "the optional API dependencies are not installed")
    def test_serve_runs_uvicorn_with_the_requested_binding(self) -> None:
        import uvicorn

        with patch.object(uvicorn, "run") as run:
            status = main(["serve", "--host", "127.0.0.1", "--port", "8123"])
        self.assertEqual(status, 0)
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(run.call_args.kwargs["port"], 8123)

    def test_missing_subcommand_uses_argparse_failure(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            main([])
        self.assertEqual(raised.exception.code, 2)

    def test_module_entrypoint_delegates_to_cli(self) -> None:
        argv = ["pv_bess", "validate", "--scenario", str(self.sample)]
        with (
            patch.object(sys, "argv", argv),
            redirect_stdout(StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_module("pv_bess.__main__", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
