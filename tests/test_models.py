from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from pv_bess.models import (
    BatteryConfig,
    DatasetMetadata,
    FinancialAssumptions,
    GridConfig,
    IntervalInput,
    Scenario,
)
from tests.helpers import make_scenario


class ModelValidationTests(unittest.TestCase):
    def test_timestamp_requires_offset(self) -> None:
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            IntervalInput(datetime(2026, 1, 1), 0, 0)

    def test_nonfinite_power_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            IntervalInput(datetime(2026, 1, 1, tzinfo=UTC), float("nan"), 0)

    def test_battery_operating_window_is_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "inside the operating window"):
            BatteryConfig(1_000, 500, 500, 0.2, 0.8, 0.1)

    def test_series_gaps_are_rejected(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        intervals = (
            *scenario.intervals,
            IntervalInput(
                scenario.intervals[-1].timestamp + timedelta(hours=2),
                0,
                0,
            ),
        )
        with self.assertRaisesRegex(ValueError, "uniform interval"):
            Scenario(
                scenario.name,
                intervals,
                scenario.battery,
                scenario.grid,
                scenario.dataset,
            )

    def test_interval_duration_is_inferred_in_utc(self) -> None:
        scenario = make_scenario([0, 0], [0, 0], interval_hours=0.25)
        self.assertAlmostEqual(scenario.interval_hours, 0.25)

    def test_non_eur_scenario_is_rejected_until_currency_is_generalized(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        with self.assertRaisesRegex(ValueError, "supports EUR"):
            Scenario(
                scenario.name,
                scenario.intervals,
                scenario.battery,
                scenario.grid,
                DatasetMetadata("USD fixture", "Hand-calculated", "CC0-1.0", "UTC", "USD"),
            )

    def test_extreme_price_is_rejected_for_numerical_conditioning(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute market_price"):
            IntervalInput(
                datetime(2026, 1, 1, tzinfo=UTC),
                0,
                1_000_001,
            )

    def test_scenario_requires_immutable_interval_tuple(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        with self.assertRaisesRegex(TypeError, "immutable tuple"):
            Scenario(
                scenario.name,
                list(scenario.intervals),  # type: ignore[arg-type]
                scenario.battery,
                scenario.grid,
                scenario.dataset,
            )

    def test_project_life_must_be_an_integer(self) -> None:
        with self.assertRaisesRegex(TypeError, "must be an integer"):
            FinancialAssumptions(1_000, 10, 1.5, 0.08)  # type: ignore[arg-type]

    def test_battery_rejects_invalid_physical_inputs(self) -> None:
        cases = [
            ("zero capacity", {"energy_capacity_kwh": 0}, "greater than zero"),
            ("excess power", {"max_charge_power_kw": 1_000_000_001}, "must not exceed"),
            ("bad minimum", {"minimum_soc_fraction": -0.1}, "between zero and one"),
            (
                "reversed window",
                {"minimum_soc_fraction": 0.9, "maximum_soc_fraction": 0.8},
                "must be less",
            ),
            ("bad terminal", {"terminal_soc_fraction": 0.95}, "inside the operating"),
            ("zero charge efficiency", {"charge_efficiency": 0}, "greater than zero"),
            ("efficiency above one", {"discharge_efficiency": 1.1}, "at most one"),
            (
                "negative degradation reserve",
                {"degradation_cost_eur_per_mwh_dc_discharged": -1},
                "greater than or equal",
            ),
        ]
        defaults = {
            "energy_capacity_kwh": 1_000,
            "max_charge_power_kw": 500,
            "max_discharge_power_kw": 500,
            "minimum_soc_fraction": 0.1,
            "maximum_soc_fraction": 0.9,
            "initial_soc_fraction": 0.5,
            "terminal_soc_fraction": 0.5,
            "charge_efficiency": 0.95,
            "discharge_efficiency": 0.95,
            "degradation_cost_eur_per_mwh_dc_discharged": 0,
        }
        for name, overrides, message in cases:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, message):
                BatteryConfig(**(defaults | overrides))

    def test_grid_and_dataset_contract_failures_are_explicit(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one grid limit"):
            GridConfig(0, 0)
        with self.assertRaisesRegex(ValueError, "import_limit_kw must be positive"):
            GridConfig(1_000, 0, True)
        with self.assertRaisesRegex(ValueError, "must not be blank"):
            DatasetMetadata("", "source", "CC0-1.0", "UTC")
        with self.assertRaisesRegex(ValueError, "ISO 4217"):
            DatasetMetadata("data", "source", "CC0-1.0", "UTC", "EURO")

    def test_scenario_time_axis_failures_are_explicit(self) -> None:
        scenario = make_scenario([0, 0], [0, 0])
        with self.assertRaisesRegex(ValueError, "name must not be blank"):
            replace(scenario, name=" ")
        with self.assertRaisesRegex(ValueError, "at least two intervals"):
            replace(scenario, intervals=scenario.intervals[:1])
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            replace(scenario, intervals=(scenario.intervals[0], scenario.intervals[0]))
        delayed = replace(
            scenario.intervals[1],
            timestamp=scenario.intervals[0].timestamp + timedelta(hours=25),
        )
        with self.assertRaisesRegex(ValueError, "must not exceed 24 hours"):
            replace(scenario, intervals=(scenario.intervals[0], delayed))

    def test_financial_bounds_are_explicit(self) -> None:
        cases = [
            ((-1, 0, 1, 0.08), "greater than or equal"),
            ((1, 0, 0, 0.08), "between 1 and 100"),
            ((1, 0, 1, -0.951), r"\[-0.95, 10\]"),
            ((1, 0, 1, 10.1), r"\[-0.95, 10\]"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, message):
                FinancialAssumptions(*arguments)
        with self.assertRaisesRegex(ValueError, "annualization_factor"):
            FinancialAssumptions(1, 0, 1, 0.08, 0)
        with self.assertRaisesRegex(ValueError, "benefit_degradation"):
            FinancialAssumptions(1, 0, 1, 0.08, annual_benefit_degradation_fraction=1)
        with self.assertRaisesRegex(ValueError, "opex_escalation"):
            FinancialAssumptions(1, 0, 1, 0.08, annual_opex_escalation_fraction=1.1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
