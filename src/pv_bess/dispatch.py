"""Mixed-integer hourly dispatch optimizer with explicit energy accounting."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from math import inf, isfinite

import numpy as np
import scipy
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from pv_bess.models import (
    MODEL_VERSION,
    SCHEMA_VERSION,
    DispatchResult,
    DispatchSummary,
    IntervalDispatch,
    Scenario,
    SolverPhaseMetadata,
)
from pv_bess.provenance import scenario_sha256

_FLOW_ZERO_TOLERANCE_KW = 1e-6
_ENERGY_BALANCE_TOLERANCE_KWH = 1e-4
_ECONOMIC_VALIDATION_TOLERANCE_EUR = 1e-6


class DispatchOptimizationError(RuntimeError):
    """Raised when no optimal, validated dispatch can be produced."""


@dataclass(frozen=True, slots=True)
class _VariableIndex:
    interval_count: int

    @property
    def pv_export(self) -> int:
        return 0

    @property
    def pv_charge(self) -> int:
        return self.interval_count

    @property
    def grid_charge(self) -> int:
        return 2 * self.interval_count

    @property
    def battery_export(self) -> int:
        return 3 * self.interval_count

    @property
    def curtailment(self) -> int:
        return 4 * self.interval_count

    @property
    def soc(self) -> int:
        return 5 * self.interval_count

    @property
    def charge_mode(self) -> int:
        return 6 * self.interval_count + 1

    @property
    def import_mode(self) -> int:
        return 7 * self.interval_count + 1

    @property
    def variable_count(self) -> int:
        return 8 * self.interval_count + 1

    def at(self, offset: int, interval: int) -> int:
        return offset + interval


def _clean(value: float) -> float:
    if abs(value) <= _FLOW_ZERO_TOLERANCE_KW:
        return 0.0
    return float(value)


def _build_problem(
    scenario: Scenario,
) -> tuple[
    NDArray[np.float64],
    NDArray[np.int32],
    Bounds,
    LinearConstraint,
    _VariableIndex,
]:
    count = len(scenario.intervals)
    index = _VariableIndex(count)
    hours = scenario.interval_hours
    battery = scenario.battery
    grid = scenario.grid

    objective = np.zeros(index.variable_count, dtype=float)
    lower_bounds = np.zeros(index.variable_count, dtype=float)
    upper_bounds = np.full(index.variable_count, inf, dtype=float)
    integrality = np.zeros(index.variable_count, dtype=np.int32)

    for interval, item in enumerate(scenario.intervals):
        revenue_coefficient = item.market_price_eur_per_mwh * hours / 1_000
        objective[index.at(index.pv_export, interval)] = -revenue_coefficient
        objective[index.at(index.battery_export, interval)] = (
            -revenue_coefficient
            + battery.degradation_cost_eur_per_mwh_dc_discharged
            * hours
            / (battery.discharge_efficiency * 1_000)
        )
        objective[index.at(index.grid_charge, interval)] = revenue_coefficient

        upper_bounds[index.at(index.pv_export, interval)] = item.pv_power_kw
        upper_bounds[index.at(index.pv_charge, interval)] = min(
            item.pv_power_kw, battery.max_charge_power_kw
        )
        upper_bounds[index.at(index.grid_charge, interval)] = (
            min(grid.import_limit_kw, battery.max_charge_power_kw)
            if grid.allow_grid_charging
            else 0.0
        )
        upper_bounds[index.at(index.battery_export, interval)] = min(
            grid.export_limit_kw, battery.max_discharge_power_kw
        )
        upper_bounds[index.at(index.curtailment, interval)] = item.pv_power_kw

    for state in range(count + 1):
        lower_bounds[index.at(index.soc, state)] = battery.minimum_soc_kwh
        upper_bounds[index.at(index.soc, state)] = battery.maximum_soc_kwh
    lower_bounds[index.soc] = battery.initial_soc_kwh
    upper_bounds[index.soc] = battery.initial_soc_kwh
    lower_bounds[index.at(index.soc, count)] = battery.terminal_soc_kwh
    upper_bounds[index.at(index.soc, count)] = battery.terminal_soc_kwh

    for offset in (index.charge_mode, index.import_mode):
        upper_bounds[offset : offset + count] = 1.0
        integrality[offset : offset + count] = 1

    rows_per_interval = 6
    matrix = lil_matrix((rows_per_interval * count, index.variable_count), dtype=float)
    constraint_lower = np.full(rows_per_interval * count, -inf, dtype=float)
    constraint_upper = np.full(rows_per_interval * count, inf, dtype=float)

    for interval, item in enumerate(scenario.intervals):
        row = rows_per_interval * interval

        # PV allocation: every available kW is exported, charged, or curtailed.
        matrix[row, index.at(index.pv_export, interval)] = 1
        matrix[row, index.at(index.pv_charge, interval)] = 1
        matrix[row, index.at(index.curtailment, interval)] = 1
        constraint_lower[row] = item.pv_power_kw
        constraint_upper[row] = item.pv_power_kw

        # Point-of-connection export limit and exclusive import direction.
        matrix[row + 1, index.at(index.pv_export, interval)] = 1
        matrix[row + 1, index.at(index.battery_export, interval)] = 1
        matrix[row + 1, index.at(index.import_mode, interval)] = grid.export_limit_kw
        constraint_upper[row + 1] = grid.export_limit_kw

        # Import is only available in import mode.
        matrix[row + 2, index.at(index.grid_charge, interval)] = 1
        matrix[row + 2, index.at(index.import_mode, interval)] = -grid.import_limit_kw
        constraint_upper[row + 2] = 0

        # Charging and discharging cannot occur in the same interval.
        matrix[row + 3, index.at(index.pv_charge, interval)] = 1
        matrix[row + 3, index.at(index.grid_charge, interval)] = 1
        matrix[row + 3, index.at(index.charge_mode, interval)] = -battery.max_charge_power_kw
        constraint_upper[row + 3] = 0

        matrix[row + 4, index.at(index.battery_export, interval)] = 1
        matrix[row + 4, index.at(index.charge_mode, interval)] = battery.max_discharge_power_kw
        constraint_upper[row + 4] = battery.max_discharge_power_kw

        # AC charge/discharge variables update DC stored energy with separate efficiencies.
        matrix[row + 5, index.at(index.soc, interval + 1)] = 1
        matrix[row + 5, index.at(index.soc, interval)] = -1
        matrix[row + 5, index.at(index.pv_charge, interval)] = -battery.charge_efficiency * hours
        matrix[row + 5, index.at(index.grid_charge, interval)] = -battery.charge_efficiency * hours
        matrix[row + 5, index.at(index.battery_export, interval)] = (
            hours / battery.discharge_efficiency
        )
        constraint_lower[row + 5] = 0
        constraint_upper[row + 5] = 0

    return (
        objective,
        integrality,
        Bounds(lower_bounds, upper_bounds),
        LinearConstraint(matrix.tocsr(), constraint_lower, constraint_upper),
        index,
    )


def _refinement_objective(scenario: Scenario, index: _VariableIndex) -> NDArray[np.float64]:
    """Minimize unnecessary battery throughput without changing operating economics."""

    objective = np.zeros(index.variable_count, dtype=float)
    hours = scenario.interval_hours
    for interval in range(len(scenario.intervals)):
        objective[index.at(index.pv_charge, interval)] = hours / 1_000
        objective[index.at(index.grid_charge, interval)] = hours / 1_000
        objective[index.at(index.battery_export, interval)] = hours / (
            scenario.battery.discharge_efficiency * 1_000
        )
        objective[index.at(index.curtailment, interval)] = hours / 1_000_000_000
    return objective


def _highs_backend_version() -> str | None:
    """Best-effort backend version; SciPy exposes it only through a private module."""

    try:
        core = importlib.import_module("scipy.optimize._highspy._core")
        version = vars(core)
        return (
            f"{version['HIGHS_VERSION_MAJOR']}."
            f"{version['HIGHS_VERSION_MINOR']}."
            f"{version['HIGHS_VERSION_PATCH']}"
        )
    except (ImportError, KeyError):
        return None


def _baseline_interval(scenario: Scenario, interval: int) -> tuple[float, float, float]:
    """Return rational PV-only export, curtailment, and market value."""

    item = scenario.intervals[interval]
    export_kw = min(item.pv_power_kw, scenario.grid.export_limit_kw)
    if item.market_price_eur_per_mwh < 0:
        export_kw = 0.0
    curtailed_kw = item.pv_power_kw - export_kw
    value_eur = export_kw * scenario.interval_hours * item.market_price_eur_per_mwh / 1_000
    return export_kw, curtailed_kw, value_eur


def _validate_solution(scenario: Scenario, intervals: tuple[IntervalDispatch, ...]) -> None:
    battery = scenario.battery
    grid = scenario.grid
    previous_soc_kwh = battery.initial_soc_kwh
    for item in intervals:
        numeric_values = (
            item.interval_hours,
            item.pv_power_kw,
            item.market_price_eur_per_mwh,
            item.pv_export_kw,
            item.pv_charge_kw,
            item.grid_charge_kw,
            item.battery_export_kw,
            item.curtailed_pv_kw,
            item.soc_start_kwh,
            item.soc_end_kwh,
            item.market_value_eur,
            item.degradation_cost_eur,
        )
        if any(not isfinite(value) for value in numeric_values):
            raise DispatchOptimizationError("optimized dispatch contains a non-finite value")
        flows = (
            item.pv_export_kw,
            item.pv_charge_kw,
            item.grid_charge_kw,
            item.battery_export_kw,
            item.curtailed_pv_kw,
        )
        if any(value < -_FLOW_ZERO_TOLERANCE_KW for value in flows):
            raise DispatchOptimizationError("optimized dispatch contains a negative flow")
        if abs(item.soc_start_kwh - previous_soc_kwh) > _ENERGY_BALANCE_TOLERANCE_KWH:
            raise DispatchOptimizationError("optimized SOC states are not continuous")
        pv_error_kwh = (
            abs(item.pv_power_kw - item.pv_export_kw - item.pv_charge_kw - item.curtailed_pv_kw)
            * item.interval_hours
        )
        if pv_error_kwh > _ENERGY_BALANCE_TOLERANCE_KWH:
            raise DispatchOptimizationError("optimized PV allocation does not conserve energy")
        if item.grid_export_kw > grid.export_limit_kw + _FLOW_ZERO_TOLERANCE_KW:
            raise DispatchOptimizationError("optimized dispatch exceeds the grid export limit")
        if item.grid_charge_kw > grid.import_limit_kw + _FLOW_ZERO_TOLERANCE_KW:
            raise DispatchOptimizationError("optimized dispatch exceeds the grid import limit")
        if (item.pv_charge_kw + item.grid_charge_kw) > (
            battery.max_charge_power_kw + _FLOW_ZERO_TOLERANCE_KW
        ):
            raise DispatchOptimizationError("optimized dispatch exceeds battery charge power")
        if item.battery_export_kw > (battery.max_discharge_power_kw + _FLOW_ZERO_TOLERANCE_KW):
            raise DispatchOptimizationError("optimized dispatch exceeds battery discharge power")
        if (
            item.pv_charge_kw + item.grid_charge_kw > _FLOW_ZERO_TOLERANCE_KW
            and item.battery_export_kw > _FLOW_ZERO_TOLERANCE_KW
        ):
            raise DispatchOptimizationError("battery charges and discharges simultaneously")
        if (
            item.grid_charge_kw > _FLOW_ZERO_TOLERANCE_KW
            and item.grid_export_kw > _FLOW_ZERO_TOLERANCE_KW
        ):
            raise DispatchOptimizationError("grid import and export occur simultaneously")
        expected_soc = (
            item.soc_start_kwh
            + (
                battery.charge_efficiency * (item.pv_charge_kw + item.grid_charge_kw)
                - item.battery_export_kw / battery.discharge_efficiency
            )
            * item.interval_hours
        )
        if abs(item.soc_end_kwh - expected_soc) > _ENERGY_BALANCE_TOLERANCE_KWH:
            raise DispatchOptimizationError("optimized SOC transition does not conserve energy")
        if not (
            battery.minimum_soc_kwh - _ENERGY_BALANCE_TOLERANCE_KWH
            <= item.soc_end_kwh
            <= battery.maximum_soc_kwh + _ENERGY_BALANCE_TOLERANCE_KWH
        ):
            raise DispatchOptimizationError("optimized SOC leaves the operating window")
        previous_soc_kwh = item.soc_end_kwh

    if abs(intervals[-1].soc_end_kwh - battery.terminal_soc_kwh) > (_ENERGY_BALANCE_TOLERANCE_KWH):
        raise DispatchOptimizationError("optimized dispatch misses the terminal SOC target")

    hours = scenario.interval_hours
    pv_input_kwh = sum(item.pv_power_kw * hours for item in intervals)
    grid_input_kwh = sum(item.grid_charge_kw * hours for item in intervals)
    export_kwh = sum(item.grid_export_kw * hours for item in intervals)
    curtailed_kwh = sum(item.curtailed_pv_kw * hours for item in intervals)
    conversion_losses_kwh = sum(
        (
            (1 - battery.charge_efficiency) * (item.pv_charge_kw + item.grid_charge_kw)
            + (1 / battery.discharge_efficiency - 1) * item.battery_export_kw
        )
        * hours
        for item in intervals
    )
    global_residual_kwh = (
        pv_input_kwh
        + grid_input_kwh
        + battery.initial_soc_kwh
        - export_kwh
        - curtailed_kwh
        - intervals[-1].soc_end_kwh
        - conversion_losses_kwh
    )
    scaled_tolerance_kwh = _ENERGY_BALANCE_TOLERANCE_KWH + 1e-9 * max(
        1.0, pv_input_kwh + grid_input_kwh + battery.initial_soc_kwh
    )
    if abs(global_residual_kwh) > scaled_tolerance_kwh:
        raise DispatchOptimizationError("optimized dispatch fails global energy conservation")


def optimize_dispatch(
    scenario: Scenario,
    *,
    time_limit_seconds: float = 60.0,
    relative_mip_gap: float = 1e-8,
) -> DispatchResult:
    """Optimize one scenario and reject any result that violates domain invariants."""

    if not isfinite(time_limit_seconds) or time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be finite and greater than zero")
    if not isfinite(relative_mip_gap) or not 0 <= relative_mip_gap < 1:
        raise ValueError("relative_mip_gap must be in [0, 1)")

    objective, integrality, bounds, constraints, index = _build_problem(scenario)
    primary_solution = milp(
        c=objective,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options={
            "disp": False,
            "mip_rel_gap": relative_mip_gap,
            "presolve": True,
            "time_limit": time_limit_seconds,
        },
    )
    if not primary_solution.success or primary_solution.x is None:
        raise DispatchOptimizationError(
            "dispatch optimization failed with status "
            f"{primary_solution.status}: {primary_solution.message}"
        )

    primary_value_eur = float(primary_solution.fun)
    economic_constraint = LinearConstraint(
        objective.reshape(1, -1),
        primary_value_eur,
        primary_value_eur,
    )
    refinement_solution = milp(
        c=_refinement_objective(scenario, index),
        integrality=integrality,
        bounds=bounds,
        constraints=(constraints, economic_constraint),
        options={
            "disp": False,
            "mip_rel_gap": relative_mip_gap,
            "presolve": True,
            "time_limit": time_limit_seconds,
        },
    )
    if not refinement_solution.success or refinement_solution.x is None:
        raise DispatchOptimizationError(
            "dispatch refinement failed with status "
            f"{refinement_solution.status}: {refinement_solution.message}"
        )
    refined_primary_value_eur = float(objective @ refinement_solution.x)
    if abs(refined_primary_value_eur - primary_value_eur) > (_ECONOMIC_VALIDATION_TOLERANCE_EUR):
        raise DispatchOptimizationError("dispatch refinement changed the economic optimum")

    values = refinement_solution.x
    hours = scenario.interval_hours
    battery = scenario.battery
    dispatch_rows: list[IntervalDispatch] = []
    baseline_export_energy_mwh = 0.0
    baseline_curtailed_energy_mwh = 0.0
    baseline_market_value_eur = 0.0

    for interval, item in enumerate(scenario.intervals):
        pv_export_kw = _clean(values[index.at(index.pv_export, interval)])
        pv_charge_kw = _clean(values[index.at(index.pv_charge, interval)])
        grid_charge_kw = _clean(values[index.at(index.grid_charge, interval)])
        battery_export_kw = _clean(values[index.at(index.battery_export, interval)])
        curtailed_pv_kw = _clean(values[index.at(index.curtailment, interval)])
        soc_start_kwh = _clean(values[index.at(index.soc, interval)])
        soc_end_kwh = _clean(values[index.at(index.soc, interval + 1)])

        market_value_eur = (
            (pv_export_kw + battery_export_kw - grid_charge_kw)
            * hours
            * item.market_price_eur_per_mwh
            / 1_000
        )
        degradation_cost_eur = (
            battery_export_kw
            * hours
            / battery.discharge_efficiency
            * battery.degradation_cost_eur_per_mwh_dc_discharged
            / 1_000
        )
        dispatch_rows.append(
            IntervalDispatch(
                timestamp=item.timestamp,
                interval_hours=hours,
                pv_power_kw=item.pv_power_kw,
                market_price_eur_per_mwh=item.market_price_eur_per_mwh,
                pv_export_kw=pv_export_kw,
                pv_charge_kw=pv_charge_kw,
                grid_charge_kw=grid_charge_kw,
                battery_export_kw=battery_export_kw,
                curtailed_pv_kw=curtailed_pv_kw,
                soc_start_kwh=soc_start_kwh,
                soc_end_kwh=soc_end_kwh,
                market_value_eur=market_value_eur,
                degradation_cost_eur=degradation_cost_eur,
            )
        )

        baseline_export, baseline_curtailment, baseline_value = _baseline_interval(
            scenario, interval
        )
        baseline_export_energy_mwh += baseline_export * hours / 1_000
        baseline_curtailed_energy_mwh += baseline_curtailment * hours / 1_000
        baseline_market_value_eur += baseline_value

    intervals = tuple(dispatch_rows)
    _validate_solution(scenario, intervals)

    pv_energy_mwh = sum(item.pv_power_kw * hours / 1_000 for item in intervals)
    export_energy_mwh = sum(item.grid_export_kw * hours / 1_000 for item in intervals)
    grid_charge_energy_mwh = sum(item.grid_charge_kw * hours / 1_000 for item in intervals)
    battery_discharge_energy_mwh = sum(item.battery_export_kw * hours / 1_000 for item in intervals)
    curtailed_energy_mwh = sum(item.curtailed_pv_kw * hours / 1_000 for item in intervals)
    market_value_eur = sum(item.market_value_eur for item in intervals)
    degradation_cost_eur = sum(item.degradation_cost_eur for item in intervals)
    operating_value_eur = market_value_eur - degradation_cost_eur
    incremental_value_eur = operating_value_eur - baseline_market_value_eur
    discharged_dc_kwh = sum(
        item.battery_export_kw * hours / battery.discharge_efficiency for item in intervals
    )
    equivalent_full_cycles = discharged_dc_kwh / battery.energy_capacity_kwh
    curtailment_reduction_fraction = None
    if baseline_curtailed_energy_mwh > 1e-12:
        curtailment_reduction_fraction = (
            baseline_curtailed_energy_mwh - curtailed_energy_mwh
        ) / baseline_curtailed_energy_mwh

    summary = DispatchSummary(
        pv_energy_mwh=pv_energy_mwh,
        export_energy_mwh=export_energy_mwh,
        grid_charge_energy_mwh=grid_charge_energy_mwh,
        battery_discharge_energy_mwh=battery_discharge_energy_mwh,
        curtailed_energy_mwh=curtailed_energy_mwh,
        baseline_export_energy_mwh=baseline_export_energy_mwh,
        baseline_curtailed_energy_mwh=baseline_curtailed_energy_mwh,
        market_value_eur=market_value_eur,
        degradation_cost_eur=degradation_cost_eur,
        operating_value_eur=operating_value_eur,
        baseline_market_value_eur=baseline_market_value_eur,
        incremental_operating_value_eur=incremental_value_eur,
        equivalent_full_cycles=equivalent_full_cycles,
        curtailment_reduction_fraction=curtailment_reduction_fraction,
        ending_soc_kwh=intervals[-1].soc_end_kwh,
    )
    return DispatchResult(
        scenario_name=scenario.name,
        input_sha256=scenario_sha256(scenario),
        schema_version=SCHEMA_VERSION,
        model_version=MODEL_VERSION,
        solver_interface_name="scipy.optimize.milp",
        solver_interface_version=scipy.__version__,
        solver_backend_name="HiGHS",
        solver_backend_version=_highs_backend_version(),
        requested_relative_mip_gap=relative_mip_gap,
        time_limit_seconds_per_phase=time_limit_seconds,
        economic_phase=SolverPhaseMetadata(
            status_code=int(primary_solution.status),
            status="optimal",
            message=str(primary_solution.message),
            achieved_relative_mip_gap=(
                float(primary_solution.mip_gap)
                if getattr(primary_solution, "mip_gap", None) is not None
                else None
            ),
            objective_value=primary_value_eur,
            objective_unit="EUR minimized (negative operating value)",
        ),
        refinement_phase=SolverPhaseMetadata(
            status_code=int(refinement_solution.status),
            status="optimal",
            message=str(refinement_solution.message),
            achieved_relative_mip_gap=(
                float(refinement_solution.mip_gap)
                if getattr(refinement_solution, "mip_gap", None) is not None
                else None
            ),
            objective_value=float(refinement_solution.fun),
            objective_unit="MWh-equivalent throughput refinement",
        ),
        intervals=intervals,
        summary=summary,
    )
