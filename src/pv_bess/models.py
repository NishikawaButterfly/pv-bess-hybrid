"""Typed domain models and validation for PV-BESS analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from math import isfinite

SCHEMA_VERSION = "1.0"
MODEL_VERSION = "dispatch-milp-1.0"
_MAX_POWER_KW = 1_000_000_000.0
_MAX_ENERGY_KWH = 1_000_000_000_000.0
_MAX_ABSOLUTE_PRICE_EUR_PER_MWH = 1_000_000.0
_MAX_MONETARY_INPUT_EUR = 1_000_000_000_000_000.0


def _require_finite(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_nonnegative(name: str, value: float) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _require_at_most(name: str, value: float, maximum: float) -> None:
    if value > maximum:
        raise ValueError(f"{name} must not exceed {maximum:g}")


@dataclass(frozen=True, slots=True)
class IntervalInput:
    """PV power and market price at the beginning of one interval."""

    timestamp: datetime
    pv_power_kw: float
    market_price_eur_per_mwh: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include an explicit UTC offset")
        _require_nonnegative("pv_power_kw", self.pv_power_kw)
        _require_finite("market_price_eur_per_mwh", self.market_price_eur_per_mwh)
        _require_at_most("pv_power_kw", self.pv_power_kw, _MAX_POWER_KW)
        if abs(self.market_price_eur_per_mwh) > _MAX_ABSOLUTE_PRICE_EUR_PER_MWH:
            raise ValueError(
                "absolute market_price_eur_per_mwh must not exceed "
                f"{_MAX_ABSOLUTE_PRICE_EUR_PER_MWH:g}"
            )


@dataclass(frozen=True, slots=True)
class BatteryConfig:
    """AC-side power limits and DC-side stored-energy constraints."""

    energy_capacity_kwh: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    minimum_soc_fraction: float = 0.10
    maximum_soc_fraction: float = 0.90
    initial_soc_fraction: float = 0.50
    terminal_soc_fraction: float | None = None
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    degradation_cost_eur_per_mwh_dc_discharged: float = 0.0

    def __post_init__(self) -> None:
        for name in ("energy_capacity_kwh", "max_charge_power_kw", "max_discharge_power_kw"):
            value = getattr(self, name)
            _require_finite(name, value)
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        _require_at_most("energy_capacity_kwh", self.energy_capacity_kwh, _MAX_ENERGY_KWH)
        _require_at_most("max_charge_power_kw", self.max_charge_power_kw, _MAX_POWER_KW)
        _require_at_most("max_discharge_power_kw", self.max_discharge_power_kw, _MAX_POWER_KW)

        fractions = {
            "minimum_soc_fraction": self.minimum_soc_fraction,
            "maximum_soc_fraction": self.maximum_soc_fraction,
            "initial_soc_fraction": self.initial_soc_fraction,
        }
        if self.terminal_soc_fraction is not None:
            fractions["terminal_soc_fraction"] = self.terminal_soc_fraction
        for name, value in fractions.items():
            _require_finite(name, value)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")

        if self.minimum_soc_fraction >= self.maximum_soc_fraction:
            raise ValueError("minimum_soc_fraction must be less than maximum_soc_fraction")
        if not (
            self.minimum_soc_fraction <= self.initial_soc_fraction <= self.maximum_soc_fraction
        ):
            raise ValueError("initial_soc_fraction must be inside the operating window")
        if not (
            self.minimum_soc_fraction
            <= self.resolved_terminal_soc_fraction
            <= self.maximum_soc_fraction
        ):
            raise ValueError("terminal_soc_fraction must be inside the operating window")

        for name in ("charge_efficiency", "discharge_efficiency"):
            value = getattr(self, name)
            _require_finite(name, value)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be greater than zero and at most one")
        _require_nonnegative(
            "degradation_cost_eur_per_mwh_dc_discharged",
            self.degradation_cost_eur_per_mwh_dc_discharged,
        )
        _require_at_most(
            "degradation_cost_eur_per_mwh_dc_discharged",
            self.degradation_cost_eur_per_mwh_dc_discharged,
            _MAX_ABSOLUTE_PRICE_EUR_PER_MWH,
        )

    @property
    def resolved_terminal_soc_fraction(self) -> float:
        """Return the explicit terminal target, defaulting to the initial SOC."""

        if self.terminal_soc_fraction is None:
            return self.initial_soc_fraction
        return self.terminal_soc_fraction

    @property
    def minimum_soc_kwh(self) -> float:
        return self.energy_capacity_kwh * self.minimum_soc_fraction

    @property
    def maximum_soc_kwh(self) -> float:
        return self.energy_capacity_kwh * self.maximum_soc_fraction

    @property
    def initial_soc_kwh(self) -> float:
        return self.energy_capacity_kwh * self.initial_soc_fraction

    @property
    def terminal_soc_kwh(self) -> float:
        return self.energy_capacity_kwh * self.resolved_terminal_soc_fraction

    @property
    def usable_energy_kwh(self) -> float:
        return self.maximum_soc_kwh - self.minimum_soc_kwh


@dataclass(frozen=True, slots=True)
class GridConfig:
    """Point-of-connection limits. Power values are nonnegative magnitudes."""

    export_limit_kw: float
    import_limit_kw: float = 0.0
    allow_grid_charging: bool = False

    def __post_init__(self) -> None:
        _require_nonnegative("export_limit_kw", self.export_limit_kw)
        _require_nonnegative("import_limit_kw", self.import_limit_kw)
        _require_at_most("export_limit_kw", self.export_limit_kw, _MAX_POWER_KW)
        _require_at_most("import_limit_kw", self.import_limit_kw, _MAX_POWER_KW)
        if self.export_limit_kw == 0 and self.import_limit_kw == 0:
            raise ValueError("at least one grid limit must be greater than zero")
        if self.allow_grid_charging and self.import_limit_kw == 0:
            raise ValueError("import_limit_kw must be positive when grid charging is enabled")


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Provenance required for every public or imported time series."""

    name: str
    source: str
    license_id: str
    timezone_name: str
    currency: str = "EUR"
    synthetic: bool = True

    def __post_init__(self) -> None:
        for name in ("name", "source", "license_id", "timezone_name", "currency"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be blank")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter ISO 4217 code")


@dataclass(frozen=True, slots=True)
class Scenario:
    """A validated, uniformly spaced dispatch scenario."""

    name: str
    intervals: tuple[IntervalInput, ...]
    battery: BatteryConfig
    grid: GridConfig
    dataset: DatasetMetadata

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must not be blank")
        if not isinstance(self.intervals, tuple):
            raise TypeError("intervals must be an immutable tuple")
        if self.dataset.currency.upper() != "EUR":
            raise ValueError("the current model supports EUR market and financial inputs only")
        if len(self.intervals) < 2:
            raise ValueError("at least two intervals are required to infer interval duration")

        utc_timestamps = [item.timestamp.astimezone(UTC) for item in self.intervals]
        expected_seconds = (utc_timestamps[1] - utc_timestamps[0]).total_seconds()
        if expected_seconds <= 0:
            raise ValueError("timestamps must be strictly increasing")
        if expected_seconds > 86_400:
            raise ValueError("interval duration must not exceed 24 hours")

        for previous, current in pairwise(utc_timestamps):
            actual_seconds = (current - previous).total_seconds()
            if actual_seconds <= 0:
                raise ValueError("timestamps must be unique and strictly increasing")
            if abs(actual_seconds - expected_seconds) > 1e-6:
                raise ValueError("timestamps must have a uniform interval with no gaps")

    @property
    def interval_hours(self) -> float:
        first = self.intervals[0].timestamp.astimezone(UTC)
        second = self.intervals[1].timestamp.astimezone(UTC)
        return (second - first).total_seconds() / 3_600


@dataclass(frozen=True, slots=True)
class FinancialAssumptions:
    """Unlevered, pre-tax project assumptions for the battery increment."""

    capex_eur: float
    annual_fixed_opex_eur: float
    project_life_years: int
    discount_rate_fraction: float
    annualization_factor: float = 1.0
    annual_benefit_degradation_fraction: float = 0.0
    annual_opex_escalation_fraction: float = 0.0

    def __post_init__(self) -> None:
        _require_nonnegative("capex_eur", self.capex_eur)
        _require_nonnegative("annual_fixed_opex_eur", self.annual_fixed_opex_eur)
        _require_at_most("capex_eur", self.capex_eur, _MAX_MONETARY_INPUT_EUR)
        _require_at_most(
            "annual_fixed_opex_eur", self.annual_fixed_opex_eur, _MAX_MONETARY_INPUT_EUR
        )
        if type(self.project_life_years) is not int:
            raise TypeError("project_life_years must be an integer")
        if not 1 <= self.project_life_years <= 100:
            raise ValueError("project_life_years must be between 1 and 100")
        _require_finite("annualization_factor", self.annualization_factor)
        if not 0 < self.annualization_factor <= 1_000_000:
            raise ValueError("annualization_factor must be in (0, 1000000]")
        for name in (
            "discount_rate_fraction",
            "annual_benefit_degradation_fraction",
            "annual_opex_escalation_fraction",
        ):
            _require_finite(name, getattr(self, name))
        if not -0.95 <= self.discount_rate_fraction <= 10:
            raise ValueError("discount_rate_fraction must be in [-0.95, 10]")
        if not 0 <= self.annual_benefit_degradation_fraction < 1:
            raise ValueError("annual_benefit_degradation_fraction must be in [0, 1)")
        if not -0.95 <= self.annual_opex_escalation_fraction <= 1:
            raise ValueError("annual_opex_escalation_fraction must be in [-0.95, 1]")


@dataclass(frozen=True, slots=True)
class IntervalDispatch:
    timestamp: datetime
    interval_hours: float
    pv_power_kw: float
    market_price_eur_per_mwh: float
    pv_export_kw: float
    pv_charge_kw: float
    grid_charge_kw: float
    battery_export_kw: float
    curtailed_pv_kw: float
    soc_start_kwh: float
    soc_end_kwh: float
    market_value_eur: float
    degradation_cost_eur: float

    @property
    def grid_export_kw(self) -> float:
        return self.pv_export_kw + self.battery_export_kw

    @property
    def net_operating_value_eur(self) -> float:
        return self.market_value_eur - self.degradation_cost_eur


@dataclass(frozen=True, slots=True)
class DispatchSummary:
    pv_energy_mwh: float
    export_energy_mwh: float
    grid_charge_energy_mwh: float
    battery_discharge_energy_mwh: float
    curtailed_energy_mwh: float
    baseline_export_energy_mwh: float
    baseline_curtailed_energy_mwh: float
    market_value_eur: float
    degradation_cost_eur: float
    operating_value_eur: float
    baseline_market_value_eur: float
    incremental_operating_value_eur: float
    equivalent_full_cycles: float
    curtailment_reduction_fraction: float | None
    ending_soc_kwh: float


@dataclass(frozen=True, slots=True)
class SolverPhaseMetadata:
    status_code: int
    status: str
    message: str
    achieved_relative_mip_gap: float | None
    objective_value: float
    objective_unit: str


@dataclass(frozen=True, slots=True)
class DispatchResult:
    scenario_name: str
    input_sha256: str
    schema_version: str
    model_version: str
    solver_interface_name: str
    solver_interface_version: str
    solver_backend_name: str
    solver_backend_version: str | None
    requested_relative_mip_gap: float
    time_limit_seconds_per_phase: float
    economic_phase: SolverPhaseMetadata
    refinement_phase: SolverPhaseMetadata
    intervals: tuple[IntervalDispatch, ...]
    summary: DispatchSummary


@dataclass(frozen=True, slots=True)
class FinancialResult:
    dispatch_input_sha256: str
    analysis_input_sha256: str
    cash_flows_eur: tuple[float, ...]
    npv_eur: float
    irr_fraction: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    lcos_eur_per_mwh: float | None
