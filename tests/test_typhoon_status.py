import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api_status = load_module("api_status", ROOT / "api" / "index.py")
cached_status = load_module("cached_status", ROOT / "scripts" / "update_status.py")
alerts = load_module("alerts", ROOT / "scripts" / "send_alerts.py")


class TyphoonClassificationTests(unittest.TestCase):
    def test_current_in_par_bulletin_is_active(self):
        doc = {"doc_type": "Bulletin", "headline": "TYPHOON OBET REMAINS WITHIN PAR.", "bullets": []}
        self.assertTrue(api_status.document_is_active_in_par(doc))
        self.assertTrue(cached_status.document_is_active_in_par(doc))

    def test_exit_bulletin_is_inactive(self):
        doc = {
            "doc_type": "Bulletin",
            "headline": "TYPHOON SAUDEL HAS EXITED THE PHILIPPINE AREA OF RESPONSIBILITY.",
            "bullets": [],
        }
        self.assertFalse(api_status.document_is_active_in_par(doc))
        self.assertFalse(cached_status.document_is_active_in_par(doc))

    def test_outside_par_advisory_is_not_an_in_par_cyclone(self):
        doc = {
            "doc_type": "Advisory",
            "headline": "TYPHOON SAUDEL IS OUTSIDE THE PHILIPPINE AREA OF RESPONSIBILITY.",
            "bullets": [],
        }
        self.assertFalse(api_status.document_is_active_in_par(doc))
        self.assertFalse(cached_status.document_is_active_in_par(doc))

    def test_missing_bulletin_does_not_fall_back_to_outside_par_advisory(self):
        for module in (api_status, cached_status):
            with patch.object(module, "discover_bulletin_pdf_url", return_value=None), patch.object(
                module, "fetch_and_parse_pdf"
            ) as fetch_pdf:
                self.assertEqual(module.fetch_active_document(), (None, None))
                fetch_pdf.assert_not_called()


class AlertConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 0, 7, tzinfo=timezone.utc)
        self.confirmed = {
            "pagasa_active": True,
            "pagasa_doc_type": "Bulletin",
            "status_scope": "inside_par",
            "last_checked_utc": self.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pagasa_message": "TYPHOON OBET REMAINS WITHIN PAR.",
        }

    def test_fresh_confirmed_bulletin_can_alert(self):
        self.assertTrue(alerts.is_confirmed_active_typhoon(self.confirmed, self.now))

    def test_stale_or_unclassified_status_cannot_alert(self):
        stale = dict(self.confirmed)
        stale["last_checked_utc"] = (self.now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertFalse(alerts.is_confirmed_active_typhoon(stale, self.now))
        legacy = {"pagasa_active": True, "last_checked_utc": self.confirmed["last_checked_utc"]}
        self.assertFalse(alerts.is_confirmed_active_typhoon(legacy, self.now))

    def test_check_typhoon_does_not_send_for_legacy_false_positive(self):
        false_positive = {
            "pagasa_active": True,
            "last_checked_utc": self.confirmed["last_checked_utc"],
            "pagasa_message": "TYPHOON SAUDEL MAINTAINS ITS STRENGTH.",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "data.json"
            data_path.write_text(json.dumps(false_positive))
            with patch.object(alerts, "DATA_PATH", data_path), patch.object(alerts, "notify") as notify:
                state = alerts.check_typhoon({"typhoon_alerted_date": ""})
        notify.assert_not_called()
        self.assertEqual(state["typhoon_alerted_date"], "")

    def test_typhoon_only_mode_does_not_touch_rain_or_flood_checks(self):
        current_status = dict(self.confirmed)
        current_status["last_checked_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "data.json"
            state_path = Path(temp_dir) / "alert_state.json"
            data_path.write_text(json.dumps(current_status))
            state_path.write_text(json.dumps({"typhoon_alerted_date": ""}))
            with patch.object(alerts, "DATA_PATH", data_path), patch.object(
                alerts, "STATE_PATH", state_path
            ), patch.object(alerts, "notify") as notify, patch.object(
                alerts, "check_rain"
            ) as check_rain, patch.object(
                alerts, "check_flood_advisories"
            ) as check_flood_advisories, patch.object(
                alerts, "check_flood_risk"
            ) as check_flood_risk:
                result = alerts.main(["--checks", "typhoon"])

            saved_state = json.loads(state_path.read_text())

        self.assertEqual(result, 0)
        notify.assert_called_once()
        check_rain.assert_not_called()
        check_flood_advisories.assert_not_called()
        check_flood_risk.assert_not_called()
        self.assertEqual(saved_state["typhoon_alerted_date"], alerts.manila_today())

    def test_workflow_runs_typhoon_alert_before_flood_advisory_fetch(self):
        workflow = (ROOT / ".github" / "workflows" / "update.yml").read_text()
        typhoon_step = workflow.index("python3 scripts/send_alerts.py --checks typhoon")
        flood_fetch_step = workflow.index("python3 scripts/update_flood_advisories.py")
        self.assertLess(typhoon_step, flood_fetch_step)


if __name__ == "__main__":
    unittest.main()
