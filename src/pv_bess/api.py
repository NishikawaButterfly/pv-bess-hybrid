"""Optional HTTP transport around the unchanged calculation kernel."""

from __future__ import annotations

import json
import mimetypes
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Any

import scipy
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pv_bess.dispatch import DispatchOptimizationError, _highs_backend_version, optimize_dispatch
from pv_bess.finance import evaluate_financials
from pv_bess.io import (
    _MAX_SCENARIO_BYTES,
    _MAX_TIME_SERIES_BYTES,
    ScenarioFileError,
    load_scenario,
    write_results,
)
from pv_bess.models import MODEL_VERSION, SCHEMA_VERSION, IntervalDispatch

_READ_CHUNK_BYTES = 65_536
_FALLBACK_TIME_SERIES_NAME = "time_series.csv"
_WEB_DIRECTORY = Path(__file__).resolve().parents[2] / "web"

# Windows can map .js and .css to other types through the registry, and the
# browser then refuses to apply them. Pin the types the bundled page uses.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")


def _package_version() -> str:
    """Best-effort distribution version; source checkouts may lack metadata."""

    try:
        return metadata.version("pv-bess-hybrid")
    except metadata.PackageNotFoundError:
        return "unknown"


def _read_bounded_upload(upload: UploadFile, name: str, maximum_bytes: int) -> bytes:
    """Read one upload completely while enforcing the kernel's byte limit."""

    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = upload.file.read(_READ_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        received += len(chunk)
        if received > maximum_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"{name} exceeds the {maximum_bytes}-byte limit",
            )
        chunks.append(chunk)


def _staged_time_series_path(base_directory: Path, scenario_bytes: bytes) -> Path:
    """Return where the uploaded CSV must be staged for ``load_scenario``.

    The scenario's declared ``time_series_csv`` name is honored when it is a safe
    relative path. Otherwise a placeholder name keeps staging total so that
    ``load_scenario`` reports the original defect exactly as the CLI would.
    """

    fallback = base_directory / _FALLBACK_TIME_SERIES_NAME
    try:
        payload = json.loads(scenario_bytes.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        return fallback
    if not isinstance(payload, dict):
        return fallback
    declared = payload.get("time_series_csv")
    if not isinstance(declared, str) or not declared.strip():
        return fallback
    candidate = Path(declared.strip())
    if candidate.is_absolute():
        return fallback
    resolved_base = base_directory.resolve()
    resolved = (resolved_base / candidate).resolve()
    if not resolved.is_relative_to(resolved_base):
        return fallback
    return resolved


def _scenario_error_status_code(error: ScenarioFileError) -> int:
    """Map malformed files to 400 and well-formed files with bad values to 422.

    ``load_scenario`` wraps domain ``ValueError`` messages verbatim, so a wrapped
    plain ``ValueError`` carrying an identical message marks a value problem;
    every other failure is a defective file.
    """

    cause = error.__cause__
    if type(cause) is ValueError and str(cause) == str(error):
        return 422
    return 400


def _interval_payload(item: IntervalDispatch) -> dict[str, Any]:
    """One interval in dispatch.csv column order, without the per-row hashes."""

    return {
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


def _run_uploaded_scenario(scenario_bytes: bytes, time_series_bytes: bytes) -> dict[str, Any]:
    """Stage the uploads, run the CLI's exact pipeline, and return its summary.

    The CLI splits its output between summary.json and dispatch.csv; the web page
    needs both, so the per-interval series is added under ``dispatch_intervals``.
    """

    with (
        tempfile.TemporaryDirectory() as staging_directory,
        tempfile.TemporaryDirectory() as results_directory,
    ):
        base = Path(staging_directory)
        time_series_path = _staged_time_series_path(base, scenario_bytes)
        time_series_path.parent.mkdir(parents=True, exist_ok=True)
        time_series_path.write_bytes(time_series_bytes)
        scenario_path = base / "scenario.json"
        scenario_path.write_bytes(scenario_bytes)

        scenario, financial_assumptions = load_scenario(scenario_path)
        dispatch = optimize_dispatch(scenario)
        financial = evaluate_financials(dispatch, scenario, financial_assumptions)
        summary_path, _ = write_results(results_directory, dispatch, financial)
        payload: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
        payload["dispatch_intervals"] = [_interval_payload(item) for item in dispatch.intervals]
        return payload


def create_app() -> FastAPI:
    """Build the FastAPI application; every calculation stays in the kernel."""

    application = FastAPI(title="pv-bess-hybrid API", version=_package_version())

    @application.get("/health")
    def health() -> dict[str, str | None]:
        return {
            "status": "ok",
            "kernel_version": _package_version(),
            "schema_version": SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "solver_interface_name": "scipy.optimize.milp",
            "solver_interface_version": scipy.__version__,
            "solver_backend_name": "HiGHS",
            "solver_backend_version": _highs_backend_version(),
        }

    @application.post("/api/v1/dispatch")
    def run_dispatch(scenario: UploadFile, time_series: UploadFile) -> dict[str, Any]:
        scenario_bytes = _read_bounded_upload(scenario, "scenario", _MAX_SCENARIO_BYTES)
        time_series_bytes = _read_bounded_upload(time_series, "time_series", _MAX_TIME_SERIES_BYTES)
        try:
            return _run_uploaded_scenario(scenario_bytes, time_series_bytes)
        except ScenarioFileError as exc:
            raise HTTPException(
                status_code=_scenario_error_status_code(exc), detail=str(exc)
            ) from exc
        except (DispatchOptimizationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @application.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # Registered after the API routes, so /health, /api/v1, and /docs keep
    # priority. Installed wheels ship without web/, and the API stays complete
    # without it.
    if _WEB_DIRECTORY.is_dir():
        application.mount("/", StaticFiles(directory=_WEB_DIRECTORY, html=True), name="web")

    return application


app = create_app()
