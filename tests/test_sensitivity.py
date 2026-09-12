from __future__ import annotations

import csv
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any
from unittest import mock

from pv_bess.cli import main
from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.finance import evaluate_financials, financial_precondition_errors
from pv_bess.io import load_scenario, load_sensitivity_spec, write_results
from pv_bess.models import BatteryConfig, FinancialAssumptions, GridConfig
from pv_bess.sensitivity import (
    MAX_TOTAL_RUNS,
    SensitivitySpec,
    SensitivitySpecError,
    SensitivityVariant,
    apply_variant,
    parse_sensitivity_spec,
    run_sensitivity,
    variant_assumptions,
)
from tests.helpers import make_scenario


def _spec(parameters: dict[str, Any]) -> SensitivitySpec:
    return parse_sensitivity_spec({"schema_version": "1.0", "parameters": parameters})


class SensitivitySpecTests(unittest.TestCase):
    def test_unknown_parameter_is_rejected_with_the_supported_list(self) -> None:
        expected = (
            "unknown sensitivity parameter 'project_life_years'; supported parameters: "
            "capex_eur, charge_efficiency, degradation_cost_eur_per_mwh_dc_discharged, "
            "discharge_efficiency, discount_rate_fraction, energy_capacity_kwh, "
            "market_price_level, power_kw"
        )
        with self.assertRaises(SensitivitySpecError) as raised:
            _spec({"project_life_years": {"values": [10]}})
        self.assertEqual(str(raised.exception), expected)

    def test_specs_beyond_the_run_cap_are_rejected(self) -> None:
        values = [float(index) for index in range(1, MAX_TOTAL_RUNS + 1)]
        with self.assertRaisesRegex(
            SensitivitySpecError,
            rf"requests {MAX_TOTAL_RUNS + 1} runs .* at most {MAX_TOTAL_RUNS} runs",
        ):
            _spec({"energy_capacity_kwh": {"values": values, "capex_eur_per_kwh": 100}})

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
        self.assertEqual(len(spec.variants), 10)
        self.assertEqual(spec.variants[0].label, "market_price_level*0.8")
        self.assertEqual(spec.variants[-1].label, "discount_rate_fraction=0.1")
        capacity = [item for item in spec.variants if item.parameter == "energy_capacity_kwh"]
        self.assertEqual([item.capex_eur_per_kwh for item in capacity], [250, 250])


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
            self.scenario,
            SensitivityVariant("energy_capacity_kwh", "absolute", 1_500, capex_eur_per_kwh=200),
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

    def test_financial_preconditions_refuse_before_any_solve(self) -> None:
        scenario = replace(
            self.scenario, battery=replace(self.scenario.battery, terminal_soc_fraction=0.25)
        )
        spec = _spec({"market_price_level": {"multipliers": [1.2]}})
        with (
            mock.patch("pv_bess.sensitivity.optimize_dispatch", wraps=optimize_dispatch) as solver,
            self.assertRaisesRegex(ValueError, "terminal SOC to equal initial SOC"),
        ):
            run_sensitivity(scenario, self.assumptions, spec)
        self.assertEqual(solver.call_count, 0)

    def test_variant_scaled_preconditions_refuse_before_any_solve(self) -> None:
        """A capacity variant rescales the SOC endpoints in kWh, so a base
        inside the equality tolerance can leave it once resized."""

        battery = replace(
            self.scenario.battery,
            energy_capacity_kwh=4_000_000,
            terminal_soc_fraction=0.5 + 1e-16,
            initial_soc_fraction=0.5,
        )
        scenario = replace(self.scenario, battery=battery)
        assumptions = self.assumptions
        self.assertEqual(financial_precondition_errors(scenario, assumptions), ())
        spec = _spec({"energy_capacity_kwh": {"multipliers": [4], "capex_eur_per_kwh": 250}})
        with (
            mock.patch("pv_bess.sensitivity.optimize_dispatch", wraps=optimize_dispatch) as solver,
            self.assertRaisesRegex(
                ValueError, r"variant 'energy_capacity_kwh\*4': financial evaluation requires"
            ),
        ):
            run_sensitivity(scenario, assumptions, spec)
        self.assertEqual(solver.call_count, 0)

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

    def test_shared_opex_escalation_warning_is_carried_once_for_the_whole_table(self) -> None:
        spec = _spec({"market_price_level": {"multipliers": [0.8, 1.2]}})
        mistyped = replace(self.assumptions, annual_opex_escalation_fraction=1.0)
        result = run_sensitivity(self.scenario, mistyped, spec)
        # One entry for the table, not one per run: every row shares the escalation.
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("annual_opex_escalation_fraction", result.warnings[0])
        self.assertIn("100%", result.warnings[0])
        self.assertEqual(len(result.variants), 2)


class SensitivityFinancialAndCostTests(unittest.TestCase):
    """The financial axes and the declared cost co-variation of capacity variants.

    The fixture battery is capacity-limited (power and export headroom both
    exceed what one interval can store), so a larger battery strictly increases
    market value and the cost co-variation is what decides whether it pays.
    """

    def setUp(self) -> None:
        self.scenario = make_scenario(
            [2_000, 0],
            [10, 100],
            battery=BatteryConfig(
                energy_capacity_kwh=1_000,
                max_charge_power_kw=2_000,
                max_discharge_power_kw=2_000,
                minimum_soc_fraction=0,
                maximum_soc_fraction=1,
                initial_soc_fraction=0,
                terminal_soc_fraction=0,
                charge_efficiency=1,
                discharge_efficiency=1,
                degradation_cost_eur_per_mwh_dc_discharged=1,
            ),
            grid=GridConfig(export_limit_kw=5_000),
        )
        self.assumptions = FinancialAssumptions(
            capex_eur=1_000,
            annual_fixed_opex_eur=10,
            project_life_years=5,
            discount_rate_fraction=0.08,
            annualization_factor=365,
        )

    def test_capacity_variant_without_cost_is_refused_naming_the_field(self) -> None:
        for build in (
            lambda: _spec({"energy_capacity_kwh": {"multipliers": [1.5]}}),
            lambda: SensitivityVariant("energy_capacity_kwh", "multiplier", 1.5),
        ):
            with self.assertRaises(SensitivitySpecError) as raised:
                build()
            message = str(raised.exception)
            self.assertIn("capex_eur_per_kwh", message)
            self.assertIn("same capital cost", message)

    def test_cost_declared_on_a_non_capacity_parameter_is_refused(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "applies only to energy_capacity_kwh"):
            _spec({"power_kw": {"multipliers": [1.5], "capex_eur_per_kwh": 100}})

    def test_capacity_sweep_co_varies_capex(self) -> None:
        spec = _spec({"energy_capacity_kwh": {"multipliers": [2.0], "capex_eur_per_kwh": 400}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        (doubled,) = result.variants
        self.assertEqual(result.base.capex_eur, 1_000)
        self.assertEqual(doubled.capex_eur, 1_000 + 1_000 * 400)
        # The larger battery moves more energy, yet its co-varied CAPEX makes
        # it the worse investment: under the old fixed-cost behaviour the same
        # variant had a higher NPV than the base, never a lower one.
        self.assertGreater(doubled.market_value_eur, result.base.market_value_eur)
        self.assertLess(doubled.npv_eur, result.base.npv_eur)
        self.assertNotEqual(doubled.dispatch_input_sha256, result.base.dispatch_input_sha256)
        self.assertNotEqual(doubled.analysis_input_sha256, result.base.analysis_input_sha256)

    def test_capacity_shrink_below_zero_capex_shows_the_arithmetic(self) -> None:
        spec = _spec({"energy_capacity_kwh": {"values": [100], "capex_eur_per_kwh": 400}})
        with (
            mock.patch("pv_bess.sensitivity.optimize_dispatch", wraps=optimize_dispatch) as solver,
            self.assertRaises(SensitivitySpecError) as raised,
        ):
            run_sensitivity(self.scenario, self.assumptions, spec)
        message = str(raised.exception)
        # Every number the user typed is positive; only the derived CAPEX is
        # not, so the refusal must show how it was computed.
        self.assertIn("derives capex_eur = 1000 + (100 - 1000) * 400 = -359000", message)
        self.assertEqual(solver.call_count, 0)

    def test_capex_axis_scans(self) -> None:
        spec = _spec({"capex_eur": {"multipliers": [0.5, 1.5]}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        cheaper, dearer = result.variants
        self.assertEqual(cheaper.capex_eur, 500)
        self.assertEqual(dearer.capex_eur, 1_500)
        self.assertGreater(cheaper.npv_eur, result.base.npv_eur)
        self.assertGreater(result.base.npv_eur, dearer.npv_eur)
        self.assertEqual(cheaper.market_value_eur, result.base.market_value_eur)
        self.assertEqual(dearer.market_value_eur, result.base.market_value_eur)

    def test_discount_rate_axis_scans(self) -> None:
        spec = _spec({"discount_rate_fraction": {"values": [0.02, 0.3]}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        patient, hurried = result.variants
        # The fixture's operating cash flows are positive, so NPV falls as the
        # rate rises; the base sits between the two scanned rates.
        self.assertGreater(patient.npv_eur, result.base.npv_eur)
        self.assertGreater(result.base.npv_eur, hurried.npv_eur)
        self.assertEqual(patient.capex_eur, 1_000)
        self.assertEqual(hurried.capex_eur, 1_000)

    def test_financial_only_variant_reuses_the_base_dispatch(self) -> None:
        spec = _spec(
            {
                "capex_eur": {"multipliers": [1.5]},
                "discount_rate_fraction": {"values": [0.12]},
            }
        )
        with mock.patch("pv_bess.sensitivity.optimize_dispatch", wraps=optimize_dispatch) as solver:
            result = run_sensitivity(self.scenario, self.assumptions, spec)
        self.assertEqual(solver.call_count, 1)
        for variant in result.variants:
            self.assertEqual(variant.dispatch_input_sha256, result.base.dispatch_input_sha256)
            self.assertEqual(variant.market_value_eur, result.base.market_value_eur)
            self.assertNotEqual(variant.analysis_input_sha256, result.base.analysis_input_sha256)
            self.assertNotEqual(variant.npv_eur, result.base.npv_eur)

    def test_scanned_rate_above_threshold_carries_the_warning_on_that_variant(self) -> None:
        spec = _spec({"discount_rate_fraction": {"values": [1.5]}})
        result = run_sensitivity(self.scenario, self.assumptions, spec)
        self.assertEqual(result.warnings, ())
        self.assertEqual(result.base.warnings, ())
        (scanned,) = result.variants
        self.assertEqual(len(scanned.warnings), 1)
        self.assertIn("discount_rate_fraction", scanned.warnings[0])
        self.assertIn("150%", scanned.warnings[0])


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
            self.assertEqual(payload["run_count"], 11)
            self.assertEqual(len(rows), 11)
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
            base_dispatch_sha = payload["base"]["dispatch_input_sha256"]
            for label in ("capex_eur*0.8", "capex_eur*1.2", "discount_rate_fraction=0.06"):
                self.assertEqual(by_label[label]["dispatch_input_sha256"], base_dispatch_sha)
            self.assertNotEqual(
                by_label["energy_capacity_kwh*1.5"]["capex_eur"],
                payload["base"]["capex_eur"],
            )

    def test_old_style_spec_gains_only_additive_fields(self) -> None:
        """A spec with no capacity variants and no financial axes keeps every
        pre-existing field and value shape; the new per-row fields are appended."""

        old_row_fields = [
            "label",
            "parameter",
            "mode",
            "value",
            "dispatch_input_sha256",
            "analysis_input_sha256",
            "market_value_eur",
            "npv_eur",
            "irr_fraction",
            "simple_payback_years",
            "discounted_payback_years",
            "lcos_eur_per_mwh",
        ]
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "parameters": {
                            "market_price_level": {"multipliers": [1.2]},
                            "degradation_cost_eur_per_mwh_dc_discharged": {"values": [0]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = Path(directory) / "sensitivity"
            with redirect_stdout(StringIO()):
                status = main(
                    [
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
                )
            self.assertEqual(status, 0)
            payload = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
            with (output / "sensitivity.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                fieldnames = list(reader.fieldnames or [])
                rows = list(reader)
        self.assertEqual(fieldnames, [*old_row_fields, "capex_eur", "warnings"])
        for row in (payload["base"], *payload["variants"]):
            self.assertEqual(sorted(row), sorted([*old_row_fields, "capex_eur", "warnings"]))
            self.assertEqual(row["capex_eur"], 5_000_000)
            self.assertEqual(row["warnings"], [])
        for row in rows:
            self.assertEqual(row["capex_eur"], "5000000.0")
            self.assertEqual(row["warnings"], "")

    def test_cli_prints_a_variant_warning_with_its_label(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "parameters": {"discount_rate_fraction": {"values": [8]}},
                    }
                ),
                encoding="utf-8",
            )
            output = Path(directory) / "sensitivity"
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(
                    [
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
                )
            payload = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
        self.assertEqual(status, 0)
        self.assertIn("warning: discount_rate_fraction=8:", stdout.getvalue())
        self.assertIn("800%", stdout.getvalue())
        # The base assumptions are clean, so the table-level warnings stay
        # empty and the scanned rate's warning lives on its own row.
        self.assertEqual(payload["warnings"], [])
        (scanned,) = [
            item for item in payload["variants"] if item["label"] == "discount_rate_fraction=8"
        ]
        self.assertEqual(len(scanned["warnings"]), 1)
        self.assertIn("800%", scanned["warnings"][0])

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

    def test_cli_reports_the_shared_opex_escalation_warning(self) -> None:
        payload = json.loads(self.scenario.read_text(encoding="utf-8"))
        payload["financial"]["annual_opex_escalation_fraction"] = 1
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
        self.assertIn("warning: annual_opex_escalation_fraction", stdout.getvalue())
        self.assertIn("100%", stdout.getvalue())
        self.assertEqual(len(table["warnings"]), 1)
        self.assertIn("100%", table["warnings"][0])

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
                        "parameters": {"annual_fixed_opex_eur": {"values": [50_000]}},
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


_DEFAULT_TABLE_COLUMNS = [
    "label",
    "parameter",
    "mode",
    "value",
    "dispatch_input_sha256",
    "analysis_input_sha256",
    "market_value_eur",
    "npv_eur",
    "irr_fraction",
    "simple_payback_years",
    "discounted_payback_years",
    "lcos_eur_per_mwh",
    "capex_eur",
    "warnings",
]


class SensitivityScheduleRetentionTests(unittest.TestCase):
    """--retain-schedules keeps, for every row, the schedule its numbers came from."""

    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.scenario = root / "sample-data" / "scenario.json"
        self.bundled_spec = root / "sample-data" / "sensitivity-spec.json"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.work = Path(directory.name)

    def _spec_file(self, name: str, parameters: dict[str, Any]) -> Path:
        path = self.work / f"{name}.json"
        path.write_text(
            json.dumps({"schema_version": "1.0", "parameters": parameters}), encoding="utf-8"
        )
        return path

    def _arguments(self, spec: Path, output: Path, *extra: str) -> list[str]:
        return [
            "sensitivity",
            "--scenario",
            str(self.scenario),
            "--spec",
            str(spec),
            "--output",
            str(output),
            "--time-limit",
            "10",
            *extra,
        ]

    def _sensitivity(self, spec: Path, output: Path, *extra: str) -> str:
        """Run the command and return its stdout; any exit fails the test instead."""

        stdout = StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                status = main(self._arguments(spec, output, *extra))
        except SystemExit as exc:
            self.fail(f"pv-bess sensitivity exited: {exc}")
        self.assertEqual(status, 0)
        return stdout.getvalue()

    @staticmethod
    def _rows(output: Path) -> list[dict[str, Any]]:
        table = json.loads((output / "sensitivity.json").read_text(encoding="utf-8"))
        return [table["base"], *table["variants"]]

    @staticmethod
    def _csv_rows(path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    @staticmethod
    def _snapshot(output: Path) -> dict[str, bytes | None]:
        """Every entry under ``output``, hidden ones included; None marks a directory."""

        return {
            path.relative_to(output).as_posix(): None if path.is_dir() else path.read_bytes()
            for path in sorted(output.rglob("*"))
        }

    def test_retained_schedule_matches_a_standalone_run_of_that_variant(self) -> None:
        spec = self._spec_file(
            "capacity", {"energy_capacity_kwh": {"multipliers": [1.5], "capex_eur_per_kwh": 250}}
        )
        output = self.work / "sensitivity"
        self._sensitivity(spec, output, "--retain-schedules")
        (row,) = [item for item in self._rows(output) if item["label"] == "energy_capacity_kwh*1.5"]

        # The same variant written by hand as a scenario file: 20,000 kWh x 1.5,
        # and 5,000,000 EUR plus 10,000 kWh at the declared 250 EUR/kWh.
        standalone = self.work / "standalone"
        standalone.mkdir()
        payload = json.loads(self.scenario.read_text(encoding="utf-8"))
        payload["battery"]["energy_capacity_kwh"] = 30_000
        payload["financial"]["capex_eur"] = 7_500_000
        (standalone / "scenario.json").write_text(json.dumps(payload), encoding="utf-8")
        (standalone / "hourly.csv").write_bytes(self.scenario.with_name("hourly.csv").read_bytes())
        with redirect_stdout(StringIO()):
            status = main(
                [
                    "run",
                    "--scenario",
                    str(standalone / "scenario.json"),
                    "--output",
                    str(standalone / "run"),
                    "--time-limit",
                    "10",
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(
            (output / row["schedule_file"]).read_bytes(),
            (standalone / "run" / "dispatch.csv").read_bytes(),
        )

    def test_every_schedule_is_the_run_its_row_describes(self) -> None:
        spec_path = self._spec_file(
            "mixed",
            {
                "market_price_level": {"multipliers": [1.2]},
                "energy_capacity_kwh": {"multipliers": [1.5], "capex_eur_per_kwh": 250},
                "capex_eur": {"multipliers": [0.8]},
                "discount_rate_fraction": {"values": [0.1]},
            },
        )
        output = self.work / "sensitivity"
        self._sensitivity(spec_path, output, "--retain-schedules")
        rows = {row["label"]: row for row in self._rows(output)}

        scenario, assumptions = load_scenario(self.scenario)
        runs = [("base", scenario, assumptions)]
        runs.extend(
            (
                variant.label,
                apply_variant(scenario, variant),
                variant_assumptions(scenario, assumptions, variant),
            )
            for variant in load_sensitivity_spec(spec_path).variants
        )
        self.assertEqual(sorted(label for label, _, _ in runs), sorted(rows))
        for index, (label, run_scenario, run_assumptions) in enumerate(runs):
            with self.subTest(row=label):
                dispatch = optimize_dispatch(run_scenario)
                financial = evaluate_financials(dispatch, run_scenario, run_assumptions)
                # What `pv-bess run` writes for this scenario and these assumptions.
                run_output = self.work / "standalone" / str(index)
                write_results(run_output, dispatch, financial)
                self.assertEqual(
                    (output / rows[label]["schedule_file"]).read_bytes(),
                    (run_output / "dispatch.csv").read_bytes(),
                )

    def test_financial_only_variants_keep_their_own_file_over_the_base_dispatch(self) -> None:
        spec = self._spec_file(
            "financial",
            {"capex_eur": {"multipliers": [0.8]}, "discount_rate_fraction": {"values": [0.1]}},
        )
        output = self.work / "sensitivity"
        self._sensitivity(spec, output, "--retain-schedules")
        base, *variants = self._rows(output)
        base_schedule = self._csv_rows(output / base["schedule_file"])
        self.assertEqual(len(variants), 2)
        for row in variants:
            with self.subTest(row=row["label"]):
                self.assertEqual(row["dispatch_input_sha256"], base["dispatch_input_sha256"])
                self.assertNotEqual(row["schedule_file"], base["schedule_file"])
                schedule = self._csv_rows(output / row["schedule_file"])
                self.assertEqual(len(schedule), len(base_schedule))
                for own, shared in zip(schedule, base_schedule, strict=True):
                    self.assertEqual(own["dispatch_input_sha256"], base["dispatch_input_sha256"])
                    self.assertEqual(own["analysis_input_sha256"], row["analysis_input_sha256"])
                    self.assertNotEqual(own["analysis_input_sha256"], base["analysis_input_sha256"])
                    own_rest = {k: v for k, v in own.items() if k != "analysis_input_sha256"}
                    shared_rest = {k: v for k, v in shared.items() if k != "analysis_input_sha256"}
                    self.assertEqual(own_rest, shared_rest)

    def test_rows_with_the_same_analysis_hash_share_one_file(self) -> None:
        spec = self._spec_file("repeat", {"capex_eur": {"multipliers": [1, 1.2]}})
        output = self.work / "sensitivity"
        self._sensitivity(spec, output, "--retain-schedules")
        rows = {row["label"]: row for row in self._rows(output)}
        base, same, other = rows["base"], rows["capex_eur*1"], rows["capex_eur*1.2"]
        self.assertEqual(same["analysis_input_sha256"], base["analysis_input_sha256"])
        self.assertEqual(same["schedule_file"], base["schedule_file"])
        self.assertNotEqual(other["schedule_file"], base["schedule_file"])
        files = sorted((output / "schedules").iterdir())
        self.assertEqual(len(files), 2)
        # No two files carry the same bytes: one file per distinct run.
        self.assertEqual(len({path.read_bytes() for path in files}), len(files))

    def test_every_row_schedule_file_exists_and_is_relative(self) -> None:
        output = self.work / "sensitivity"
        self._sensitivity(self.bundled_spec, output, "--retain-schedules")
        rows = self._rows(output)
        flat_rows = self._csv_rows(output / "sensitivity.csv")
        self.assertEqual(len(flat_rows), len(rows))
        for row, flat in zip(rows, flat_rows, strict=True):
            with self.subTest(row=row["label"]):
                relative = row["schedule_file"]
                self.assertEqual(relative, f"schedules/{row['analysis_input_sha256']}.csv")
                self.assertFalse(Path(relative).is_absolute())
                self.assertTrue((output / relative).is_file())
                self.assertEqual(flat["label"], row["label"])
                self.assertEqual(flat["schedule_file"], relative)
        with (output / "sensitivity.csv").open(encoding="utf-8", newline="") as handle:
            header = next(csv.reader(handle))
        self.assertEqual(header, [*_DEFAULT_TABLE_COLUMNS, "schedule_file"])

    def test_schedule_filenames_are_bare_analysis_hashes(self) -> None:
        output = self.work / "sensitivity"
        self._sensitivity(self.bundled_spec, output, "--retain-schedules")
        names = sorted(path.name for path in (output / "schedules").iterdir())
        # 64 lowercase hexadecimal characters and ".csv": nothing from a label,
        # so no "*" (forbidden on Windows), "=", or path separator can appear.
        for name in names:
            self.assertRegex(name, r"\A[0-9a-f]{64}\.csv\Z")
        self.assertEqual(
            {name.removesuffix(".csv") for name in names},
            {row["analysis_input_sha256"] for row in self._rows(output)},
        )

    def test_default_output_is_unchanged_without_the_flag(self) -> None:
        spec = self._spec_file(
            "mixed",
            {"market_price_level": {"multipliers": [1.2]}, "capex_eur": {"multipliers": [0.8]}},
        )
        plain, retained = self.work / "plain", self.work / "retained"
        stdout = self._sensitivity(spec, plain)
        self._sensitivity(spec, retained, "--retain-schedules")

        self.assertFalse((plain / "schedules").exists())
        self.assertNotIn("schedules", stdout)
        plain_table = json.loads((plain / "sensitivity.json").read_text(encoding="utf-8"))
        retained_table = json.loads((retained / "sensitivity.json").read_text(encoding="utf-8"))
        for row in (plain_table["base"], *plain_table["variants"]):
            self.assertNotIn("schedule_file", row)
        for row in (retained_table["base"], *retained_table["variants"]):
            del row["schedule_file"]
        del plain_table["generated_at_utc"], retained_table["generated_at_utc"]
        # Retaining schedules adds a field and changes no number.
        self.assertEqual(retained_table, plain_table)

        plain_lines = (plain / "sensitivity.csv").read_text(encoding="utf-8").splitlines()
        retained_lines = (retained / "sensitivity.csv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(plain_lines[0].split(","), _DEFAULT_TABLE_COLUMNS)
        self.assertEqual([line.rsplit(",", 1)[0] for line in retained_lines], plain_lines)

    def test_existing_schedules_directory_is_refused_without_force(self) -> None:
        output = self.work / "sensitivity"
        (output / "schedules").mkdir(parents=True)
        (output / "schedules" / "keep.txt").write_text("prior", encoding="utf-8")
        spec = self._spec_file("price", {"market_price_level": {"multipliers": [1.2]}})
        with (
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
            self.assertRaisesRegex(
                SystemExit, r"refusing to overwrite schedules/; pass --force to replace them"
            ),
        ):
            main(self._arguments(spec, output, "--retain-schedules"))
        self.assertEqual((output / "schedules" / "keep.txt").read_text(encoding="utf-8"), "prior")
        self.assertEqual(sorted(path.name for path in output.iterdir()), ["schedules"])

    def test_a_failure_while_writing_schedules_publishes_nothing(self) -> None:
        import pv_bess.io as io_module

        original = io_module._stage_text
        schedules_written: list[str] = []

        def failing(path: Path, content: str) -> Path:
            if re.fullmatch(r"[0-9a-f]{64}\.csv", path.name):
                schedules_written.append(path.name)
                if len(schedules_written) == 2:
                    raise OSError("simulated failure while writing a schedule")
            return original(path, content)

        spec = self._spec_file("price", {"market_price_level": {"multipliers": [0.8, 1.2]}})
        output = self.work / "sensitivity"
        try:
            with (
                mock.patch("pv_bess.io._stage_text", side_effect=failing),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
                self.assertRaisesRegex(OSError, "simulated failure while writing a schedule"),
            ):
                main(self._arguments(spec, output, "--retain-schedules"))
        except SystemExit as exc:
            self.fail(f"pv-bess sensitivity exited: {exc}")
        self.assertEqual(len(schedules_written), 2)
        # Not the table, not a partial schedules/, not even an empty one.
        self.assertEqual(sorted(output.iterdir()) if output.exists() else [], [])

    def test_a_failure_mid_publication_with_force_leaves_the_previous_state_intact(
        self,
    ) -> None:
        output = self.work / "sensitivity"
        first = self._spec_file("first", {"market_price_level": {"multipliers": [1.2]}})
        second = self._spec_file(
            "second",
            {"market_price_level": {"multipliers": [0.8]}, "capex_eur": {"multipliers": [0.8]}},
        )
        self._sensitivity(first, output, "--retain-schedules")
        before = self._snapshot(output)
        self.assertIn("schedules", before)

        original_replace = Path.replace
        interrupted: list[Path] = []

        def replace_once_into_schedules(source: Path, target: Path) -> Path:
            # The new schedules/ is the last thing swapped in; fail exactly there,
            # after the new table has already taken the old table's place.
            if Path(target).name == "schedules" and not interrupted:
                interrupted.append(source)
                raise OSError("simulated failure while publishing schedules")
            return original_replace(source, target)

        try:
            with (
                mock.patch.object(
                    Path, "replace", autospec=True, side_effect=replace_once_into_schedules
                ),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
                self.assertRaisesRegex(OSError, "simulated failure while publishing schedules"),
            ):
                main(self._arguments(second, output, "--retain-schedules", "--force"))
        except SystemExit as exc:
            self.fail(f"pv-bess sensitivity exited: {exc}")
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(self._snapshot(output), before)

    def test_a_forced_run_without_the_flag_leaves_an_existing_schedules_directory_alone(
        self,
    ) -> None:
        output = self.work / "sensitivity"
        first = self._spec_file("first", {"market_price_level": {"multipliers": [1.2]}})
        second = self._spec_file("second", {"capex_eur": {"multipliers": [0.8]}})
        self._sensitivity(first, output, "--retain-schedules")
        schedules_before = {
            path.name: path.read_bytes() for path in (output / "schedules").iterdir()
        }
        self._sensitivity(second, output, "--force")
        self.assertEqual(
            {path.name: path.read_bytes() for path in (output / "schedules").iterdir()},
            schedules_before,
        )
        for row in self._rows(output):
            self.assertNotIn("schedule_file", row)

    def test_runs_that_share_an_analysis_hash_must_share_a_schedule(self) -> None:
        scenario, assumptions = load_scenario(self.scenario)
        # The bundled reserve is already 10 EUR/MWh, so this variant repeats the
        # base inputs exactly, is solved again, and must reproduce the base schedule.
        spec = _spec({"degradation_cost_eur_per_mwh_dc_discharged": {"values": [10]}})
        base = optimize_dispatch(scenario)
        first = base.intervals[0]
        diverging = replace(
            base,
            intervals=(replace(first, pv_export_kw=first.pv_export_kw + 1), *base.intervals[1:]),
        )
        with (
            mock.patch("pv_bess.sensitivity.optimize_dispatch", side_effect=[base, diverging]),
            self.assertRaisesRegex(DispatchOptimizationError, "same analysis inputs"),
        ):
            run_sensitivity(scenario, assumptions, spec, retain_schedules=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
