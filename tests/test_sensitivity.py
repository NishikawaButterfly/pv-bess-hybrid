from __future__ import annotations

import csv
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

from pv_bess.cli import main
from pv_bess.dispatch import optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import load_sensitivity_spec
from pv_bess.models import FinancialAssumptions
from pv_bess.sensitivity import (
    MAX_TOTAL_RUNS,
    SensitivitySpec,
    SensitivitySpecError,
    SensitivityVariant,
    apply_variant,
    parse_sensitivity_spec,
    run_sensitivity,
)
from tests.helpers import make_scenario


def _spec(parameters: dict[str, Any]) -> SensitivitySpec:
    return parse_sensitivity_spec({"schema_version": "1.0", "parameters": parameters})


class SensitivitySpecTests(unittest.TestCase):
    def test_unknown_parameter_is_rejected_with_the_supported_list(self) -> None:
        expected = (
            "unknown sensitivity parameter 'capex_eur'; supported parameters: "
            "charge_efficiency, degradation_cost_eur_per_mwh_dc_discharged, "
            "discharge_efficiency, energy_capacity_kwh, market_price_level, power_kw"
        )
        with self.assertRaises(SensitivitySpecError) as raised:
            _spec({"capex_eur": {"values": [1]}})
        self.assertEqual(str(raised.exception), expected)

    def test_specs_beyond_the_run_cap_are_rejected(self) -> None:
        values = [float(index) for index in range(1, MAX_TOTAL_RUNS + 1)]
        with self.assertRaisesRegex(
            SensitivitySpecError,
            rf"requests {MAX_TOTAL_RUNS + 1} runs .* at most {MAX_TOTAL_RUNS} runs",
        ):
            _spec({"energy_capacity_kwh": {"values": values}})

    def test_market_price_level_accepts_multipliers_only(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "multipliers only"):
            _spec({"market_price_level": {"values": [50]}})

    def test_malformed_specs_are_rejected(self) -> None:
        cases: tuple[tuple[str, Any], ...] = (
            ("must be a JSON object", ["not", "an", "object"]),
            ("unknown spec key", {"schema_version": "1.0", "parameters": {}, "grid": {}}),
            ("schema_version must be", {"parameters": {"power_kw": {"values": [1]}}}),
            ("non-empty JSON object", {"schema_version": "1.0", "parameters": {}}),
            (
                "exactly one of",
                {
                    "schema_version": "1.0",
                    "parameters": {"power_kw": {"values": [1], "multipliers": [1]}},
                },
            ),
            (
                "non-empty JSON array",
                {"schema_version": "1.0", "parameters": {"power_kw": {"values": []}}},
            ),
            (
                "must be JSON numbers",
                {"schema_version": "1.0", "parameters": {"power_kw": {"values": [True]}}},
            ),
            (
                "greater than zero",
                {"schema_version": "1.0", "parameters": {"power_kw": {"multipliers": [0]}}},
            ),
            (
                "duplicate variant",
                {"schema_version": "1.0", "parameters": {"power_kw": {"values": [5, 5]}}},
            ),
        )
        for pattern, payload in cases:
            with (
                self.subTest(pattern=pattern),
                self.assertRaisesRegex(SensitivitySpecError, pattern),
            ):
                parse_sensitivity_spec(payload)

    def test_bundled_sample_spec_loads(self) -> None:
        sample = Path(__file__).resolve().parents[1] / "sample-data" / "sensitivity-spec.json"
        spec = load_sensitivity_spec(sample)
        self.assertEqual(len(spec.variants), 6)
        self.assertEqual(spec.variants[0].label, "market_price_level*0.8")
        self.assertEqual(spec.variants[-1].label, "degradation_cost_eur_per_mwh_dc_discharged=20")


class SensitivityRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = make_scenario([2_000, 0], [10, 100])
        self.assumptions = FinancialAssumptions(
            capex_eur=1_000,
            annual_fixed_opex_eur=10,
            project_life_years=5,
            discount_rate_fraction=0.08,
            annualization_factor=365,
        )

    def test_base_run_equals_a_direct_kernel_run(self) -> None:
        spec = _spec({"market_price_level": {"multipliers": [1.2]}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        dispatch = optimize_dispatch(self.scenario)
        financial = evaluate_financials(dispatch, self.scenario, self.assumptions)
        self.assertEqual(result.base.label, "base")
        self.assertIsNone(result.base.parameter)
        self.assertEqual(result.base.dispatch_input_sha256, dispatch.input_sha256)
        self.assertEqual(result.base.analysis_input_sha256, financial.analysis_input_sha256)
        self.assertAlmostEqual(result.base.market_value_eur, dispatch.summary.market_value_eur)
        self.assertAlmostEqual(result.base.npv_eur, financial.npv_eur)
        self.assertAlmostEqual(result.base.lcos_eur_per_mwh or 0, financial.lcos_eur_per_mwh or 0)

    def test_price_multipliers_move_npv_in_the_expected_direction(self) -> None:
        spec = _spec({"market_price_level": {"multipliers": [0.8, 1.2]}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        lower, higher = result.variants
        self.assertEqual(lower.label, "market_price_level*0.8")
        self.assertEqual(higher.label, "market_price_level*1.2")
        self.assertLess(lower.market_value_eur, result.base.market_value_eur)
        self.assertGreater(higher.market_value_eur, result.base.market_value_eur)
        self.assertLess(lower.npv_eur, result.base.npv_eur)
        self.assertGreater(higher.npv_eur, result.base.npv_eur)
        self.assertNotEqual(lower.dispatch_input_sha256, result.base.dispatch_input_sha256)
        self.assertNotEqual(higher.analysis_input_sha256, result.base.analysis_input_sha256)

    def test_variants_change_only_the_intended_fields(self) -> None:
        capacity = apply_variant(
            self.scenario, SensitivityVariant("energy_capacity_kwh", "absolute", 1_500)
        )
        self.assertEqual(capacity.battery.energy_capacity_kwh, 1_500)
        self.assertEqual(capacity.battery.max_charge_power_kw, 1_000)

        power = apply_variant(self.scenario, SensitivityVariant("power_kw", "multiplier", 0.5))
        self.assertEqual(power.battery.max_charge_power_kw, 500)
        self.assertEqual(power.battery.max_discharge_power_kw, 500)
        self.assertEqual(power.battery.energy_capacity_kwh, 2_000)

        priced = apply_variant(
            self.scenario, SensitivityVariant("market_price_level", "multiplier", 1.5)
        )
        self.assertEqual(priced.intervals[1].market_price_eur_per_mwh, 150)
        self.assertEqual(priced.intervals[1].pv_power_kw, 0)
        self.assertEqual(priced.battery, self.scenario.battery)

    def test_invalid_variant_scenarios_fail_before_any_solve(self) -> None:
        spec = _spec({"charge_efficiency": {"multipliers": [1.5]}})
        with self.assertRaisesRegex(SensitivitySpecError, "produces an invalid scenario"):
            run_sensitivity(self.scenario, self.assumptions, spec)

    def test_shared_assumption_warnings_are_carried_once_for_the_whole_table(self) -> None:
        spec = _spec({"market_price_level": {"multipliers": [0.8, 1.2]}})
        ordinary = run_sensitivity(self.scenario, self.assumptions, spec)
        self.assertEqual(ordinary.warnings, ())

        mistyped = replace(self.assumptions, discount_rate_fraction=8.0)
        result = run_sensitivity(self.scenario, mistyped, spec)
        # One entry for the table, not one per run: every row shares the rate.
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("800%", result.warnings[0])
        self.assertEqual(len(result.variants), 2)


class SensitivityCommandLineTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.scenario = root / "sample-data" / "scenario.json"
        self.spec = root / "sample-data" / "sensitivity-spec.json"

    def test_cli_writes_agreeing_json_and_csv_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sensitivity"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "sensitivity",
                        "--scenario",
                        str(self.scenario),
                        "--spec",
                        str(self.spec),
                        "--output",
                        str(output),
                        "--time-limit",
                        "10",
                    ]
                )
            self.assertEqual(status, 0)
            self.assertIn("base_analysis_input_sha256:", stdout.getvalue())
            self.assertNotIn("warning:", stdout.getvalue())

            payload = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["warnings"], [])
            with (output / "sensitivity.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(payload["run_count"], 7)
            self.assertEqual(len(rows), 7)
            self.assertEqual(rows[0]["label"], "base")
            self.assertEqual(
                payload["base"]["dispatch_input_sha256"], rows[0]["dispatch_input_sha256"]
            )
            by_label = {item["label"]: item for item in payload["variants"]}
            for row in rows[1:]:
                variant = by_label[row["label"]]
                self.assertAlmostEqual(float(row["npv_eur"]), variant["npv_eur"])
                self.assertAlmostEqual(float(row["market_value_eur"]), variant["market_value_eur"])
                self.assertEqual(row["analysis_input_sha256"], variant["analysis_input_sha256"])
            self.assertLess(
                by_label["market_price_level*0.8"]["npv_eur"], payload["base"]["npv_eur"]
            )
            self.assertGreater(
                by_label["market_price_level*1.2"]["npv_eur"], payload["base"]["npv_eur"]
            )

    def test_cli_reports_the_shared_discount_rate_warning(self) -> None:
        payload = json.loads(self.scenario.read_text(encoding="utf-8"))
        payload["financial"]["discount_rate_fraction"] = 8
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            scenario_path = directory_path / "scenario.json"
            scenario_path.write_text(json.dumps(payload), encoding="utf-8")
            (directory_path / "hourly.csv").write_text(
                self.scenario.with_name("hourly.csv").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            output = directory_path / "sensitivity"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
                        "sensitivity",
                        "--scenario",
                        str(scenario_path),
                        "--spec",
                        str(self.spec),
                        "--output",
                        str(output),
                        "--time-limit",
                        "10",
                    ]
                )
            table = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertIn("warning: discount_rate_fraction", stdout.getvalue())
        self.assertIn("800%", stdout.getvalue())
        self.assertEqual(len(table["warnings"]), 1)
        self.assertIn("800%", table["warnings"][0])

    def test_cli_enforces_the_overwrite_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "parameters": {"market_price_level": {"multipliers": [1.1]}},
                    }
                ),
                encoding="utf-8",
            )
            output = Path(directory) / "sensitivity"
            arguments = [
                "sensitivity",
                "--scenario",
                str(self.scenario),
                "--spec",
                str(spec_path),
                "--output",
                str(output),
                "--time-limit",
                "10",
            ]
            with redirect_stdout(StringIO()):
                self.assertEqual(main(arguments), 0)
            with self.assertRaisesRegex(SystemExit, "refusing to overwrite"):
                main(arguments)
            with redirect_stdout(StringIO()):
                self.assertEqual(main([*arguments, "--force"]), 0)

    def test_cli_reports_spec_errors_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "parameters": {"discount_rate_fraction": {"values": [0.1]}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "supported parameters"):
                main(
                    [
                        "sensitivity",
                        "--scenario",
                        str(self.scenario),
                        "--spec",
                        str(spec_path),
                        "--output",
                        str(Path(directory) / "sensitivity"),
                    ]
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
