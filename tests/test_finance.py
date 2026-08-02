from __future__ import annotations

import math
import unittest
from dataclasses import replace

from pv_bess.dispatch import optimize_dispatch
from pv_bess.finance import evaluate_financials, internal_rate_of_return, net_present_value
from pv_bess.models import BatteryConfig, FinancialAssumptions
from pv_bess.provenance import scenario_sha256
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

    def test_zero_fade_reproduces_the_unfaded_result_and_hashes_exactly(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        explicit = replace(
            scenario,
            battery=replace(
                scenario.battery,
                calendar_fade_fraction_per_year=0.0,
                cycling_fade_fraction_per_efc=0.0,
                minimum_capacity_fraction=0.0,
            ),
        )
        assumptions = FinancialAssumptions(1_000, 100, 5, 0.08, 365)
        baseline = evaluate_financials(optimize_dispatch(scenario), scenario, assumptions)
        explicit_result = evaluate_financials(optimize_dispatch(explicit), explicit, assumptions)
        self.assertEqual(scenario_sha256(scenario), scenario_sha256(explicit))
        self.assertEqual(baseline.analysis_input_sha256, explicit_result.analysis_input_sha256)
        self.assertEqual(baseline.cash_flows_eur, explicit_result.cash_flows_eur)
        self.assertEqual(baseline.npv_eur, explicit_result.npv_eur)
        self.assertEqual(baseline.lcos_eur_per_mwh, explicit_result.lcos_eur_per_mwh)
        self.assertIsNone(explicit_result.capacity_fade)

    def test_capacity_fade_matches_the_documented_hand_table(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        faded = replace(
            scenario,
            battery=replace(
                scenario.battery,
                calendar_fade_fraction_per_year=0.02,
                cycling_fade_fraction_per_efc=0.004,
                minimum_capacity_fraction=0.85,
            ),
        )
        dispatch = optimize_dispatch(faded)
        self.assertAlmostEqual(dispatch.summary.incremental_operating_value_eur, 99.0)
        self.assertAlmostEqual(dispatch.summary.battery_discharge_energy_mwh, 1.0)
        self.assertAlmostEqual(dispatch.summary.equivalent_full_cycles, 0.5)

        result = evaluate_financials(
            dispatch,
            faded,
            FinancialAssumptions(
                capex_eur=1_000,
                annual_fixed_opex_eur=0,
                project_life_years=4,
                discount_rate_fraction=0.0,
                annualization_factor=10,
            ),
        )
        fade = result.capacity_fade
        assert fade is not None
        self.assertAlmostEqual(fade.annualized_equivalent_full_cycles, 5.0)
        # The docs/methodology.md worked table: year, capacity fraction, benefit,
        # discharged MWh (discharged energy is 10 MWh times the fraction).
        expected_rows = ((1.0, 990.0), (0.96, 950.4), (0.92, 910.8), (0.88, 871.2))
        for year, (fraction, benefit_eur) in enumerate(expected_rows, start=1):
            self.assertAlmostEqual(fade.capacity_fraction_by_year[year - 1], fraction)
            self.assertAlmostEqual(result.cash_flows_eur[year], benefit_eur)
        self.assertAlmostEqual(result.npv_eur, 2_722.40)
        self.assertAlmostEqual(result.lcos_eur_per_mwh or 0, 1_037.60 / 37.60)

    def test_capacity_fade_scales_lcos_cost_and_energy_together(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        faded = replace(
            scenario,
            battery=replace(scenario.battery, calendar_fade_fraction_per_year=0.03),
        )
        # Fade never changes the dispatch problem, so one solved dispatch serves
        # both the faded and the unfaded evaluation.
        dispatch = optimize_dispatch(scenario)
        without_capex = FinancialAssumptions(0, 0, 10, 0.08, 365)
        unfaded = evaluate_financials(dispatch, scenario, without_capex)
        with_fade = evaluate_financials(dispatch, faded, without_capex)
        # With no CAPEX or fixed OPEX the variable cost per discharged MWh is
        # constant, so a consistently scaled numerator and denominator leave the
        # ratio unchanged while every faded year costs and discharges less.
        self.assertAlmostEqual(unfaded.lcos_eur_per_mwh or 0, with_fade.lcos_eur_per_mwh or 0)

        with_capex = FinancialAssumptions(1_000, 0, 10, 0.08, 365)
        self.assertGreater(
            evaluate_financials(dispatch, faded, with_capex).lcos_eur_per_mwh or 0,
            evaluate_financials(dispatch, scenario, with_capex).lcos_eur_per_mwh or 0,
        )

    def test_capacity_fade_changes_the_analysis_hash_but_not_the_dispatch_hash(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        faded = replace(
            scenario,
            battery=replace(scenario.battery, cycling_fade_fraction_per_efc=0.001),
        )
        self.assertEqual(scenario_sha256(scenario), scenario_sha256(faded))
        dispatch = optimize_dispatch(scenario)
        assumptions = FinancialAssumptions(1_000, 100, 5, 0.08, 365)
        plain = evaluate_financials(dispatch, scenario, assumptions)
        with_fade = evaluate_financials(dispatch, faded, assumptions)
        self.assertNotEqual(plain.analysis_input_sha256, with_fade.analysis_input_sha256)
        self.assertNotEqual(plain.npv_eur, with_fade.npv_eur)

    def test_fade_crossing_the_capacity_floor_is_rejected(self) -> None:
        scenario = make_scenario([2_000, 0], [20, 100])
        # 0.04 per year reaches 0.84 in year 5, below the 0.85 floor.
        floored = replace(
            scenario,
            battery=replace(
                scenario.battery,
                calendar_fade_fraction_per_year=0.04,
                minimum_capacity_fraction=0.85,
            ),
        )
        dispatch = optimize_dispatch(scenario)
        with self.assertRaisesRegex(ValueError, "minimum_capacity_fraction"):
            evaluate_financials(dispatch, floored, FinancialAssumptions(1_000, 0, 5, 0.08))
        # The default floor of zero still rejects capacity below zero.
        negative = replace(
            scenario,
            battery=replace(scenario.battery, calendar_fade_fraction_per_year=0.2),
        )
        with self.assertRaisesRegex(ValueError, "below the validated"):
            evaluate_financials(dispatch, negative, FinancialAssumptions(1_000, 0, 7, 0.08))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
