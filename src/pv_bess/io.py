"""Bounded scenario ingestion and deterministic result export."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pv_bess.models import (
    SCHEMA_VERSION,
    BatteryConfig,
    DatasetMetadata,
    DispatchResult,
    FinancialAssumptions,
    FinancialResult,
    GridConfig,
    IntervalInput,
    Scenario,
)

_MAX_SCENARIO_BYTES = 1_000_000
_MAX_TIME_SERIES_BYTES = 25_000_000
_MAX_INTERVALS = 100_000
_CSV_COLUMNS = ("timestamp", "pv_power_kw", "market_price_eur_per_mwh")
_ROOT_KEYS = {
    "schema_version",
    "name",
    "time_series_csv",
    "dataset",
    "battery",
    "grid",
    "financial",
}
_DATASET_KEYS = {"name", "source", "license_id", "timezone_name", "currency", "synthetic"}
_BATTERY_KEYS = {
    "energy_capacity_kwh",
    "max_charge_power_kw",
    "max_discharge_power_kw",
    "minimum_soc_fraction",
    "maximum_soc_fraction",
    "initial_soc_fraction",
    "terminal_soc_fraction",
    "charge_efficiency",
    "discharge_efficiency",
    "degradation_cost_eur_per_mwh_dc_discharged",
}
_GRID_KEYS = {"export_limit_kw", "import_limit_kw", "allow_grid_charging"}
_FINANCIAL_KEYS = {
    "capex_eur",
    "annual_fixed_opex_eur",
    "project_life_years",
    "discount_rate_fraction",
    "annualization_factor",
    "annual_benefit_degradation_fraction",
    "annual_opex_escalation_fraction",
}


class ScenarioFileError(ValueError):
    """Raised when a scenario file is unsafe, malformed, or unsupported."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioFileError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_unknown_keys(mapping: dict[str, Any], name: str, allowed: set[str]) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ScenarioFileError(f"unknown {name} key(s): {', '.join(unknown)}")


def _read_bounded_text(path: Path, maximum_bytes: int) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ScenarioFileError(f"cannot access {path}: {exc}") from exc
    if size > maximum_bytes:
        raise ScenarioFileError(f"{path.name} exceeds the {maximum_bytes}-byte limit")
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ScenarioFileError(f"cannot read {path} as UTF-8: {exc}") from exc


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ScenarioFileError(f"{name} must be a JSON object")
    return value


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioFileError(f"{key} must be a non-blank string")
    return value.strip()


def _number(mapping: dict[str, Any], key: str, default: float | None = None) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScenarioFileError(f"{key} must be a JSON number")
    return float(value)


def _integer(mapping: dict[str, Any], key: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioFileError(f"{key} must be a JSON integer")
    return value


def _boolean(mapping: dict[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise ScenarioFileError(f"{key} must be true or false")
    return value


def _optional_number(mapping: dict[str, Any], key: str) -> float | None:
    if key not in mapping or mapping[key] is None:
        return None
    return _number(mapping, key)


def _resolve_companion(base_directory: Path, relative_name: str) -> Path:
    candidate = Path(relative_name)
    if candidate.is_absolute():
        raise ScenarioFileError("time_series_csv must be a relative path")
    resolved_base = base_directory.resolve()
    resolved = (resolved_base / candidate).resolve()
    if not resolved.is_relative_to(resolved_base):
        raise ScenarioFileError("time_series_csv must stay inside the scenario directory")
    return resolved


def _load_intervals(path: Path) -> tuple[IntervalInput, ...]:
    text = _read_bounded_text(path, _MAX_TIME_SERIES_BYTES)
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None or tuple(reader.fieldnames) != _CSV_COLUMNS:
        raise ScenarioFileError("CSV header must be exactly: " + ",".join(_CSV_COLUMNS))

    intervals: list[IntervalInput] = []
    for line_number, row in enumerate(reader, start=2):
        if len(intervals) >= _MAX_INTERVALS:
            raise ScenarioFileError(f"CSV exceeds the {_MAX_INTERVALS}-row limit")
        try:
            if None in row:
                raise ValueError("row contains more fields than the declared header")
            raw_timestamp = row["timestamp"].strip()
            if raw_timestamp.endswith("Z"):
                raw_timestamp = raw_timestamp[:-1] + "+00:00"
            timestamp = datetime.fromisoformat(raw_timestamp)
            pv_power_kw = float(row["pv_power_kw"])
            price = float(row["market_price_eur_per_mwh"])
            intervals.append(
                IntervalInput(
                    timestamp=timestamp,
                    pv_power_kw=pv_power_kw,
                    market_price_eur_per_mwh=price,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScenarioFileError(f"invalid CSV row {line_number}: {exc}") from exc
    return tuple(intervals)


def load_scenario(path: str | Path) -> tuple[Scenario, FinancialAssumptions]:
    """Load a versioned JSON scenario and its sibling CSV without side effects."""

    scenario_path = Path(path).resolve()
    try:
        payload = json.loads(
            _read_bounded_text(scenario_path, _MAX_SCENARIO_BYTES),
            object_pairs_hook=_unique_json_object,
        )
    except json.JSONDecodeError as exc:
        raise ScenarioFileError(f"invalid scenario JSON: {exc}") from exc
    root = _mapping(payload, "scenario")
    _reject_unknown_keys(root, "scenario", _ROOT_KEYS)
    if root.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioFileError(
            f"schema_version must be {SCHEMA_VERSION!r}; received {root.get('schema_version')!r}"
        )

    dataset_data = _mapping(root.get("dataset"), "dataset")
    battery_data = _mapping(root.get("battery"), "battery")
    grid_data = _mapping(root.get("grid"), "grid")
    financial_data = _mapping(root.get("financial"), "financial")
    _reject_unknown_keys(dataset_data, "dataset", _DATASET_KEYS)
    _reject_unknown_keys(battery_data, "battery", _BATTERY_KEYS)
    _reject_unknown_keys(grid_data, "grid", _GRID_KEYS)
    _reject_unknown_keys(financial_data, "financial", _FINANCIAL_KEYS)
    csv_path = _resolve_companion(scenario_path.parent, _required_string(root, "time_series_csv"))

    try:
        dataset = DatasetMetadata(
            name=_required_string(dataset_data, "name"),
            source=_required_string(dataset_data, "source"),
            license_id=_required_string(dataset_data, "license_id"),
            timezone_name=_required_string(dataset_data, "timezone_name"),
            currency=_required_string(dataset_data, "currency").upper(),
            synthetic=_boolean(dataset_data, "synthetic", True),
        )
        battery = BatteryConfig(
            energy_capacity_kwh=_number(battery_data, "energy_capacity_kwh"),
            max_charge_power_kw=_number(battery_data, "max_charge_power_kw"),
            max_discharge_power_kw=_number(battery_data, "max_discharge_power_kw"),
            minimum_soc_fraction=_number(battery_data, "minimum_soc_fraction", 0.10),
            maximum_soc_fraction=_number(battery_data, "maximum_soc_fraction", 0.90),
            initial_soc_fraction=_number(battery_data, "initial_soc_fraction", 0.50),
            terminal_soc_fraction=_optional_number(battery_data, "terminal_soc_fraction"),
            charge_efficiency=_number(battery_data, "charge_efficiency", 0.95),
            discharge_efficiency=_number(battery_data, "discharge_efficiency", 0.95),
            degradation_cost_eur_per_mwh_dc_discharged=_number(
                battery_data,
                "degradation_cost_eur_per_mwh_dc_discharged",
                0.0,
            ),
        )
        grid = GridConfig(
            export_limit_kw=_number(grid_data, "export_limit_kw"),
            import_limit_kw=_number(grid_data, "import_limit_kw", 0.0),
            allow_grid_charging=_boolean(grid_data, "allow_grid_charging", False),
        )
        financial = FinancialAssumptions(
            capex_eur=_number(financial_data, "capex_eur"),
            annual_fixed_opex_eur=_number(financial_data, "annual_fixed_opex_eur"),
            project_life_years=_integer(financial_data, "project_life_years"),
            discount_rate_fraction=_number(financial_data, "discount_rate_fraction"),
            annualization_factor=_number(financial_data, "annualization_factor", 1.0),
            annual_benefit_degradation_fraction=_number(
                financial_data, "annual_benefit_degradation_fraction", 0.0
            ),
            annual_opex_escalation_fraction=_number(
                financial_data, "annual_opex_escalation_fraction", 0.0
            ),
        )
        scenario = Scenario(
            name=_required_string(root, "name"),
            intervals=_load_intervals(csv_path),
            battery=battery,
            grid=grid,
            dataset=dataset,
        )
    except ValueError as exc:
        if isinstance(exc, ScenarioFileError):
            raise
        raise ScenarioFileError(str(exc)) from exc
    return scenario, financial


def _stage_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".stage.tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def _reserve_backup_path(path: Path) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".backup.tmp",
    )
    os.close(descriptor)
    backup_path = Path(temporary_name)
    backup_path.unlink()
    return backup_path


def _publish_text_pair(artifacts: tuple[tuple[Path, str], ...]) -> None:
    """Stage all artifacts, publish them together, and restore the prior pair on failure."""

    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    published: set[Path] = set()
    try:
        for target, content in artifacts:
            staged[target] = _stage_text(target, content)

        for target, _ in artifacts:
            if target.exists():
                backup = _reserve_backup_path(target)
                target.replace(backup)
                backups[target] = backup

        for target, _ in artifacts:
            staged[target].replace(target)
            published.add(target)
    except Exception as publication_error:
        rollback_errors: list[OSError] = []
        for target in published.difference(backups):
            try:
                target.unlink(missing_ok=True)
            except OSError as exc:
                rollback_errors.append(exc)
        for target, backup in reversed(tuple(backups.items())):
            try:
                backup.replace(target)
            except OSError as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise RuntimeError(
                "result publication failed and rollback was incomplete; "
                "preserve hidden backup files for recovery"
            ) from publication_error
        raise
    else:
        for backup in backups.values():
            with suppress(OSError):
                backup.unlink(missing_ok=True)
    finally:
        for temporary_path in staged.values():
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def write_results(
    output_directory: str | Path,
    dispatch: DispatchResult,
    financial: FinancialResult,
    *,
    force: bool = False,
) -> tuple[Path, Path]:
    """Publish a failure-safe artifact pair, refusing silent overwrite."""

    if financial.dispatch_input_sha256 != dispatch.input_sha256:
        raise ValueError("financial result does not belong to the supplied dispatch result")
    output = Path(output_directory).resolve()
    summary_path = output / "summary.json"
    dispatch_path = output / "dispatch.csv"
    existing_targets = [path for path in (summary_path, dispatch_path) if path.exists()]
    if existing_targets and not force:
        names = ", ".join(path.name for path in existing_targets)
        raise FileExistsError(f"refusing to overwrite {names}; pass --force to replace them")

    output.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "scenario_name": dispatch.scenario_name,
        "dispatch_input_sha256": dispatch.input_sha256,
        "analysis_input_sha256": financial.analysis_input_sha256,
        "schema_version": dispatch.schema_version,
        "model_version": dispatch.model_version,
        "solver": {
            "interface_name": dispatch.solver_interface_name,
            "interface_version": dispatch.solver_interface_version,
            "backend_name": dispatch.solver_backend_name,
            "backend_version": dispatch.solver_backend_version,
            "requested_relative_mip_gap": dispatch.requested_relative_mip_gap,
            "time_limit_seconds_per_phase": dispatch.time_limit_seconds_per_phase,
            "phases": {
                "economic": asdict(dispatch.economic_phase),
                "refinement": asdict(dispatch.refinement_phase),
            },
        },
        "units": {
            "power": "kW AC",
            "stored_energy": "kWh DC",
            "interval_energy": "MWh",
            "market_price": "EUR/MWh",
            "currency": "EUR",
        },
        "dispatch_summary": asdict(dispatch.summary),
        "financial_summary": asdict(financial),
        "limitations": [
            "Results are scenario calculations, not a forecast or engineering certification.",
            "Financial metrics are unlevered and pre-tax.",
            "The model excludes network losses outside the stated battery efficiencies.",
        ],
    }
    summary_content = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"

    fieldnames = [
        "dispatch_input_sha256",
        "analysis_input_sha256",
        "timestamp",
        "interval_hours",
        "pv_power_kw",
        "market_price_eur_per_mwh",
        "pv_export_kw",
        "pv_charge_kw",
        "grid_charge_kw",
        "battery_export_kw",
        "grid_export_kw",
        "curtailed_pv_kw",
        "soc_start_kwh",
        "soc_end_kwh",
        "market_value_eur",
        "degradation_cost_eur",
        "net_operating_value_eur",
    ]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as buffer:
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in dispatch.intervals:
            writer.writerow(
                {
                    "dispatch_input_sha256": dispatch.input_sha256,
                    "analysis_input_sha256": financial.analysis_input_sha256,
                    "timestamp": item.timestamp.isoformat(),
                    "interval_hours": item.interval_hours,
                    "pv_power_kw": item.pv_power_kw,
                    "market_price_eur_per_mwh": item.market_price_eur_per_mwh,
                    "pv_export_kw": item.pv_export_kw,
                    "pv_charge_kw": item.pv_charge_kw,
                    "grid_charge_kw": item.grid_charge_kw,
                    "battery_export_kw": item.battery_export_kw,
                    "grid_export_kw": item.grid_export_kw,
                    "curtailed_pv_kw": item.curtailed_pv_kw,
                    "soc_start_kwh": item.soc_start_kwh,
                    "soc_end_kwh": item.soc_end_kwh,
                    "market_value_eur": item.market_value_eur,
                    "degradation_cost_eur": item.degradation_cost_eur,
                    "net_operating_value_eur": item.net_operating_value_eur,
                }
            )
        buffer.seek(0)
        dispatch_content = buffer.read()
    _publish_text_pair(
        (
            (summary_path, summary_content),
            (dispatch_path, dispatch_content),
        )
    )
    return summary_path, dispatch_path
