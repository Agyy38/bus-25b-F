"""合成資料僅用於測試，並非採集證據。"""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from validate import validate, render


def record(second=0, direction=0, buses=None):
    buses = buses if buses is not None else [{"busPlate": "AB1234", "speed": "10", "passengerFlow": -1}]
    return {"recv_at": f"2026-10-03T10:{second // 60:02}:{second % 60:02}",
            "url": "https://example.invalid/macauweb/routestation/bus",
            "reqBody": f"dir={direction}",
            "resp": json.dumps({"header": {"status": "000"}, "data": {
                "routeInfo": [{"staCode": "M1/2", "busInfo": buses}]}})}


class ValidatorTests(unittest.TestCase):
    def check(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as f:
                for row in rows:
                    f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")
            return validate([path])

    def test_normal_both_directions(self):
        result = self.check([record(0, 0), record(10, 0), record(0, 1)])
        self.assertEqual(result["issues"], {})
        self.assertEqual(result["fields"]["vehicle_observations"], 3)

    def test_broken_json_does_not_stop(self):
        result = self.check(["{broken", record(), record(direction=1)])
        self.assertEqual(result["issues"]["outer_json_invalid"], 1)
        self.assertEqual(result["fields"]["vehicle_observations"], 2)

    def test_missing_required(self):
        self.assertEqual(self.check([{}])["issues"]["required_field_missing"], 1)

    def test_flow_string_is_supported_but_bool_is_not(self):
        buses = [{"busPlate": f"AB{i:04}", "speed": "1", "passengerFlow": flow}
                 for i, flow in enumerate(["-1", "5", True, "6"])]
        result = self.check([record(buses=buses)])
        self.assertEqual(result["fields"]["passenger_flow_string"], 2)
        self.assertEqual(result["fields"]["passenger_flow_no_reading"], 1)
        self.assertEqual(result["issues"]["passenger_flow_invalid"], 2)

    def test_gap_is_direction_specific_and_sorted(self):
        rows = [record(240), record(0)] + [record(t, 1) for t in range(0, 241, 10)]
        result = self.check(rows)
        self.assertEqual(result["issues"]["sampling_gap"], 1)
        self.assertIn("dir=0", result["examples"]["sampling_gap"][0])

    def test_duplicate_snapshot_but_not_repeated_content_later(self):
        result = self.check([record(), record(), record(10), record(direction=1)])
        self.assertEqual(result["issues"]["duplicate_snapshot"], 1)
        self.assertEqual(result["fields"]["vehicle_observations"], 3)

    def test_vehicle_conflict(self):
        row = record()
        payload = json.loads(row["resp"])
        stop = copy.deepcopy(payload["data"]["routeInfo"][0])
        stop["staCode"] = "M2"
        payload["data"]["routeInfo"].append(stop)
        row["resp"] = json.dumps(payload)
        self.assertEqual(self.check([row])["issues"]["vehicle_station_conflict"], 1)

    def test_speed_categories(self):
        buses = [{"busPlate": f"AB{i:04}", "passengerFlow": -1, **extra}
                 for i, extra in enumerate([{"speed": ""}, {}, {"speed": "0"}, {"speed": "abc"}])]
        result = self.check([record(buses=buses)])
        for key in ("speed_missing", "speed_format_invalid"):
            self.assertEqual(result["issues"][key], 1)
        for key in ("speed_empty_ambiguous", "speed_zero"):
            self.assertEqual(result["fields"][key], 1)

    def test_missing_direction_never_defaults_to_zero(self):
        row = record(); row["reqBody"] = "routeName=25B"
        self.assertEqual(self.check([row])["issues"]["direction_unknown_or_conflicting"], 1)

    def test_conflicting_direction(self):
        row = record(); row["url"] += "?direction=1"
        self.assertEqual(self.check([row])["issues"]["direction_unknown_or_conflicting"], 1)

    def test_api_failure_not_valid_coverage(self):
        row = record(); row["resp"] = '{"header":{"status":"1000"},"data":""}'
        result = self.check([row])
        self.assertEqual(result["issues"]["api_status_failure"], 1)
        self.assertEqual(result["streams"], [])

    def test_bad_inner_json(self):
        row = record(); row["resp"] = "broken"
        self.assertEqual(self.check([row])["issues"]["response_json_invalid"], 1)

    def test_no_bus_distinct_from_bad_schema(self):
        result = self.check([record(buses=[])])
        self.assertEqual(result["fields"]["no_bus_snapshots"], 1)
        self.assertNotIn("response_schema_invalid", result["issues"])

    def test_timezone_equivalence(self):
        row = record(); row["recv_at"] = "2026-10-03T02:00:00+00:00"
        self.assertEqual(self.check([record(), row])["issues"]["duplicate_snapshot"], 1)

    def test_missing_file_and_empty_input(self):
        with tempfile.TemporaryDirectory() as folder:
            result = validate([Path(folder) / "missing.gz"])
        self.assertIn("file_read_error", result["issues"])
        self.assertIn("empty_input", result["issues"])

    def test_report_contains_evidence_not_plate(self):
        report = render(self.check([record(), record()]))
        self.assertIn("synthetic.jsonl.gz:2", report)
        self.assertNotIn("AB1234", report)


if __name__ == "__main__":
    unittest.main()
