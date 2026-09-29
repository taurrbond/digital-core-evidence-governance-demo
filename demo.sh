#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
python3 -m unittest discover -s tests -v
python3 run_demo.py --fixture fixtures/synthetic_control_plane.xlsx --report evidence/demo_report.json
