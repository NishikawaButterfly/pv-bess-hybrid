from __future__ import annotations

import importlib.util
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from pv_bess.dispatch import optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import load_scenario
from pv_bess.provenance import analysis_sha256, scenario_sha256

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_DIRECTORY = _REPOSITORY_ROOT / "sample-data" / "monthly"
_DISPATCH_SHA256 = "45d62c07d58c8f381138cc54da10605c4a2fd5d75e38b84ef15ee45801964958"
_ANALYSIS_SHA256 = "a9b25aaec1e112250cd3bf2b3dc024fa27e4f6e8e69fe6ea01a6306b8a26e884"


def _load_generator() -> ModuleType:
    """Import the fixture generator script, which lives outside the package."""

    path = _REPOSITORY_ROOT / "tools" / "make_synthetic_year.py"
    spec = importlib.util.spec_from_file_location("make_synthetic_year", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MonthlySampleTests(unittest.TestCase):
    def test_committed_csv_matches_the_seeded_generator(self) -> None:
        generator = _load_generator()
        rows = generator.month_slice(generator.synthetic_year(2026), 3)
        expected = generator.render_csv(rows)
        committed = (_FIXTURE_DIRECTORY / "hourly.csv").read_text(encoding="utf-8")
        self.assertEqual(committed, expected)

    def test_monthly_sample_validates_and_a_week_slice_solves(self) -> None:
        scenario, assumptions = load_scenario(_FIXTURE_DIRECTORY / "scenario.json")
        self.assertEqual(len(scenario.intervals), 744)
        self.assertEqual(scenario.interval_hours, 1.0)
        self.assertEqual(assumptions.annualization_factor, 8_760 / 744)
        self.assertEqual(scenario_sha256(scenario), _DISPATCH_SHA256)
        self.assertEqual(analysis_sha256(scenario, assumptions), _ANALYSIS_SHA256)

        week = replace(scenario, intervals=scenario.intervals[:168])
        summary = optimize_dispatch(week).summary
        self.assertAlmostEqual(summary.operating_value_eur, 8_457.4041584)
        self.assertAlmostEqual(summary.incremental_operating_value_eur, 2_662.8921584)
        self.assertAlmostEqual(summary.equivalent_full_cycles, 5.145792)
        self.assertAlmostEqual(summary.ending_soc_kwh, 10_000)
        self.assertAlmostEqual(summary.curtailed_energy_mwh, 0)

    @unittest.skipUnless(
        os.environ.get("PV_BESS_RUN_SLOW_TESTS"),
        "set PV_BESS_RUN_SLOW_TESTS=1 to solve the full 744-hour month",
    )
    def test_full_month_solves_end_to_end(self) -> None:
        scenario, assumptions = load_scenario(_FIXTURE_DIRECTORY / "scenario.json")
        dispatch = optimize_dispatch(scenario)
        financial = evaluate_financials(dispatch, scenario, assumptions)
        self.assertEqual(dispatch.input_sha256, _DISPATCH_SHA256)
        self.assertEqual(financial.analysis_input_sha256, _ANALYSIS_SHA256)

        summary = dispatch.summary
        self.assertAlmostEqual(summary.pv_energy_mwh, 771.06)
        self.assertAlmostEqual(summary.curtailed_energy_mwh, 0)
        self.assertAlmostEqual(summary.baseline_curtailed_energy_mwh, 0)
        self.assertIsNone(summary.curtailment_reduction_fraction)
        self.assertAlmostEqual(summary.incremental_operating_value_eur, 13_375.5431584)
        self.assertAlmostEqual(summary.equivalent_full_cycles, 23.1457920)
        self.assertAlmostEqual(summary.ending_soc_kwh, 10_000)

        # The unfavorable investment result is intentional fixture evidence.
        self.assertAlmostEqual(financial.npv_eur, -4_751_352.98496495)
        self.assertAlmostEqual(financial.lcos_eur_per_mwh or 0, 175.50296269382608)
        self.assertIsNone(financial.irr_fraction)
        self.assertIsNone(financial.simple_payback_years)
        self.assertIsNone(financial.discounted_payback_years)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
