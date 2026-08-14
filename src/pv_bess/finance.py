"""Transparent unlevered, pre-tax financial calculations for a battery increment."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from math import isfinite

from pv_bess.models import (
    CapacityFadeSummary,
    DispatchResult,
    FinancialAssumptions,
    FinancialResult,
    Scenario,
)
from pv_bess.provenance import analysis_sha256, scenario_sha256

# A rate above 100% per year is legal and occasionally intended, so it is
# warned about rather than refused. The value is the boundary itself: 1.0 is a
# defensible 100% and stays silent.
PERCENTAGE_LIKE_RATE_THRESHOLD = 1.0


def assumption_warnings(assumptions: FinancialAssumptions) -> tuple[str, ...]:
    """Return plain-language warnings about inputs that are valid but probably mistyped.

    This is the single place warnings are produced. It is deliberately not part
    of :func:`net_present_value`, which :func:`internal_rate_of_return` evaluates
    at rates well above the threshold while bisecting, and not part of
    :class:`~pv_bess.models.FinancialAssumptions` validation, which can only
    accept or reject. Generating them here means every surface reads the same
    tuple off :class:`~pv_bess.models.FinancialResult` instead of repeating the
    judgment, so the text cannot diverge, duplicate, or be forgotten.
    """

    rate = assumptions.discount_rate_fraction
    if rate <= PERCENTAGE_LIKE_RATE_THRESHOLD:
        return ()
    return (
        f"discount_rate_fraction is {rate:g}, which the model read as "
        f"{rate * 100:g}% per year; a value above "
        f"{PERCENTAGE_LIKE_RATE_THRESHOLD:.1f} is usually a percentage entered as "
        f"a fraction, and {rate:g}% would be {rate / 100:g}. NPV, discounted "
        f"payback, and LCOS were calculated at {rate * 100:g}%.",
    )


def net_present_value(cash_flows_eur: Sequence[float], discount_rate_fraction: float) -> float:
    """Return NPV with the first cash flow occurring at time zero.

    The upper bound is a conditioning guard, not a plausibility guard: it keeps
    ``(1 + rate) ** period`` inside the float range for the longest supported
    project life, and :func:`internal_rate_of_return` bisects up to it. Judging
    whether a rate is plausible belongs to :func:`assumption_warnings`.
    """

    if not isfinite(discount_rate_fraction) or not -0.95 <= discount_rate_fraction <= 10:
        raise ValueError("discount_rate_fraction must be finite and in [-0.95, 10]")
    if not cash_flows_eur:
        raise ValueError("at least one cash flow is required")
    if any(not isfinite(value) for value in cash_flows_eur):
        raise ValueError("cash flows must be finite")
    return sum(
        value / (1 + discount_rate_fraction) ** period
        for period, value in enumerate(cash_flows_eur)
    )


def _sign_changes(values: Sequence[float]) -> int:
    signs = [1 if value > 0 else -1 for value in values if value != 0]
    return sum(left != right for left, right in pairwise(signs))


def internal_rate_of_return(cash_flows_eur: Sequence[float]) -> float | None:
    """Return the unique conventional IRR, or ``None`` when it is absent or ambiguous."""

    if len(cash_flows_eur) < 2:
        raise ValueError("at least two cash flows are required")
    if any(not isfinite(value) for value in cash_flows_eur):
        raise ValueError("cash flows must be finite")
    if _sign_changes(cash_flows_eur) != 1:
        return None

    def value(rate: float) -> float:
        return net_present_value(cash_flows_eur, rate)

    lower = -0.95
    upper = 1.0
    lower_value = value(lower)
    upper_value = value(upper)
    while lower_value * upper_value > 0 and upper < 10:
        upper = min(upper * 2, 10)
        upper_value = value(upper)
    if lower_value * upper_value > 0:
        return None

    for _ in range(200):
        midpoint = (lower + upper) / 2
        midpoint_value = value(midpoint)
        if abs(midpoint_value) <= 1e-10:
            return midpoint
        if lower_value * midpoint_value <= 0:
            upper = midpoint
            upper_value = midpoint_value
        else:
            lower = midpoint
            lower_value = midpoint_value
    return (lower + upper) / 2


def _payback_years(cash_flows_eur: Sequence[float], discount_rate: float | None) -> float | None:
    cumulative = cash_flows_eur[0]
    if cumulative >= 0:
        return 0.0
    for year, cash_flow in enumerate(cash_flows_eur[1:], start=1):
        adjusted = cash_flow
        if discount_rate is not None:
            adjusted /= (1 + discount_rate) ** year
        previous = cumulative
        cumulative += adjusted
        if cumulative >= 0 and adjusted > 0:
            return (year - 1) + (-previous / adjusted)
    return None


def _annual_lcos_inputs(
    dispatch: DispatchResult,
    scenario: Scenario,
) -> tuple[float, float]:
    """Return representative-period battery cost and discharged energy for LCOS."""

    charging_cost_eur = 0.0
    for result, source in zip(dispatch.intervals, scenario.intervals, strict=True):
        baseline_export_kw = min(source.pv_power_kw, scenario.grid.export_limit_kw)
        if source.market_price_eur_per_mwh < 0:
            baseline_export_kw = 0.0
        foregone_pv_export_kw = max(0.0, baseline_export_kw - result.pv_export_kw)
        charging_cost_eur += (
            (result.grid_charge_kw + foregone_pv_export_kw)
            * result.interval_hours
            * source.market_price_eur_per_mwh
            / 1_000
        )
    representative_cost_eur = charging_cost_eur + dispatch.summary.degradation_cost_eur
    return representative_cost_eur, dispatch.summary.battery_discharge_energy_mwh


def _capacity_fade_schedule(
    dispatch: DispatchResult,
    scenario: Scenario,
    assumptions: FinancialAssumptions,
) -> CapacityFadeSummary | None:
    """Return the per-year capacity trajectory, or ``None`` when no fade is configured.

    The representative dispatch is never re-solved: every project year keeps the
    year-one schedule scaled by its capacity fraction. Cycling fade accrues at the
    year-one annualized equivalent full cycles for every year, a first-order
    simplification that slightly overstates fade late in the project life.
    """

    battery = scenario.battery
    if battery.calendar_fade_fraction_per_year == 0 and battery.cycling_fade_fraction_per_efc == 0:
        return None
    annualized_efc = dispatch.summary.equivalent_full_cycles * assumptions.annualization_factor
    fade_per_year = (
        battery.calendar_fade_fraction_per_year
        + battery.cycling_fade_fraction_per_efc * annualized_efc
    )
    fractions: list[float] = []
    for year in range(1, assumptions.project_life_years + 1):
        fraction = 1 - fade_per_year * (year - 1)
        if fraction < battery.minimum_capacity_fraction:
            raise ValueError(
                f"the fade parameters drive the year-{year} capacity fraction to "
                f"{fraction:.6g}, below the validated minimum_capacity_fraction of "
                f"{battery.minimum_capacity_fraction:g}; reduce the fade parameters "
                "or shorten project_life_years"
            )
        fractions.append(fraction)
    return CapacityFadeSummary(
        calendar_fade_fraction_per_year=battery.calendar_fade_fraction_per_year,
        cycling_fade_fraction_per_efc=battery.cycling_fade_fraction_per_efc,
        minimum_capacity_fraction=battery.minimum_capacity_fraction,
        annualized_equivalent_full_cycles=annualized_efc,
        capacity_fraction_by_year=tuple(fractions),
    )


def evaluate_financials(
    dispatch: DispatchResult,
    scenario: Scenario,
    assumptions: FinancialAssumptions,
) -> FinancialResult:
    """Evaluate incremental battery cash flows using explicit annualization assumptions."""

    if dispatch.input_sha256 != scenario_sha256(scenario):
        raise ValueError("dispatch result does not match the supplied scenario")
    if abs(scenario.battery.initial_soc_kwh - scenario.battery.terminal_soc_kwh) > 1e-9:
        raise ValueError(
            "financial evaluation requires terminal SOC to equal initial SOC; "
            "inventory valuation is not implemented"
        )

    # A fraction of exactly 1.0 is a bit-exact multiplicative identity, so the
    # no-fade path reproduces the pre-fade cash flows and LCOS byte for byte.
    capacity_fade = _capacity_fade_schedule(dispatch, scenario, assumptions)
    if capacity_fade is None:
        capacity_fractions: tuple[float, ...] = (1.0,) * assumptions.project_life_years
    else:
        capacity_fractions = capacity_fade.capacity_fraction_by_year

    annual_incremental_value_eur = (
        dispatch.summary.incremental_operating_value_eur * assumptions.annualization_factor
    )
    cash_flows: list[float] = [-assumptions.capex_eur]
    for year in range(1, assumptions.project_life_years + 1):
        performance = (1 - assumptions.annual_benefit_degradation_fraction) ** (year - 1)
        opex_factor = (1 + assumptions.annual_opex_escalation_fraction) ** (year - 1)
        cash_flows.append(
            annual_incremental_value_eur * capacity_fractions[year - 1] * performance
            - assumptions.annual_fixed_opex_eur * opex_factor
        )

    npv_eur = net_present_value(cash_flows, assumptions.discount_rate_fraction)
    irr_fraction = internal_rate_of_return(cash_flows)
    simple_payback_years = _payback_years(cash_flows, None)
    discounted_payback_years = _payback_years(cash_flows, assumptions.discount_rate_fraction)

    # Both sides of the LCOS ratio follow the same per-year capacity trajectory
    # as the NPV cash flows: a faded year costs less and discharges less alike.
    representative_cost_eur, representative_discharge_mwh = _annual_lcos_inputs(dispatch, scenario)
    discounted_cost_eur = assumptions.capex_eur
    discounted_discharge_mwh = 0.0
    for year in range(1, assumptions.project_life_years + 1):
        capacity_fraction = capacity_fractions[year - 1]
        opex_factor = (1 + assumptions.annual_opex_escalation_fraction) ** (year - 1)
        discount_factor = (1 + assumptions.discount_rate_fraction) ** year
        annual_variable_cost = (
            representative_cost_eur * assumptions.annualization_factor * capacity_fraction
        )
        annual_fixed_cost = assumptions.annual_fixed_opex_eur * opex_factor
        discounted_cost_eur += (annual_variable_cost + annual_fixed_cost) / discount_factor
        discounted_discharge_mwh += (
            representative_discharge_mwh
            * assumptions.annualization_factor
            * capacity_fraction
            / discount_factor
        )
    lcos_eur_per_mwh = None
    if discounted_discharge_mwh > 1e-12:
        lcos_eur_per_mwh = discounted_cost_eur / discounted_discharge_mwh

    return FinancialResult(
        dispatch_input_sha256=dispatch.input_sha256,
        analysis_input_sha256=analysis_sha256(scenario, assumptions),
        cash_flows_eur=tuple(cash_flows),
        npv_eur=npv_eur,
        irr_fraction=irr_fraction,
        simple_payback_years=simple_payback_years,
        discounted_payback_years=discounted_payback_years,
        lcos_eur_per_mwh=lcos_eur_per_mwh,
        capacity_fade=capacity_fade,
        warnings=assumption_warnings(assumptions),
    )
