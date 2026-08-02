from __future__ import annotations

import json
import unittest
from importlib.util import find_spec
from pathlib import Path

from pv_bess.models import MODEL_VERSION, SCHEMA_VERSION


def _api_test_stack_available() -> bool:
    if any(find_spec(name) is None for name in ("fastapi", "httpx")):
        return False
    return any(find_spec(name) is not None for name in ("python_multipart", "multipart"))


_API_STACK_AVAILABLE = _api_test_stack_available()

if _API_STACK_AVAILABLE:
    from fastapi.testclient import TestClient

    from pv_bess.api import create_app


@unittest.skipUnless(_API_STACK_AVAILABLE, "the optional API dependencies are not installed")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample = Path(__file__).resolve().parents[1] / "sample-data" / "scenario.json"
        cls.client = TestClient(create_app())

    def _files(
        self,
        scenario_bytes: bytes | None = None,
        time_series_bytes: bytes | None = None,
    ) -> dict[str, tuple[str, bytes, str]]:
        if scenario_bytes is None:
            scenario_bytes = self.sample.read_bytes()
        if time_series_bytes is None:
            time_series_bytes = self.sample.with_name("hourly.csv").read_bytes()
        return {
            "scenario": ("scenario.json", scenario_bytes, "application/json"),
            "time_series": ("hourly.csv", time_series_bytes, "text/csv"),
        }

    def test_health_reports_kernel_and_solver_versions(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(payload["model_version"], MODEL_VERSION)
        self.assertEqual(payload["solver_interface_name"], "scipy.optimize.milp")
        self.assertRegex(payload["solver_interface_version"], r"^\d+\.\d+")
        self.assertEqual(payload["solver_backend_name"], "HiGHS")

    def test_dispatch_returns_the_summary_the_cli_writes(self) -> None:
        response = self.client.post("/api/v1/dispatch", files=self._files())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["dispatch_input_sha256"],
            "76d3d912a674c9b8b6ef8bc8df9e423ed5f544830fe97a3058ef1939d769b491",
        )
        self.assertEqual(
            payload["analysis_input_sha256"],
            "c8c1af3b4a7d5d2cbac5a49eb312c88ff09a2d54084bbecffa354415e97cdab8",
        )
        self.assertEqual(payload["solver"]["phases"]["economic"]["status"], "optimal")
        self.assertEqual(payload["solver"]["phases"]["refinement"]["status"], "optimal")
        self.assertAlmostEqual(payload["dispatch_summary"]["pv_energy_mwh"], 40.2)
        self.assertAlmostEqual(payload["dispatch_summary"]["equivalent_full_cycles"], 0.45)
        self.assertAlmostEqual(payload["financial_summary"]["npv_eur"], -3_818_737.07961859)
        self.assertAlmostEqual(payload["financial_summary"]["lcos_eur_per_mwh"], 265.9735362230494)

    def test_dispatch_includes_the_interval_series_for_charting(self) -> None:
        response = self.client.post("/api/v1/dispatch", files=self._files())
        self.assertEqual(response.status_code, 200)
        intervals = response.json()["dispatch_intervals"]
        self.assertEqual(len(intervals), 24)
        first = intervals[0]
        self.assertEqual(first["timestamp"], "2026-06-15T00:00:00+00:00")
        self.assertEqual(first["interval_hours"], 1.0)
        self.assertEqual(first["pv_power_kw"], 0.0)
        self.assertEqual(first["market_price_eur_per_mwh"], 45.0)
        for key in (
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
        ):
            self.assertIn(key, first)
        for item in intervals:
            self.assertAlmostEqual(
                item["grid_export_kw"], item["pv_export_kw"] + item["battery_export_kw"]
            )

    def test_defective_files_are_rejected_with_400(self) -> None:
        escaping = json.loads(self.sample.read_text(encoding="utf-8"))
        escaping["time_series_csv"] = "../outside.csv"
        header = b"timestamp,pv_power_kw,market_price_eur_per_mwh\n"
        cases = (
            ("malformed scenario JSON", b"{", None, "invalid scenario JSON"),
            (
                "escaping time series path",
                json.dumps(escaping).encode("utf-8"),
                None,
                "stay inside",
            ),
            ("wrong CSV header", None, b"a,b,c\n1,2,3\n", "header must be exactly"),
            ("invalid CSV row", None, header + b"not-a-timestamp,0,10\n", "invalid CSV row 2"),
        )
        for label, scenario_bytes, time_series_bytes, message in cases:
            with self.subTest(label):
                response = self.client.post(
                    "/api/v1/dispatch",
                    files=self._files(scenario_bytes, time_series_bytes),
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["detail"])

    def test_bad_scenario_value_is_rejected_with_422(self) -> None:
        payload = json.loads(self.sample.read_text(encoding="utf-8"))
        payload["battery"]["minimum_soc_fraction"] = 0.99
        response = self.client.post(
            "/api/v1/dispatch",
            files=self._files(json.dumps(payload).encode("utf-8")),
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("minimum_soc_fraction", response.json()["detail"])

    def test_oversized_scenario_upload_is_rejected_with_413(self) -> None:
        response = self.client.post(
            "/api/v1/dispatch",
            files=self._files(scenario_bytes=b"x" * 1_000_001),
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("exceeds", response.json()["detail"])

    def test_missing_upload_is_rejected_with_422(self) -> None:
        files = self._files()
        del files["time_series"]
        response = self.client.post("/api/v1/dispatch", files=files)
        self.assertEqual(response.status_code, 422)


@unittest.skipUnless(_API_STACK_AVAILABLE, "the optional API dependencies are not installed")
class WebPageTests(unittest.TestCase):
    """The bundled static page rides on the API app without shadowing it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(create_app())

    def test_root_serves_the_dispatch_page(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("PV-BESS dispatch explorer", response.text)
        self.assertIn("app.js", response.text)

    def test_static_assets_are_served_with_usable_types(self) -> None:
        for path, expected_type, marker in (
            ("/app.js", "javascript", "/api/v1/dispatch"),
            ("/styles.css", "text/css", ".chart-svg"),
            ("/favicon.svg", "image/svg+xml", "<svg"),
        ):
            with self.subTest(path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_type, response.headers["content-type"])
                self.assertIn(marker, response.text)

    def test_static_mount_does_not_shadow_health_or_the_api(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        # A bare POST must reach FastAPI's upload validation (422 with details),
        # not the static file tree (405 without them).
        dispatch = self.client.post("/api/v1/dispatch")
        self.assertEqual(dispatch.status_code, 422)
        self.assertIn("detail", dispatch.json())

    def test_unknown_path_is_a_plain_404(self) -> None:
        response = self.client.get("/no-such-page")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
