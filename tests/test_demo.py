from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from digital_core_demo import run_fixture


class DigitalCoreDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ROOT / "fixtures" / "synthetic_control_plane.xlsx"
        cls.report = run_fixture(cls.fixture)

    def test_validation_is_clean(self):
        self.assertEqual(self.report["validation_summary"], {"ERROR": 0, "WARN": 0})

    def test_expected_normalized_counts(self):
        self.assertEqual(self.report["normalized_counts"], {
            "sources": 3,
            "facts": 3,
            "money_ledger": 2,
            "conflicts": 2,
            "actions": 4,
            "permission_snapshots": 3,
        })

    def test_governance_gate_17_of_17(self):
        gate = self.report["governance_gate"]
        self.assertEqual(gate["status"], "PASS_DEMO_ONLY")
        self.assertEqual(gate["tests_passed"], 17)
        self.assertEqual(gate["tests_failed"], 0)
        self.assertFalse(gate["external_execution_allowed"])

    def test_no_external_side_effects(self):
        self.assertEqual(self.report["side_effects"], {
            "network": False,
            "database": False,
            "external_writes": False,
            "local_report_only": True,
        })

    def test_report_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "report.json"
            out.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
            loaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(loaded["version"], "0.1")
            self.assertEqual(len(loaded["fixture_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
