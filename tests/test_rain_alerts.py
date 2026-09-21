import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
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
    def timing(self, probabilities, amounts=None, hour=10, minute=30):
        hourly = {
            "time": [f"2026-09-21T{h:02d}:00" for h in range(10, 16)],
            "precipitation_probability": probabilities,
            "precipitation": amounts or [0] * 6,
        }
        now = datetime(2026, 9, 21, hour, minute, tzinfo=alerts.ZoneInfo("Asia/Manila"))
        return alerts.rain_timing_text(hourly, now)

    def test_next_window_uses_preceding_hour_and_merges_adjacent_hours(self):
        text = self.timing([90, 0, 0, 70, 80, 0])
        self.assertIn("12:00 PM–2:00 PM PHT", text)

    def test_current_window_is_forecast_not_observed_rain(self):
        self.assertIn("possible now through 11:00 AM", self.timing([0, 70, 0, 0, 0, 0]))

    def test_rain_amount_can_identify_window(self):
        self.assertIn("12:00 PM–1:00 PM", self.timing([0] * 6, [0, 0, 0, 0.2, 0, 0]))

    def test_past_rain_is_not_presented_as_upcoming(self):
        self.assertIn("no clear rain window", self.timing([90, 0, 0, 0, 0, 0]))

    def test_missing_data_does_not_claim_dry_weather(self):
        with self.assertRaises(ValueError):
            self.timing([None] * 6)
        with self.assertRaises(ValueError):
            alerts.rain_timing_text({})

    def test_hourly_outage_keeps_daily_alert(self):
        with patch.object(alerts, "fetch_rain_forecast", return_value={
            "date": alerts.manila_today(), "probability": 90, "mm": 12,
        }), patch.object(alerts.urllib.request, "urlopen", side_effect=OSError("offline")), patch.object(
            alerts, "notify"
        ) as notify:
            state = alerts.check_rain({})
        self.assertIn("Estimated rain time unavailable", notify.call_args.args[0])
        self.assertEqual(state["rain_alerted_date"], alerts.manila_today())

    def test_already_alerted_does_not_fetch_timing_or_notify(self):
        with patch.object(alerts, "fetch_rain_timing") as timing, patch.object(alerts, "notify") as notify:
            alerts.check_rain({"rain_alerted_date": alerts.manila_today()})
        timing.assert_not_called()
        notify.assert_not_called()

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
