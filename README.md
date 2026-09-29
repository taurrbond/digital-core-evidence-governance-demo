# Digital Core Evidence Governance Demo v0.1

[![CI](https://github.com/taurrbond/digital-core-evidence-governance-demo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/taurrbond/digital-core-evidence-governance-demo/actions/workflows/ci.yml)

Minimal, local-only portfolio demonstrator derived from confirmed Digital Core source patterns.

## What it demonstrates

- dependency-free XLSX ingestion;
- lossless staging with per-row SHA-256;
- normalization of sources, facts/money, conflicts, actions, and permission snapshots;
- GRC validation of source authority (L1-L5) and evidence confidence (A-E);
- human/execution safety gates;
- deterministic 17-check governance gate;
- JSON audit evidence;
- no network, database, or external writes.

The fixture is fully synthetic. It contains no real people, employers, accounts, email addresses, Drive IDs, legal cases, medical records, debts, or production secrets.

## Requirements

- Python 3.10+
- Bash
- No third-party Python packages

Verified during the publication audit with Python 3.13.5.

## One-command demo

```bash
./demo.sh
```

Expected end state:

- Python unit tests: PASS
- governance gate: `PASS_DEMO_ONLY`
- 17/17 gate checks PASS
- validation: 0 ERROR / 0 WARN
- report written to `evidence/demo_report.json`
- `external_side_effects: false`

## Pipeline

```text
synthetic_control_plane.xlsx
        ↓
lossless staging
        ↓
normalization
        ↓
validation
        ↓
governance gate
        ↓
JSON audit report
```

## Safety boundary

This demo deliberately does **not** connect to PostgreSQL, Supabase, Gmail, Google Drive, GitHub, or any external API. `EXTERNAL_EXECUTION` exists only as a policy state in the synthetic fixture; no fixture action is authorized for execution.

## Portfolio positioning

**Cyber GRC:** evidence provenance, conflicting claims, permission snapshots, human approval gates, fail-closed execution policy, audit evidence.

**Python Automation:** XLSX parsing, normalization, deterministic validation, SHA-256 integrity, automated tests, reproducible JSON reporting.
