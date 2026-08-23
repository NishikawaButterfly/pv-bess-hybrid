"""Bounded one-at-a-time sensitivity reruns of the unchanged dispatch kernel."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Literal

from pv_bess.dispatch import DispatchOptimizationError, optimize_dispatch
from pv_bess.finance import evaluate_financials, financial_precondition_errors
from pv_bess.models import (
    DispatchResult,
    FinancialAssumptions,
    FinancialResult,
    IntervalInput,
    Scenario,
)

SPEC_SCHEMA_VERSION = "1.0"
MAX_TOTAL_RUNS = 32
SUPPORTED_PARAMETERS = (
    "capex_eur",
    "charge_efficiency",
    "degradation_cost_eur_per_mwh_dc_discharged",
    "discharge_efficiency",
    "discount_rate_fraction",
    "energy_capacity_kwh",
    "market_price_level",
    "power_kw",
)
# Financial parameters never enter the MILP, so their variants share the base
# dispatch and only the financial evaluation is redone.
FINANCIAL_PARAMETERS = frozenset({"capex_eur", "discount_rate_fraction"})
_CAPACITY_PARAMETER = "energy_capacity_kwh"
_MULTIPLIER_ONLY_PARAMETERS = frozenset({"market_price_level"})
_SPEC_ROOT_KEYS = frozenset({"schema_version", "parameters"})
_ENTRY_KEYS = frozenset({"multipliers", "values"})
_COST_KEY = "capex_eur_per_kwh"

ValueMode = Literal["multiplier", "absolute"]


class SensitivitySpecError(ValueError):
    """Raised when a sensitivity spec is malformed, unsupported, or over the run cap."""


@dataclass(frozen=True, slots=True)
class SensitivityVariant:
    """One change to the base case: a single parameter set to a multiplier or
    absolute value, with the marginal cost of capacity declared when the
    parameter resizes the battery."""

    parameter: str
    mode: ValueMode
    value: float
    capex_eur_per_kwh: float | None = None

    def __post_init__(self) -> None:
        if self.parameter not in SUPPORTED_PARAMETERS:
            raise SensitivitySpecError(
                f"unknown sensitivity parameter {self.parameter!r}; "
                f"supported parameters: {', '.join(SUPPORTED_PARAMETERS)}"
            )
        if self.parameter in _MULTIPLIER_ONLY_PARAMETERS and self.mode != "multiplier":
            raise SensitivitySpecError(f"{self.parameter} supports multipliers only")
        if not isfinite(self.value):
            raise SensitivitySpecError(f"{self.parameter} variant values must be finite")
        if self.mode == "multiplier" and self.value <= 0:
            raise SensitivitySpecError(f"{self.parameter} multipliers must be greater than zero")
        if self.parameter == _CAPACITY_PARAMETER:
            if self.capex_eur_per_kwh is None:
                raise SensitivitySpecError(
                    f"{_CAPACITY_PARAMETER} variants resize the battery while capex_eur "
                    "stays at the base value, so every size would carry the same capital "
                    f"cost; declare {_COST_KEY} (the marginal cost of capacity, in EUR "
                    f"per kWh) on the {_CAPACITY_PARAMETER} entry so each variant's "
                    "CAPEX co-varies with its size"
                )
            if not isfinite(self.capex_eur_per_kwh) or self.capex_eur_per_kwh < 0:
                raise SensitivitySpecError(f"{_COST_KEY} must be finite and nonnegative")
        elif self.capex_eur_per_kwh is not None:
            raise SensitivitySpecError(
                f"{_COST_KEY} applies only to {_CAPACITY_PARAMETER} variants; "
                f"{self.parameter} does not resize the battery"
            )

    @property
    def label(self) -> str:
        if self.mode == "multiplier":
            return f"{self.parameter}*{self.value:g}"
        return f"{self.parameter}={self.value:g}"


@dataclass(frozen=True, slots=True)
class SensitivitySpec:
    """An ordered, capped list of one-at-a-time variants."""

    variants: tuple[SensitivityVariant, ...]

    def __post_init__(self) -> None:
        if not self.variants:
            raise SensitivitySpecError("the spec must define at least one variant")
        total_runs = 1 + len(self.variants)
        if total_runs > MAX_TOTAL_RUNS:
            raise SensitivitySpecError(
                f"the spec requests {total_runs} runs including the base case; "
                f"at most {MAX_TOTAL_RUNS} runs are supported"
            )
        seen: set[tuple[str, ValueMode, float]] = set()
        for variant in self.variants:
            key = (variant.parameter, variant.mode, variant.value)
            if key in seen:
                raise SensitivitySpecError(f"duplicate variant {variant.label!r}")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class SensitivityRun:
    """The financial and market metrics of one row of the table.

    ``capex_eur`` is the capital cost the row was evaluated under: the base
    value for physical variants, the scanned value on the ``capex_eur`` axis,
    and the derived ``base + delta_kwh * capex_eur_per_kwh`` for capacity
    variants. ``warnings`` are the kernel's judgment of the assumptions this
    row used, so a scanned value that crosses a threshold is flagged on the
    row that crossed it.
    """

    label: str
    parameter: str | None
    mode: ValueMode | None
    value: float | None
    dispatch_input_sha256: str
    analysis_input_sha256: str
    market_value_eur: float
    npv_eur: float
    irr_fraction: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    lcos_eur_per_mwh: float | None
    capex_eur: float
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    """Base-case metrics plus one run per variant, with shared solver metadata."""

    scenario_name: str
    schema_version: str
    model_version: str
    solver_interface_name: str
    solver_interface_version: str
    solver_backend_name: str
    solver_backend_version: str | None
    requested_relative_mip_gap: float
    time_limit_seconds_per_phase: float
    base: SensitivityRun
    variants: tuple[SensitivityRun, ...]
    # The base case's warnings, kept at table level so an existing mistyped
    # input is not repeated on every row; a variant whose own assumptions
    # cross a threshold carries that warning on its run instead.
    warnings: tuple[str, ...] = ()


def _number_list(entry: dict[str, Any], parameter: str, key: str) -> tuple[float, ...]:
    raw = entry[key]
    if not isinstance(raw, list) or not raw:
        raise SensitivitySpecError(f"{parameter}.{key} must be a non-empty JSON array")
    values: list[float] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise SensitivitySpecError(f"{parameter}.{key} entries must be JSON numbers")
        values.append(float(item))
    return tuple(values)


def parse_sensitivity_spec(payload: Any) -> SensitivitySpec:
    """Validate a JSON-compatible spec mapping and return the ordered variant list."""

    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise SensitivitySpecError("the sensitivity spec must be a JSON object")
    unknown = sorted(set(payload) - _SPEC_ROOT_KEYS)
    if unknown:
        raise SensitivitySpecError(f"unknown spec key(s): {', '.join(unknown)}")
    if payload.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise SensitivitySpecError(
            f"spec schema_version must be {SPEC_SCHEMA_VERSION!r}; "
            f"received {payload.get('schema_version')!r}"
        )
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise SensitivitySpecError("parameters must be a non-empty JSON object")

    variants: list[SensitivityVariant] = []
    for parameter, entry in parameters.items():
        if not isinstance(parameter, str) or parameter not in SUPPORTED_PARAMETERS:
            raise SensitivitySpecError(
                f"unknown sensitivity parameter {parameter!r}; "
                f"supported parameters: {', '.join(SUPPORTED_PARAMETERS)}"
            )
        if not isinstance(entry, dict):
            raise SensitivitySpecError(f"{parameter} must be a JSON object")
        keys = set(entry)
        cost: float | None = None
        if _COST_KEY in keys:
            if parameter != _CAPACITY_PARAMETER:
                raise SensitivitySpecError(
                    f"{_COST_KEY} applies only to {_CAPACITY_PARAMETER} variants; "
                    f"{parameter} does not resize the battery"
                )
            raw_cost = entry[_COST_KEY]
            if isinstance(raw_cost, bool) or not isinstance(raw_cost, int | float):
                raise SensitivitySpecError(f"{parameter}.{_COST_KEY} must be a JSON number")
            cost = float(raw_cost)
            keys.discard(_COST_KEY)
        if len(keys) != 1 or not keys <= _ENTRY_KEYS:
            raise SensitivitySpecError(
                f"{parameter} must define exactly one of 'multipliers' or 'values'"
            )
        key = next(iter(keys))
        mode: ValueMode = "multiplier" if key == "multipliers" else "absolute"
        variants.extend(
            SensitivityVariant(parameter=parameter, mode=mode, value=value, capex_eur_per_kwh=cost)
            for value in _number_list(entry, parameter, key)
        )
    return SensitivitySpec(variants=tuple(variants))


def _resolved(base_value: float, variant: SensitivityVariant) -> float:
    if variant.mode == "multiplier":
        return base_value * variant.value
    return variant.value


def apply_variant(scenario: Scenario, variant: SensitivityVariant) -> Scenario:
    """Return a revalidated copy of the scenario with exactly one parameter changed.

    Financial parameters do not live in the scenario, so their variants return
    it untouched; :func:`variant_assumptions` is where they take effect.
    """

    try:
        if variant.parameter in FINANCIAL_PARAMETERS:
            return scenario
        if variant.parameter == "market_price_level":
            intervals = tuple(
                IntervalInput(
                    timestamp=item.timestamp,
                    pv_power_kw=item.pv_power_kw,
                    market_price_eur_per_mwh=item.market_price_eur_per_mwh * variant.value,
                )
                for item in scenario.intervals
            )
            return replace(scenario, intervals=intervals)
        battery = scenario.battery
        if variant.parameter == "energy_capacity_kwh":
            battery = replace(
                battery,
                energy_capacity_kwh=_resolved(battery.energy_capacity_kwh, variant),
            )
        elif variant.parameter == "power_kw":
            battery = replace(
                battery,
                max_charge_power_kw=_resolved(battery.max_charge_power_kw, variant),
                max_discharge_power_kw=_resolved(battery.max_discharge_power_kw, variant),
            )
        elif variant.parameter == "charge_efficiency":
            battery = replace(
                battery,
                charge_efficiency=_resolved(battery.charge_efficiency, variant),
            )
        elif variant.parameter == "discharge_efficiency":
            battery = replace(
                battery,
                discharge_efficiency=_resolved(battery.discharge_efficiency, variant),
            )
        else:
            battery = replace(
                battery,
                degradation_cost_eur_per_mwh_dc_discharged=_resolved(
                    battery.degradation_cost_eur_per_mwh_dc_discharged, variant
                ),
            )
        return replace(scenario, battery=battery)
    except SensitivitySpecError:
        raise
    except ValueError as exc:
        raise SensitivitySpecError(
            f"variant {variant.label!r} produces an invalid scenario: {exc}"
        ) from exc


def variant_assumptions(
    scenario: Scenario,
    assumptions: FinancialAssumptions,
    variant: SensitivityVariant,
) -> FinancialAssumptions:
    """Return the revalidated financial assumptions a variant is evaluated under.

    Physical variants other than capacity share the base assumptions. A
    capacity variant derives its CAPEX from the declared marginal cost, so a
    resized battery is priced as resized instead of inheriting the base cost.
    """

    if variant.parameter == "capex_eur":
        capex = _resolved(assumptions.capex_eur, variant)
        try:
            return replace(assumptions, capex_eur=capex)
        except ValueError as exc:
            raise SensitivitySpecError(
                f"variant {variant.label!r} sets capex_eur = {capex:g}, which is invalid: {exc}"
            ) from exc
    if variant.parameter == "discount_rate_fraction":
        rate = _resolved(assumptions.discount_rate_fraction, variant)
        try:
            return replace(assumptions, discount_rate_fraction=rate)
        except ValueError as exc:
            raise SensitivitySpecError(
                f"variant {variant.label!r} sets discount_rate_fraction = {rate:g}, "
                f"which is invalid: {exc}"
            ) from exc
    if variant.parameter == _CAPACITY_PARAMETER:
        # The variant constructor refuses capacity variants without a cost.
        assert variant.capex_eur_per_kwh is not None
        base_kwh = scenario.battery.energy_capacity_kwh
        new_kwh = _resolved(base_kwh, variant)
        capex = assumptions.capex_eur + (new_kwh - base_kwh) * variant.capex_eur_per_kwh
        try:
            return replace(assumptions, capex_eur=capex)
        except ValueError as exc:
            # The refused value is derived, not typed, so show the arithmetic:
            # every input the user wrote may be positive while the result is not.
            raise SensitivitySpecError(
                f"variant {variant.label!r} derives capex_eur = {assumptions.capex_eur:g} "
                f"+ ({new_kwh:g} - {base_kwh:g}) * {variant.capex_eur_per_kwh:g} "
                f"= {capex:g}, which is invalid: {exc}"
            ) from exc
    return assumptions


def _run_metrics(
    label: str,
    variant: SensitivityVariant | None,
    dispatch: DispatchResult,
    financial: FinancialResult,
    assumptions: FinancialAssumptions,
) -> SensitivityRun:
    return SensitivityRun(
        label=label,
        parameter=variant.parameter if variant else None,
        mode=variant.mode if variant else None,
        value=variant.value if variant else None,
        dispatch_input_sha256=dispatch.input_sha256,
        analysis_input_sha256=financial.analysis_input_sha256,
        market_value_eur=dispatch.summary.market_value_eur,
        npv_eur=financial.npv_eur,
        irr_fraction=financial.irr_fraction,
        simple_payback_years=financial.simple_payback_years,
        discounted_payback_years=financial.discounted_payback_years,
        lcos_eur_per_mwh=financial.lcos_eur_per_mwh,
        capex_eur=assumptions.capex_eur,
        warnings=financial.warnings,
    )


def run_sensitivity(
    scenario: Scenario,
    assumptions: FinancialAssumptions,
    spec: SensitivitySpec,
    *,
    time_limit_seconds: float = 60.0,
    relative_mip_gap: float = 1e-8,
) -> SensitivityResult:
    """Solve the base case and every one-at-a-time variant with the unchanged kernel."""

    # Every row ends in a financial evaluation, so an input-only financial
    # refusal is raised before the base solve instead of after it.
    for message in financial_precondition_errors(scenario, assumptions):
        raise ValueError(message)

    variant_inputs = [
        (
            variant,
            apply_variant(scenario, variant),
            variant_assumptions(scenario, assumptions, variant),
        )
        for variant in spec.variants
    ]

    base_dispatch = optimize_dispatch(
        scenario,
        time_limit_seconds=time_limit_seconds,
        relative_mip_gap=relative_mip_gap,
    )
    base_financial = evaluate_financials(base_dispatch, scenario, assumptions)
    base_run = _run_metrics("base", None, base_dispatch, base_financial, assumptions)

    variant_runs: list[SensitivityRun] = []
    for variant, variant_scenario, variant_assumption_set in variant_inputs:
        if variant.parameter in FINANCIAL_PARAMETERS:
            # The dispatch is a function of the scenario alone, so a
            # financial-only variant shares the base solve and its row keeps
            # the base dispatch_input_sha256 to say so.
            dispatch = base_dispatch
        else:
            try:
                dispatch = optimize_dispatch(
                    variant_scenario,
                    time_limit_seconds=time_limit_seconds,
                    relative_mip_gap=relative_mip_gap,
                )
            except DispatchOptimizationError as exc:
                raise DispatchOptimizationError(f"variant {variant.label!r}: {exc}") from exc
        financial = evaluate_financials(dispatch, variant_scenario, variant_assumption_set)
        variant_runs.append(
            _run_metrics(variant.label, variant, dispatch, financial, variant_assumption_set)
        )

    return SensitivityResult(
        scenario_name=scenario.name,
        schema_version=base_dispatch.schema_version,
        model_version=base_dispatch.model_version,
        solver_interface_name=base_dispatch.solver_interface_name,
        solver_interface_version=base_dispatch.solver_interface_version,
        solver_backend_name=base_dispatch.solver_backend_name,
        solver_backend_version=base_dispatch.solver_backend_version,
        requested_relative_mip_gap=base_dispatch.requested_relative_mip_gap,
        time_limit_seconds_per_phase=base_dispatch.time_limit_seconds_per_phase,
        base=base_run,
        variants=tuple(variant_runs),
        warnings=base_financial.warnings,
    )
