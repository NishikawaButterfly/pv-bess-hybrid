from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pv_bess.dispatch as dispatch_module
from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.models import BatteryConfig, GridConfig, IntervalDispatch, Scenario
from tests.helpers import make_scenario


class DispatchSafetyTests(unittest.TestCase):
    def assert_invalid(
        self,
        scenario: Scenario,
        intervals: tuple[IntervalDispatch, ...],
        message: str,
    ) -> None:
        with self.assertRaisesRegex(DispatchOptimizationError, message):
            dispatch_module._validate_solution(scenario, intervals)

    def test_corrupted_interval_results_are_rejected_by_safety_invariants(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        rows = optimize_dispatch(scenario).intervals
        wider_grid = replace(scenario, grid=GridConfig(2_000))
        bidirectional_grid = replace(scenario, grid=GridConfig(1_000, 1_000, True))
        larger_charger = replace(
            scenario,
            battery=BatteryConfig(2_000, 2_000, 1_000, 0, 1, 0.5, 0.5, 1, 1, 1),
        )
        different_terminal = replace(
            scenario,
            battery=replace(scenario.battery, terminal_soc_fraction=0.6),
        )
        cases = (
            (
                "non-finite value",
                scenario,
                (replace(rows[0], pv_export_kw=float("nan")), rows[1]),
                "non-finite value",
            ),
            (
                "negative flow",
                scenario,
                (replace(rows[0], pv_export_kw=-1), rows[1]),
                "negative flow",
            ),
            (
                "SOC discontinuity",
                scenario,
                (rows[0], replace(rows[1], soc_start_kwh=1_001)),
                "not continuous",
            ),
            (
                "PV conservation",
                scenario,
                (replace(rows[0], pv_power_kw=1), rows[1]),
                "PV allocation",
            ),
            (
                "export limit",
                scenario,
                (replace(rows[0], battery_export_kw=1_001), rows[1]),
                "grid export limit",
            ),
            (
                "import limit",
                scenario,
                (replace(rows[0], grid_charge_kw=1), rows[1]),
                "grid import limit",
            ),
            (
                "charge power",
                scenario,
                (
                    replace(rows[0], pv_power_kw=1_001, pv_charge_kw=1_001),
                    rows[1],
                ),
                "battery charge power",
            ),
            (
                "discharge power",
                wider_grid,
                (replace(rows[0], battery_export_kw=1_001), rows[1]),
                "battery discharge power",
            ),
            (
                "simultaneous battery directions",
                scenario,
                (
                    replace(
                        rows[0],
                        pv_power_kw=1,
                        pv_charge_kw=1,
                        battery_export_kw=1,
                    ),
                    rows[1],
                ),
                "charges and discharges",
            ),
            (
                "simultaneous grid directions",
                bidirectional_grid,
                (
                    replace(
                        rows[0],
                        pv_power_kw=1,
                        pv_export_kw=1,
                        grid_charge_kw=1,
                    ),
                    rows[1],
                ),
                "import and export",
            ),
            (
                "SOC transition",
                scenario,
                (replace(rows[0], soc_end_kwh=1_001), rows[1]),
                "SOC transition",
            ),
            (
                "SOC operating window",
                larger_charger,
                (
                    replace(
                        rows[0],
                        pv_power_kw=1_001,
                        pv_charge_kw=1_001,
                        soc_end_kwh=2_001,
                    ),
                    rows[1],
                ),
                "operating window",
            ),
            (
                "terminal target",
                different_terminal,
                rows,
                "terminal SOC target",
            ),
        )
        for name, case_scenario, case_rows, message in cases:
            with self.subTest(name=name):
                self.assert_invalid(case_scenario, case_rows, message)

    def test_global_energy_residual_is_rejected(self) -> None:
        scenario = make_scenario([1, 0], [0, 0])
        rows = optimize_dispatch(scenario).intervals
        corrupted = (
            replace(
                rows[0],
                interval_hours=0.5,
                pv_export_kw=0,
                pv_charge_kw=1,
                soc_end_kwh=1_000.5,
            ),
            replace(
                rows[1],
                battery_export_kw=0.5,
                soc_start_kwh=1_000.5,
                soc_end_kwh=1_000,
            ),
        )
        self.assert_invalid(scenario, corrupted, "global energy conservation")

    def test_primary_and_refinement_solver_failures_are_explicit(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        failure = SimpleNamespace(
            success=False,
            x=None,
            status=1,
            message="synthetic solver failure",
        )
        with (
            patch.object(dispatch_module, "milp", return_value=failure),
            self.assertRaisesRegex(DispatchOptimizationError, "status 1"),
        ):
            optimize_dispatch(scenario)

        real_milp = dispatch_module.milp
        call_count = 0

        def fail_second_phase(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return real_milp(*args, **kwargs)
            return failure

        with (
            patch.object(dispatch_module, "milp", side_effect=fail_second_phase),
            self.assertRaisesRegex(DispatchOptimizationError, "refinement failed"),
        ):
            optimize_dispatch(scenario)

    def test_refinement_cannot_change_the_economic_solution(self) -> None:
        scenario = make_scenario([500, 0], [50, 100])
        real_milp = dispatch_module.milp
        call_count = 0

        def corrupt_second_phase(*args: object, **kwargs: object) -> object:
            nonlocal call_count
            call_count += 1
            result = real_milp(*args, **kwargs)
            if call_count == 2:
                result.x = result.x.copy()
                result.x[0] += 1
            return result

        with (
            patch.object(dispatch_module, "milp", side_effect=corrupt_second_phase),
            self.assertRaisesRegex(DispatchOptimizationError, "economic optimum"),
        ):
            optimize_dispatch(scenario)

    def test_missing_backend_and_gap_metadata_remain_explicit(self) -> None:
        with patch.object(
            dispatch_module.importlib,
            "import_module",
            side_effect=ImportError,
        ):
            self.assertIsNone(dispatch_module._highs_backend_version())
        with patch.object(
            dispatch_module.importlib,
            "import_module",
            return_value=SimpleNamespace(),
        ):
            self.assertIsNone(dispatch_module._highs_backend_version())

        scenario = make_scenario([0, 0], [0, 0])
        real_milp = dispatch_module.milp

        def solve_without_gap(*args: object, **kwargs: object) -> object:
            result = real_milp(*args, **kwargs)
            result.mip_gap = None
            return result

        with patch.object(dispatch_module, "milp", side_effect=solve_without_gap):
            result = optimize_dispatch(scenario)
        self.assertIsNone(result.economic_phase.achieved_relative_mip_gap)
        self.assertIsNone(result.refinement_phase.achieved_relative_mip_gap)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
