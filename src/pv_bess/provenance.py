"""Canonical input serialization and content hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any

from pv_bess.models import FinancialAssumptions, Scenario


def scenario_payload(scenario: Scenario) -> dict[str, Any]:
    """Return the complete dispatch calculation input as a JSON-compatible mapping.

    The multi-year fade parameters never change the dispatch problem, so they are
    hashed by :func:`analysis_sha256` instead: two scenarios that differ only in
    fade share one dispatch and therefore one dispatch-input hash.
    """

    return {
        "name": scenario.name,
        "dataset": {
            "name": scenario.dataset.name,
            "source": scenario.dataset.source,
            "license_id": scenario.dataset.license_id,
            "timezone_name": scenario.dataset.timezone_name,
            "currency": scenario.dataset.currency.upper(),
            "synthetic": scenario.dataset.synthetic,
        },
        "battery": {
            "energy_capacity_kwh": scenario.battery.energy_capacity_kwh,
            "max_charge_power_kw": scenario.battery.max_charge_power_kw,
            "max_discharge_power_kw": scenario.battery.max_discharge_power_kw,
            "minimum_soc_fraction": scenario.battery.minimum_soc_fraction,
            "maximum_soc_fraction": scenario.battery.maximum_soc_fraction,
            "initial_soc_fraction": scenario.battery.initial_soc_fraction,
            "terminal_soc_fraction": scenario.battery.resolved_terminal_soc_fraction,
            "charge_efficiency": scenario.battery.charge_efficiency,
            "discharge_efficiency": scenario.battery.discharge_efficiency,
            "degradation_cost_eur_per_mwh_dc_discharged": (
                scenario.battery.degradation_cost_eur_per_mwh_dc_discharged
            ),
        },
        "grid": {
            "export_limit_kw": scenario.grid.export_limit_kw,
            "import_limit_kw": scenario.grid.import_limit_kw,
            "allow_grid_charging": scenario.grid.allow_grid_charging,
        },
        "intervals": [
            {
                "timestamp": item.timestamp.astimezone(UTC).isoformat(),
                "pv_power_kw": item.pv_power_kw,
                "market_price_eur_per_mwh": item.market_price_eur_per_mwh,
            }
            for item in scenario.intervals
        ],
    }


def scenario_sha256(scenario: Scenario) -> str:
    """Hash a scenario after deterministic canonical JSON serialization."""

    canonical = json.dumps(
        scenario_payload(scenario),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def financial_payload(assumptions: FinancialAssumptions) -> dict[str, Any]:
    """Return every financial calculation input as a JSON-compatible mapping."""

    return {
        "capex_eur": assumptions.capex_eur,
        "annual_fixed_opex_eur": assumptions.annual_fixed_opex_eur,
        "project_life_years": assumptions.project_life_years,
        "discount_rate_fraction": assumptions.discount_rate_fraction,
        "annualization_factor": assumptions.annualization_factor,
        "annual_benefit_degradation_fraction": (assumptions.annual_benefit_degradation_fraction),
        "annual_opex_escalation_fraction": assumptions.annual_opex_escalation_fraction,
    }


def analysis_sha256(scenario: Scenario, assumptions: FinancialAssumptions) -> str:
    """Hash the dispatch scenario and all downstream financial assumptions together."""

    payload: dict[str, Any] = {
        "scenario": scenario_payload(scenario),
        "financial": financial_payload(assumptions),
    }
    battery = scenario.battery
    # Zero fade is exactly the pre-fade financial model, so the block is added
    # only when fade is active and every earlier analysis hash stays valid.
    if battery.calendar_fade_fraction_per_year != 0 or battery.cycling_fade_fraction_per_efc != 0:
        payload["battery_fade"] = {
            "calendar_fade_fraction_per_year": battery.calendar_fade_fraction_per_year,
            "cycling_fade_fraction_per_efc": battery.cycling_fade_fraction_per_efc,
            "minimum_capacity_fraction": battery.minimum_capacity_fraction,
        }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
