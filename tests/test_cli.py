from __future__ import annotations

import json
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pv_bess.cli import main


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
