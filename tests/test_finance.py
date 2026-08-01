from __future__ import annotations

import math
import unittest

from pv_bess.dispatch import optimize_dispatch
from pv_bess.finance import evaluate_financials, internal_rate_of_return, net_present_value
from pv_bess.models import BatteryConfig, FinancialAssumptions
from tests.helpers import make_scenario


class FinanceTests(unittest.TestCase):
    def test_npv_matches_hand_calculation(self) -> None:
        cash_flows = [-100.0, 60.0, 60.0]
        expected = -100 + 60 / 1.1 + 60 / 1.1**2
        self.assertAlmostEqual(net_present_value(cash_flows, 0.10), expected, places=10)

    def test_irr_matches_quadratic_solution(self) -> None:
        expected = (60 + math.sqrt(27_600)) / 200 - 1
        actual = internal_rate_of_return([-100, 60, 60])
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual or 0, expected, places=9)

    def test_ambiguous_irr_is_not_reported(self) -> None:
        self.assertIsNone(internal_rate_of_return([-100, 230, -132]))

    def test_explicit_annualization_drives_cash_flows(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        dispatch = optimize_dispatch(scenario)
        assumptions = FinancialAssumptions(
            capex_eur=1_000,
            annual_fixed_opex_eur=100,
            project_life_years=2,
            discount_rate_fraction=0.10,
            annualization_factor=10,
        )
        result = evaluate_financials(dispatch, scenario, assumptions)
        expected_annual = dispatch.summary.incremental_operating_value_eur * 10 - 100
        self.assertEqual(result.cash_flows_eur, (-1_000, expected_annual, expected_annual))
        self.assertAlmostEqual(
            result.npv_eur,
            -1_000 + expected_annual / 1.1 + expected_annual / 1.1**2,
        )

    def test_mismatched_scenario_is_rejected(self) -> None:
        first = make_scenario([0, 0], [0, 0])
        second = make_scenario([1, 0], [0, 0])
        dispatch = optimize_dispatch(first)
        assumptions = FinancialAssumptions(0, 0, 1, 0)
        with self.assertRaisesRegex(ValueError, "does not match"):
            evaluate_financials(dispatch, second, assumptions)

    def test_analysis_hash_changes_with_financial_assumptions(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        dispatch = optimize_dispatch(scenario)
        first = evaluate_financials(dispatch, scenario, FinancialAssumptions(1_000, 0, 2, 0.08))
        second = evaluate_financials(dispatch, scenario, FinancialAssumptions(2_000, 0, 2, 0.08))
        self.assertNotEqual(first.analysis_input_sha256, second.analysis_input_sha256)
        self.assertEqual(len(first.analysis_input_sha256), 64)

    def test_finance_rejects_unvalued_terminal_inventory_change(self) -> None:
        battery = BatteryConfig(1_000, 1_000, 1_000, 0, 1, 0.5, 0, 1, 1, 0)
        scenario = make_scenario([0, 0], [10, 100], battery=battery)
        dispatch = optimize_dispatch(scenario)
        with self.assertRaisesRegex(ValueError, "terminal SOC"):
            evaluate_financials(dispatch, scenario, FinancialAssumptions(0, 0, 2, 0.08, 365))

    def test_irr_at_maximum_horizon_is_numerically_bounded(self) -> None:
        result = internal_rate_of_return([-100.0, *([1.0] * 100)])
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result or 0, -0.95)
        self.assertLessEqual(result or 0, 10)

    def test_npv_rejects_rate_outside_safe_domain(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[-0\.95, 10\]"):
            net_present_value([-100, 60, 60], -0.951)

    def test_financial_functions_reject_incomplete_or_nonfinite_series(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one cash flow"):
            net_present_value([], 0.08)
        with self.assertRaisesRegex(ValueError, "cash flows must be finite"):
            net_present_value([-100, float("nan")], 0.08)
        with self.assertRaisesRegex(ValueError, "at least two cash flows"):
            internal_rate_of_return([-100])
        with self.assertRaisesRegex(ValueError, "cash flows must be finite"):
            internal_rate_of_return([-100, float("inf")])

    def test_irr_search_is_bounded_and_expands_above_one_hundred_percent(self) -> None:
        self.assertAlmostEqual(internal_rate_of_return([-100, 250]) or 0, 1.5)
        self.assertIsNone(internal_rate_of_return([-1, 100]))

    def test_zero_capex_and_zero_discharge_have_explicit_outputs(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        result = evaluate_financials(
            optimize_dispatch(scenario),
            scenario,
            FinancialAssumptions(0, 0, 2, 0.08),
        )
        self.assertEqual(result.simple_payback_years, 0)
        self.assertEqual(result.discounted_payback_years, 0)
        self.assertIsNone(result.irr_fraction)
        self.assertIsNone(result.lcos_eur_per_mwh)

    def test_negative_price_charging_cost_uses_the_rational_baseline(self) -> None:
        scenario = make_scenario([2_000, 0], [-20, 100])
        dispatch = optimize_dispatch(scenario)
        result = evaluate_financials(
            dispatch,
            scenario,
            FinancialAssumptions(1_000, 0, 2, 0.08),
        )
        self.assertGreater(dispatch.summary.battery_discharge_energy_mwh, 0)
        self.assertIsNotNone(result.lcos_eur_per_mwh)

    def test_financial_benefit_haircut_does_not_impersonate_capacity_fade(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        dispatch = optimize_dispatch(scenario)
        without_haircut = evaluate_financials(
            dispatch, scenario, FinancialAssumptions(1_000, 100, 5, 0.08)
        )
        with_haircut = evaluate_financials(
            dispatch,
            scenario,
            FinancialAssumptions(
                1_000,
                100,
                5,
                0.08,
                annual_benefit_degradation_fraction=0.10,
            ),
        )
        self.assertNotEqual(without_haircut.npv_eur, with_haircut.npv_eur)
        self.assertAlmostEqual(
            without_haircut.lcos_eur_per_mwh or 0,
            with_haircut.lcos_eur_per_mwh or 0,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
