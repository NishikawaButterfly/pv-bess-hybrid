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
