from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pv_bess.dispatch import optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import ScenarioFileError, load_scenario, write_results
from pv_bess.models import FinancialAssumptions
from tests.helpers import make_scenario


class InputOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = Path(__file__).resolve().parents[1] / "sample-data" / "scenario.json"

    def test_sample_scenario_runs_end_to_end(self) -> None:
        scenario, assumptions = load_scenario(self.sample)
        dispatch = optimize_dispatch(scenario)
        financial = evaluate_financials(dispatch, scenario, assumptions)
        self.assertEqual(len(dispatch.intervals), 24)
        self.assertEqual(
            dispatch.input_sha256,
            "76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491",
        )
        self.assertEqual(
            financial.analysis_input_sha256,
            "c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8",
        )
        self.assertAlmostEqual(dispatch.summary.pv_energy_mwh, 40.2)
        self.assertAlmostEqual(dispatch.summary.curtailed_energy_mwh, 0)
        self.assertAlmostEqual(dispatch.summary.incremental_operating_value_eur, 764.525)
        self.assertAlmostEqual(dispatch.summary.equivalent_full_cycles, 0.45)
        self.assertAlmostEqual(financial.npv_eur, -3_818_737.07961859)
        self.assertAlmostEqual(financial.lcos_eur_per_mwh or 0, 265.9735362230494)
        self.assertIsNone(financial.capacity_fade)
        # The sample's rate of 0.08 is ordinary, so the warning channel is empty
        # and every published figure above is unchanged by its existence.
        self.assertEqual(financial.warnings, ())
        with tempfile.TemporaryDirectory() as directory:
            summary_path, dispatch_path = write_results(directory, dispatch, financial)
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertNotIn("capacity_fade", payload["financial_summary"])
            self.assertEqual(payload["financial_summary"]["warnings"], [])
            self.assertEqual(payload["dispatch_input_sha256"], dispatch.input_sha256)
            self.assertEqual(payload["analysis_input_sha256"], financial.analysis_input_sha256)
            self.assertEqual(payload["solver"]["phases"]["economic"]["status"], "optimal")
            self.assertEqual(payload["solver"]["phases"]["refinement"]["status"], "optimal")
            self.assertRegex(payload["solver"]["backend_version"], r"^\d+\.\d+")
            self.assertEqual(len(dispatch_path.read_text(encoding="utf-8").splitlines()), 25)
            with dispatch_path.open(encoding="utf-8", newline="") as handle:
                first_row = next(csv.DictReader(handle))
            self.assertEqual(first_row["dispatch_input_sha256"], dispatch.input_sha256)
            self.assertEqual(first_row["analysis_input_sha256"], financial.analysis_input_sha256)
            with self.assertRaises(FileExistsError):
                write_results(directory, dispatch, financial)
            write_results(directory, dispatch, financial, force=True)

    def test_battery_fade_keys_load_and_flow_into_the_summary(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["battery"]["calendar_fade_fraction_per_year"] = 0.01
        payload["battery"]["cycling_fade_fraction_per_efc"] = 0.0001
        payload["battery"]["minimum_capacity_fraction"] = 0.6
        csv_content = self.sample.with_name("hourly.csv").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = directory_path / "scenario.json"
            scenario_path.write_text(json.dumps(payload), encoding="utf-8")
            (directory_path / "hourly.csv").write_text(csv_content, encoding="utf-8")
            scenario, assumptions = load_scenario(scenario_path)
            self.assertEqual(scenario.battery.calendar_fade_fraction_per_year, 0.01)
            self.assertEqual(scenario.battery.cycling_fade_fraction_per_efc, 0.0001)
            self.assertEqual(scenario.battery.minimum_capacity_fraction, 0.6)

            dispatch = optimize_dispatch(scenario)
            financial = evaluate_financials(dispatch, scenario, assumptions)
            self.assertIsNotNone(financial.capacity_fade)
            summary_path, _ = write_results(directory_path / "results", dispatch, financial)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        fade = summary["financial_summary"]["capacity_fade"]
        self.assertEqual(fade["calendar_fade_fraction_per_year"], 0.01)
        fractions = fade["capacity_fraction_by_year"]
        self.assertEqual(len(fractions), 15)
        self.assertEqual(fractions[0], 1.0)
        self.assertLess(fractions[-1], 1.0)
        self.assertGreaterEqual(fractions[-1], 0.6)

    def test_percentage_like_discount_rate_warning_reaches_the_summary(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["financial"]["discount_rate_fraction"] = 8
        csv_content = self.sample.with_name("hourly.csv").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = directory_path / "scenario.json"
            scenario_path.write_text(json.dumps(payload), encoding="utf-8")
            (directory_path / "hourly.csv").write_text(csv_content, encoding="utf-8")
            scenario, assumptions = load_scenario(scenario_path)
            dispatch = optimize_dispatch(scenario)
            financial = evaluate_financials(dispatch, scenario, assumptions)
            summary_path, _ = write_results(directory_path / "results", dispatch, financial)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # The rate never enters the dispatch problem, so the published dispatch
        # anchor is untouched while the analysis hash and the figures move.
        self.assertEqual(
            summary["dispatch_input_sha256"],
            "76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491",
        )
        warnings = summary["financial_summary"]["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("discount_rate_fraction", warnings[0])
        self.assertIn("800%", warnings[0])

    def test_failed_pair_publish_restores_the_previous_artifacts(self) -> None:
        original_scenario, original_assumptions = load_scenario(self.sample)
        original_dispatch = optimize_dispatch(original_scenario)
        original_financial = evaluate_financials(
            original_dispatch, original_scenario, original_assumptions
        )
        replacement_scenario = make_scenario([2_000, 0], [10, 100])
        replacement_dispatch = optimize_dispatch(replacement_scenario)
        replacement_financial = evaluate_financials(
            replacement_dispatch,
            replacement_scenario,
            FinancialAssumptions(0, 0, 1, 0),
        )

        with tempfile.TemporaryDirectory() as directory:
            summary_path, dispatch_path = write_results(
                directory, original_dispatch, original_financial
            )
            original_summary = summary_path.read_bytes()
            original_csv = dispatch_path.read_bytes()
            real_replace = Path.replace
            failure_injected = False

            def fail_second_stage(source: Path, target: str | Path) -> Path:
                nonlocal failure_injected
                destination = Path(target)
                if (
                    not failure_injected
                    and source.name.endswith(".stage.tmp")
                    and destination.name == "dispatch.csv"
                ):
                    failure_injected = True
                    raise OSError("synthetic second-artifact failure")
                return real_replace(source, target)

            with (
                patch.object(Path, "replace", new=fail_second_stage),
                self.assertRaisesRegex(OSError, "second-artifact failure"),
            ):
                write_results(
                    directory,
                    replacement_dispatch,
                    replacement_financial,
                    force=True,
                )

            self.assertTrue(failure_injected)
            self.assertEqual(summary_path.read_bytes(), original_summary)
            self.assertEqual(dispatch_path.read_bytes(), original_csv)
            self.assertEqual(list(Path(directory).glob(".*.tmp")), [])

    def test_writer_rejects_mismatched_dispatch_and_finance_results(self) -> None:
        scenario, assumptions = load_scenario(self.sample)
        financial = evaluate_financials(optimize_dispatch(scenario), scenario, assumptions)
        unrelated_dispatch = optimize_dispatch(make_scenario([0, 0], [0, 0]))
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "does not belong"),
        ):
            write_results(directory, unrelated_dispatch, financial)

    def test_companion_path_cannot_escape_scenario_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "name": "unsafe",
                        "time_series_csv": "../outside.csv",
                        "dataset": {},
                        "battery": {},
                        "grid": {},
                        "financial": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScenarioFileError, "stay inside"):
                load_scenario(path)

    def test_unknown_schema_version_is_rejected(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["schema_version"] = "999"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioFileError, "schema_version"):
                load_scenario(path)

    def test_csv_row_with_extra_field_is_rejected(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["time_series_csv"] = "bad.csv"
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = directory_path / "scenario.json"
            scenario_path.write_text(json.dumps(payload), encoding="utf-8")
            (directory_path / "bad.csv").write_text(
                "timestamp,pv_power_kw,market_price_eur_per_mwh\n"
                "2026-01-01T00:00:00+00:00,0,10,unexpected\n"
                "2026-01-01T01:00:00+00:00,0,10,unexpected\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScenarioFileError, "more fields"):
                load_scenario(scenario_path)

    def test_unknown_financial_key_is_rejected(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["financial"]["annualization_facter"] = 365
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioFileError, "unknown financial"):
                load_scenario(path)

    def test_duplicate_json_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(
                '{"schema_version":"1.0","schema_version":"2.0"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ScenarioFileError, "duplicate JSON key"):
                load_scenario(path)

    def test_malformed_and_non_object_json_are_rejected(self) -> None:
        for content, message in (("{", "invalid scenario JSON"), ("[]", "JSON object")):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "scenario.json"
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ScenarioFileError, message):
                    load_scenario(path)

    def test_invalid_section_and_scalar_types_are_rejected(self) -> None:
        cases = (
            (("battery",), [], "battery must be a JSON object"),
            (("name",), " ", "name must be a non-blank string"),
            (("dataset", "synthetic"), "yes", "synthetic must be true or false"),
            (
                ("battery", "energy_capacity_kwh"),
                True,
                "energy_capacity_kwh must be a JSON number",
            ),
            (
                ("financial", "project_life_years"),
                1.5,
                "project_life_years must be a JSON integer",
            ),
        )
        csv_content = self.sample.with_name("hourly.csv").read_text(encoding="utf-8")
        for keys, value, message in cases:
            with self.subTest(keys=keys), tempfile.TemporaryDirectory() as directory:
                payload = json.loads(self.sample.read_text(encoding="utf-8"))
                target = payload
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                directory_path = Path(directory)
                scenario_path = directory_path / "scenario.json"
                scenario_path.write_text(json.dumps(payload), encoding="utf-8")
                (directory_path / "hourly.csv").write_text(csv_content, encoding="utf-8")
                with self.assertRaisesRegex(ScenarioFileError, message):
                    load_scenario(scenario_path)

    def test_absolute_or_missing_companion_file_is_rejected(self) -> None:
        for absolute, message in ((True, "relative path"), (False, "cannot access")):
            with self.subTest(absolute=absolute), tempfile.TemporaryDirectory() as directory:
                payload = json.loads(self.sample.read_text(encoding="utf-8"))
                companion = (
                    str((Path(directory) / "outside.csv").resolve()) if absolute else "missing.csv"
                )
                payload["time_series_csv"] = companion
                path = Path(directory) / "scenario.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ScenarioFileError, message):
                    load_scenario(path)

    def test_invalid_csv_header_and_row_are_rejected(self) -> None:
        cases = (
            ("market_price_eur_per_mwh,pv_power_kw,timestamp\n", "header must be exactly"),
            (
                "timestamp,pv_power_kw,market_price_eur_per_mwh\nnot-a-timestamp,0,10\n",
                "invalid CSV row 2",
            ),
        )
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["time_series_csv"] = "invalid.csv"
        for csv_content, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                directory_path = Path(directory)
                scenario_path = directory_path / "scenario.json"
                scenario_path.write_text(json.dumps(payload), encoding="utf-8")
                (directory_path / "invalid.csv").write_text(csv_content, encoding="utf-8")
                with self.assertRaisesRegex(ScenarioFileError, message):
                    load_scenario(scenario_path)

    def test_z_timestamps_and_implicit_terminal_soc_are_supported(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["time_series_csv"] = "short.csv"
        payload["battery"].pop("terminal_soc_fraction")
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = directory_path / "scenario.json"
            scenario_path.write_text(json.dumps(payload), encoding="utf-8")
            (directory_path / "short.csv").write_text(
                "timestamp,pv_power_kw,market_price_eur_per_mwh\n"
                "2026-01-01T00:00:00Z,0,10\n"
                "2026-01-01T01:00:00Z,0,10\n",
                encoding="utf-8",
            )
            scenario, _ = load_scenario(scenario_path)
        self.assertEqual(
            scenario.battery.resolved_terminal_soc_fraction,
            scenario.battery.initial_soc_fraction,
        )
        self.assertIsNotNone(scenario.intervals[0].timestamp.utcoffset())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
