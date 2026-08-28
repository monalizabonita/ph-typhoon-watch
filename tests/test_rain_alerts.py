import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


alerts = load_module("rain_alerts", ROOT / "scripts" / "send_alerts.py")


class RainAlertTests(unittest.TestCase):
    def test_current_cached_taguig_forecast_is_reused(self):
        today = alerts.manila_today()
        snapshot = {
            "areas": [{
                "name": "Taguig",
                "date": today,
                "rain_probability": 98,
                "rain_mm": 22.8,
            }]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "flood_risk.json"
            path.write_text(json.dumps(snapshot))
            with patch.object(alerts, "FLOOD_RISK_PATH", path), patch.object(
                alerts.urllib.request, "urlopen"
            ) as urlopen:
                forecast = alerts.fetch_rain_forecast()

        urlopen.assert_not_called()
        self.assertEqual(forecast, {"date": today, "probability": 98.0, "mm": 22.8})

    def test_unavailable_forecast_fails_after_bounded_retries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"
            with patch.object(alerts, "FLOOD_RISK_PATH", missing_path), patch.object(
                alerts.urllib.request, "urlopen", side_effect=OSError("TLS timeout")
            ) as urlopen, patch.object(alerts.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "unavailable after 3 attempts"):
                    alerts.fetch_rain_forecast()

        self.assertEqual(urlopen.call_count, 3)

    def test_failed_rain_evaluation_is_not_silently_ignored(self):
        with patch.object(alerts, "fetch_rain_forecast", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Rain alert evaluation failed"):
                alerts.check_rain({"rain_alerted_date": ""})


if __name__ == "__main__":
    unittest.main()
