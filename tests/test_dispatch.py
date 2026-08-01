from __future__ import annotations

import random
import unittest

from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.models import BatteryConfig, GridConfig
from tests.helpers import make_scenario


class DispatchTests(unittest.TestCase):
    def test_flat_price_exports_pv_directly(self) -> None:
        result = optimize_dispatch(make_scenario([500, 600], [50, 50]))
        self.assertEqual([row.pv_export_kw for row in result.intervals], [500, 600])
        self.assertTrue(all(row.pv_charge_kw == 0 for row in result.intervals))
        self.assertTrue(all(row.battery_export_kw == 0 for row in result.intervals))
        self.assertEqual(result.summary.curtailed_energy_mwh, 0)

    def test_curtailment_is_shifted_with_asymmetric_efficiencies(self) -> None:
        battery = BatteryConfig(
            2_000,
            1_000,
            1_000,
            0,
            1,
            0.5,
            0.5,
            0.8,
            0.9,
            0,
        )
        result = optimize_dispatch(make_scenario([2_000, 0], [1, 100], battery=battery))
        self.assertAlmostEqual(result.intervals[0].pv_charge_kw, 1_000, places=6)
        self.assertAlmostEqual(result.intervals[1].battery_export_kw, 720, places=6)
        self.assertAlmostEqual(result.summary.ending_soc_kwh, 1_000, places=6)
        self.assertAlmostEqual(result.summary.curtailment_reduction_fraction or 0, 1.0)

    def test_refinement_cannot_trade_profit_for_curtailment(self) -> None:
        battery = BatteryConfig(1_000, 1_000, 1_000, 0, 1, 0, 0, 1, 1, 0.0005)
        result = optimize_dispatch(make_scenario([2_000, 0], [0, 0], battery=battery))
        self.assertTrue(all(row.pv_charge_kw == 0 for row in result.intervals))
        self.assertTrue(all(row.battery_export_kw == 0 for row in result.intervals))
        self.assertAlmostEqual(result.summary.incremental_operating_value_eur, 0)

    def test_grid_arbitrage_respects_feature_flag(self) -> None:
        battery = BatteryConfig(1_000, 1_000, 1_000, 0, 1, 0, 0, 1, 1, 0)
        disabled = optimize_dispatch(
            make_scenario(
                [0, 0],
                [10, 100],
                battery=battery,
                grid=GridConfig(export_limit_kw=1_000, import_limit_kw=1_000),
            )
        )
        self.assertEqual(disabled.summary.grid_charge_energy_mwh, 0)
        self.assertEqual(disabled.summary.battery_discharge_energy_mwh, 0)

        enabled = optimize_dispatch(
            make_scenario(
                [0, 0],
                [10, 100],
                battery=battery,
                grid=GridConfig(1_000, 1_000, True),
            )
        )
        self.assertAlmostEqual(enabled.intervals[0].grid_charge_kw, 1_000, places=5)
        self.assertAlmostEqual(enabled.intervals[1].battery_export_kw, 1_000, places=5)
        self.assertAlmostEqual(enabled.summary.operating_value_eur, 90)

    def test_terminal_soc_prevents_free_initial_energy(self) -> None:
        result = optimize_dispatch(make_scenario([0, 0], [100, 200]))
        self.assertTrue(all(row.battery_export_kw == 0 for row in result.intervals))
        self.assertEqual(result.summary.ending_soc_kwh, 1_000)

    def test_negative_price_pv_can_be_curtailed(self) -> None:
        result = optimize_dispatch(make_scenario([500, 500], [-20, -10]))
        self.assertTrue(all(row.pv_export_kw == 0 for row in result.intervals))
        self.assertAlmostEqual(result.summary.curtailed_energy_mwh, 1.0)

    def test_half_hour_soc_accounting(self) -> None:
        result = optimize_dispatch(make_scenario([2_000, 0], [0, 100], interval_hours=0.5))
        self.assertAlmostEqual(result.intervals[0].soc_end_kwh, 1_500)
        self.assertAlmostEqual(result.intervals[1].soc_end_kwh, 1_000)

    def test_infeasible_terminal_target_fails_explicitly(self) -> None:
        battery = BatteryConfig(1_000, 500, 500, 0, 1, 0.5, 0.9, 1, 1, 0)
        with self.assertRaises(DispatchOptimizationError):
            optimize_dispatch(make_scenario([0, 0], [10, 100], battery=battery))

    def test_seeded_scenarios_hold_physical_invariants(self) -> None:
        rng = random.Random(730_2026)
        for _ in range(8):
            pv = [rng.uniform(0, 2_000) for _ in range(6)]
            prices = [rng.uniform(-20, 180) for _ in range(6)]
            result = optimize_dispatch(make_scenario(pv, prices))
            for row in result.intervals:
                self.assertAlmostEqual(
                    row.pv_export_kw + row.pv_charge_kw + row.curtailed_pv_kw,
                    row.pv_power_kw,
                    places=5,
                )
                self.assertLessEqual(row.grid_export_kw, 1_000 + 1e-6)
                self.assertFalse(row.pv_charge_kw > 1e-6 and row.battery_export_kw > 1e-6)
                self.assertGreaterEqual(row.soc_end_kwh, -1e-6)
                self.assertLessEqual(row.soc_end_kwh, 2_000 + 1e-6)
            self.assertAlmostEqual(result.summary.ending_soc_kwh, 1_000, places=5)

    def test_invalid_solver_options_are_rejected(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        for value in (0, float("nan")):
            with self.subTest(time_limit_seconds=value), self.assertRaises(ValueError):
                optimize_dispatch(scenario, time_limit_seconds=value)
        for value in (1, float("nan")):
            with self.subTest(relative_mip_gap=value), self.assertRaises(ValueError):
                optimize_dispatch(scenario, relative_mip_gap=value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
