#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from digital_core_demo import run_fixture


def main() -> int:
    p = argparse.ArgumentParser(description="Run the local Digital Core Evidence Governance demo")
    p.add_argument("--fixture", default=str(ROOT / "fixtures" / "synthetic_control_plane.xlsx"))
    p.add_argument("--report", default=str(ROOT / "evidence" / "demo_report.json"))
    args = p.parse_args()

    fixture = Path(args.fixture)
    if not fixture.is_absolute():
        fixture = ROOT / fixture
    report = run_fixture(fixture)
    out = Path(args.report)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "status": report["governance_gate"]["status"],
        "tests": f"{report['governance_gate']['tests_passed']}/{report['governance_gate']['tests_total']}",
        "validation": report["validation_summary"],
        "report": str(out.relative_to(ROOT)),
        "external_side_effects": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["governance_gate"]["status"] == "PASS_DEMO_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
