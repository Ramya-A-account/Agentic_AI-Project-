import json
import unittest

from agentcare.api.routes import normalize_report_payload


class NormalizeReportPayloadTests(unittest.TestCase):
    def test_normalize_report_payload_accepts_json_string(self):
        raw = json.dumps({
            "report_date": "2026-09-29",
            "executive_summary": "Everything is stable.",
            "kpi_summary": {"BED_OCCUPANCY": {"average": 82.5, "minimum": 70.0, "maximum": 90.0, "observations": 2}},
            "incident_summary": {"total": 1, "critical": 1, "warning": 0, "incidents": [{"kpi_name": "BED_OCCUPANCY"}]},
            "recommendation_summary": {"total": 2, "high_priority": 1, "recommendations": [{"priority": "HIGH"}]},
            "manager_action_summary": {"total": 1, "actions": [{"action_type": "RESOLVE"}]},
            "departments": [{"name": "Emergency", "total_beds": 30, "total_icu_beds": 0}],
        })

        normalized = normalize_report_payload(raw)

        self.assertEqual(normalized["report_date"], "2026-09-29")
        self.assertEqual(normalized["kpi_summary"]["BED_OCCUPANCY"]["average"], 82.5)
        self.assertEqual(normalized["incident_summary"]["total"], 1)
        self.assertEqual(normalized["recommendation_summary"]["total"], 2)
        self.assertEqual(normalized["manager_action_summary"]["total"], 1)

    def test_normalize_report_payload_populates_missing_sections(self):
        normalized = normalize_report_payload({})

        self.assertEqual(normalized["kpi_summary"], {})
        self.assertEqual(normalized["incident_summary"]["total"], 0)
        self.assertEqual(normalized["incident_summary"]["incidents"], [])
        self.assertEqual(normalized["recommendation_summary"]["total"], 0)
        self.assertEqual(normalized["recommendation_summary"]["recommendations"], [])
        self.assertEqual(normalized["manager_action_summary"]["total"], 0)
        self.assertEqual(normalized["manager_action_summary"]["actions"], [])
        self.assertEqual(normalized["departments"], [])


if __name__ == "__main__":
    unittest.main()
