#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import itertools
import json
import re
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

REQUIRED_SHEETS = {
    "01_Sources",
    "03_Facts_Money",
    "04_Conflicts",
    "05_Actions",
    "13_Permission_Snapshot",
}
VALID_L = {"L1", "L2", "L3", "L4", "L5"}
VALID_CONF = {"A", "B", "C", "D", "E"}
VALID_STATES = {"VERIFY", "READY", "NEW", "APPROVAL_REQUIRED", "HOLD", "BLOCKED", "DONE", "NOT_APPLICABLE"}
VALID_SCOPES = {"NONE", "REVIEW_ONLY", "EVIDENCE_ACQUISITION", "PREPARE", "EXTERNAL_EXECUTION"}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "1", "yes"}:
        return True
    if s in {"false", "0", "no", "", "none"}:
        return False
    raise ValueError(f"Unsupported boolean value: {value!r}")


def col_letters(cell_ref: str) -> str:
    m = re.match(r"([A-Z]+)", cell_ref)
    return m.group(1) if m else cell_ref


class XLSXReader:
    """Dependency-free XLSX value reader adapted from the confirmed Digital Core importer."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.zf = zipfile.ZipFile(self.path, "r")
        self.shared_strings = self._load_shared_strings()
        self.sheet_targets = self._load_sheet_targets()

    def close(self) -> None:
        self.zf.close()

    def _xml(self, member: str) -> ET.Element:
        with self.zf.open(member) as fh:
            return ET.parse(fh).getroot()

    def _load_shared_strings(self) -> list[str]:
        member = "xl/sharedStrings.xml"
        if member not in self.zf.namelist():
            return []
        root = self._xml(member)
        out = []
        for si in root.findall(f"{{{MAIN_NS}}}si"):
            texts = [t.text or "" for t in si.iter(f"{{{MAIN_NS}}}t")]
            out.append("".join(texts))
        return out

    def _load_sheet_targets(self) -> dict[str, str]:
        wb_root = self._xml("xl/workbook.xml")
        rel_root = self._xml("xl/_rels/workbook.xml.rels")
        rels = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        targets: dict[str, str] = {}
        sheets = wb_root.find(f"{{{MAIN_NS}}}sheets")
        if sheets is None:
            return targets
        for sheet in sheets.findall(f"{{{MAIN_NS}}}sheet"):
            name = sheet.attrib["name"]
            rid = sheet.attrib[f"{{{REL_NS}}}id"]
            target = rels[rid].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            targets[name] = target
        return targets

    @property
    def sheet_names(self) -> list[str]:
        return list(self.sheet_targets)

    def _cell_value(self, c: ET.Element) -> Any:
        t = c.attrib.get("t")
        if t == "inlineStr":
            is_el = c.find(f"{{{MAIN_NS}}}is")
            if is_el is None:
                return None
            return "".join((node.text or "") for node in is_el.iter(f"{{{MAIN_NS}}}t"))
        v = c.find(f"{{{MAIN_NS}}}v")
        if v is None or v.text is None:
            return None
        raw = v.text
        if t == "s":
            idx = int(raw)
            return self.shared_strings[idx] if idx < len(self.shared_strings) else raw
        if t == "b":
            return raw == "1"
        if t in {"str", "e"}:
            return raw
        try:
            num = float(raw)
            return int(num) if num.is_integer() else num
        except ValueError:
            return raw

    def rows(self, sheet_name: str) -> list[tuple[int, dict[str, Any]]]:
        root = self._xml(self.sheet_targets[sheet_name])
        sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
        if sheet_data is None:
            return []
        out: list[tuple[int, dict[str, Any]]] = []
        for row in sheet_data.findall(f"{{{MAIN_NS}}}row"):
            row_no = int(row.attrib.get("r", "0"))
            cells: dict[str, Any] = {}
            for c in row.findall(f"{{{MAIN_NS}}}c"):
                ref = c.attrib.get("r", "")
                cells[col_letters(ref)] = self._cell_value(c)
            if any(clean(v) is not None for v in cells.values()):
                out.append((row_no, cells))
        return out

    def table_records(self, sheet_name: str, header_row: int = 1) -> list[dict[str, Any]]:
        rows = self.rows(sheet_name)
        by_row = dict(rows)
        header_cells = by_row.get(header_row, {})
        headers = {letter: clean(value) for letter, value in header_cells.items() if clean(value)}
        records: list[dict[str, Any]] = []
        for row_no, cells in rows:
            if row_no <= header_row:
                continue
            record = {header: cells.get(letter) for letter, header in headers.items()}
            if any(clean(v) is not None for v in record.values()):
                records.append(record)
        return records


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str


class DigitalCoreEvidenceDemo:
    def __init__(self, fixture: Path):
        self.fixture = Path(fixture)
        self.reader = XLSXReader(self.fixture)
        self.raw_rows: list[dict[str, Any]] = []
        self.normalized: dict[str, list[dict[str, Any]]] = {
            "sources": [],
            "facts": [],
            "money_ledger": [],
            "conflicts": [],
            "actions": [],
            "permission_snapshots": [],
        }
        self.issues: list[ValidationIssue] = []

    def close(self) -> None:
        self.reader.close()

    def stage(self) -> None:
        for sheet in self.reader.sheet_names:
            for row_no, cells in self.reader.rows(sheet):
                payload = {"sheet": sheet, "row_no": row_no, "cells": cells}
                raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                self.raw_rows.append({
                    "sheet": sheet,
                    "row_no": row_no,
                    "cells": cells,
                    "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                })

    def normalize(self) -> None:
        for r in self.reader.table_records("01_Sources"):
            self.normalized["sources"].append({
                "source_id": clean(r.get("Source_ID")),
                "source_name": clean(r.get("Source")),
                "account_id": clean(r.get("Account_ID")),
                "provider_id": clean(r.get("Provider_ID")),
                "owner_scope": clean(r.get("Owner_Scope")),
                "source_authority_l": clean(r.get("Source_Authority_L")),
                "evidence_confidence": clean(r.get("Evidence_Confidence")),
                "freshness_status": clean(r.get("Freshness_Status")),
                "status": clean(r.get("Status")),
                "last_verified_at": clean(r.get("Last_Verified_At")),
            })

        for r in self.reader.table_records("03_Facts_Money"):
            fact = {
                "record_id": clean(r.get("Record_ID")),
                "record_type": clean(r.get("Record_Type")),
                "statement": clean(r.get("Statement")),
                "source_id": clean(r.get("Source_ID")),
                "source_authority_l": clean(r.get("Source_Authority_L")),
                "evidence_confidence": clean(r.get("Evidence_Confidence")),
                "verification": clean(r.get("Verification")),
            }
            self.normalized["facts"].append(fact)
            if fact["record_type"] == "MONEY":
                self.normalized["money_ledger"].append({
                    "record_id": fact["record_id"],
                    "amount": r.get("Amount"),
                    "currency": clean(r.get("Currency")),
                    "source_id": fact["source_id"],
                })

        for r in self.reader.table_records("04_Conflicts"):
            self.normalized["conflicts"].append({
                "conflict_id": clean(r.get("Conflict_ID")),
                "claim_a": clean(r.get("Claim_A")),
                "claim_b": clean(r.get("Claim_B")),
                "claim_a_l": clean(r.get("Claim_A_L")),
                "claim_a_confidence": clean(r.get("Claim_A_Confidence")),
                "claim_b_l": clean(r.get("Claim_B_L")),
                "claim_b_confidence": clean(r.get("Claim_B_Confidence")),
                "resolution_status": clean(r.get("Resolution_Status")),
                "ai_policy": clean(r.get("AI_Policy")),
            })

        for r in self.reader.table_records("05_Actions"):
            self.normalized["actions"].append({
                "action_id": clean(r.get("Action_ID")),
                "action": clean(r.get("Action")),
                "priority": clean(r.get("Priority")),
                "action_state": clean(r.get("Action_State")),
                "execution_scope": clean(r.get("Execution_Scope")),
                "authorized": bool_value(r.get("Authorized")),
                "execution_mode": clean(r.get("Execution_Mode")),
                "evidence_required": clean(r.get("Evidence_Required")),
                "done_definition": clean(r.get("Done_Definition")),
            })

        for r in self.reader.table_records("13_Permission_Snapshot"):
            self.normalized["permission_snapshots"].append({
                "file_id": clean(r.get("File_ID")),
                "resource": clean(r.get("Resource")),
                "permission": clean(r.get("Permission")),
                "principal_type": clean(r.get("Principal_Type")),
                "checked_at": clean(r.get("Checked_At")),
            })

    def validate(self) -> None:
        missing = REQUIRED_SHEETS - set(self.reader.sheet_names)
        if missing:
            self.issues.append(ValidationIssue("ERROR", "MISSING_SHEETS", f"Missing sheets: {sorted(missing)}"))

        source_ids = {x["source_id"] for x in self.normalized["sources"]}
        for coll in ("sources", "facts"):
            for row in self.normalized[coll]:
                if row.get("source_authority_l") not in VALID_L:
                    self.issues.append(ValidationIssue("ERROR", "INVALID_AUTHORITY", f"{coll}: {row}"))
                if row.get("evidence_confidence") not in VALID_CONF:
                    self.issues.append(ValidationIssue("ERROR", "INVALID_CONFIDENCE", f"{coll}: {row}"))
        for row in self.normalized["conflicts"]:
            if row.get("claim_a_l") not in VALID_L or row.get("claim_b_l") not in VALID_L:
                self.issues.append(ValidationIssue("ERROR", "INVALID_CONFLICT_AUTHORITY", str(row)))
            if row.get("claim_a_confidence") not in VALID_CONF or row.get("claim_b_confidence") not in VALID_CONF:
                self.issues.append(ValidationIssue("ERROR", "INVALID_CONFLICT_CONFIDENCE", str(row)))
        for row in self.normalized["facts"]:
            if row.get("source_id") not in source_ids:
                self.issues.append(ValidationIssue("ERROR", "BROKEN_SOURCE_REF", str(row)))
        for row in self.normalized["actions"]:
            if row.get("action_state") not in VALID_STATES:
                self.issues.append(ValidationIssue("ERROR", "INVALID_ACTION_STATE", str(row)))
            if row.get("execution_scope") not in VALID_SCOPES:
                self.issues.append(ValidationIssue("ERROR", "INVALID_EXECUTION_SCOPE", str(row)))
            if row.get("execution_mode") == "HUMAN_ONLY" and row.get("authorized"):
                self.issues.append(ValidationIssue("ERROR", "HUMAN_ONLY_AUTHORIZED", str(row)))
        for row in self.normalized["permission_snapshots"]:
            if not row.get("checked_at"):
                self.issues.append(ValidationIssue("WARN", "UNCHECKED_PERMISSION", str(row)))

    def promotion_gate(self) -> dict[str, Any]:
        n = self.normalized
        source_ids = [x["source_id"] for x in n["sources"]]
        fact_ids = [x["record_id"] for x in n["facts"]]
        conflict_ids = [x["conflict_id"] for x in n["conflicts"]]
        action_ids = [x["action_id"] for x in n["actions"]]
        permission_ids = [x["file_id"] for x in n["permission_snapshots"]]

        states = ["VERIFY", "READY", "NEW", "APPROVAL_REQUIRED", "HOLD", "BLOCKED", "DONE", "NOT_APPLICABLE"]
        scopes = ["NONE", "REVIEW_ONLY", "EVIDENCE_ACQUISITION", "PREPARE", "EXTERNAL_EXECUTION"]
        actor_space = list(itertools.product(states, scopes, [False, True]))
        policy_executable = [x for x in actor_space if x == ("READY", "EXTERNAL_EXECUTION", True)]
        fixture_executable = [
            a["action_id"] for a in n["actions"]
            if a["action_state"] == "READY" and a["execution_scope"] == "EXTERNAL_EXECUTION" and a["authorized"]
        ]
        source_id_set = set(source_ids)
        source_refs_ok = all(f["source_id"] in source_id_set for f in n["facts"])
        all_authority = [x["source_authority_l"] for x in n["sources"] + n["facts"]]
        all_confidence = [x["evidence_confidence"] for x in n["sources"] + n["facts"]]
        synthetic_ids = source_ids + fact_ids + conflict_ids + action_ids + permission_ids

        def check(test_id: str, ok: bool, actual: Any, expected: Any) -> dict[str, Any]:
            return {"id": test_id, "status": "PASS" if ok else "FAIL", "actual": actual, "expected": expected}

        results = [
            check("DC-DEMO-001", REQUIRED_SHEETS.issubset(set(self.reader.sheet_names)), sorted(self.reader.sheet_names), sorted(REQUIRED_SHEETS)),
            check("DC-DEMO-002", len(self.raw_rows) == 20, len(self.raw_rows), 20),
            check("DC-DEMO-003", len(n["sources"]) == 3, len(n["sources"]), 3),
            check("DC-DEMO-004", len(n["facts"]) == 3, len(n["facts"]), 3),
            check("DC-DEMO-005", len(n["money_ledger"]) == 2, len(n["money_ledger"]), 2),
            check("DC-DEMO-006", len(n["conflicts"]) == 2, len(n["conflicts"]), 2),
            check("DC-DEMO-007", len(n["actions"]) == 4, len(n["actions"]), 4),
            check("DC-DEMO-008", len(n["permission_snapshots"]) == 3, len(n["permission_snapshots"]), 3),
            check("DC-DEMO-009", all(len(x) == len(set(x)) for x in [source_ids, fact_ids, conflict_ids, action_ids, permission_ids]), True, True),
            check("DC-DEMO-010", all(x in VALID_L for x in all_authority), sorted(set(all_authority)), "subset L1-L5"),
            check("DC-DEMO-011", all(x in VALID_CONF for x in all_confidence), sorted(set(all_confidence)), "subset A-E"),
            check("DC-DEMO-012", source_refs_ok, source_refs_ok, True),
            check("DC-DEMO-013", len(actor_space) == 80, len(actor_space), 80),
            check("DC-DEMO-014", policy_executable == [("READY", "EXTERNAL_EXECUTION", True)], policy_executable, [("READY", "EXTERNAL_EXECUTION", True)]),
            check("DC-DEMO-015", fixture_executable == [], fixture_executable, []),
            check("DC-DEMO-016", sum(1 for p in n["permission_snapshots"] if p["checked_at"]) == 3, sum(1 for p in n["permission_snapshots"] if p["checked_at"]), 3),
            check("DC-DEMO-017", all("SYN" in str(x) for x in synthetic_ids if x), synthetic_ids, "all identifiers synthetic"),
        ]
        passed = sum(r["status"] == "PASS" for r in results)
        return {
            "gate_id": "DC-EVIDENCE-DEMO-GATE-001",
            "gate_version": "0.1",
            "status": "PASS_DEMO_ONLY" if passed == len(results) and not self.issues else "FAIL",
            "tests_total": len(results),
            "tests_passed": passed,
            "tests_failed": len(results) - passed,
            "external_execution_allowed": False,
            "results": results,
        }

    def report(self) -> dict[str, Any]:
        gate = self.promotion_gate()
        counts = {k: len(v) for k, v in self.normalized.items()}
        return {
            "demo": "Digital Core Evidence Governance Demo",
            "version": "0.1",
            "fixture": self.fixture.name,
            "fixture_sha256": hashlib.sha256(self.fixture.read_bytes()).hexdigest(),
            "pipeline": ["lossless_staging", "normalization", "validation", "governance_gate", "audit_report"],
            "normalized_counts": counts,
            "staging_nonempty_row_count": len(self.raw_rows),
            "validation_summary": {
                "ERROR": sum(i.severity == "ERROR" for i in self.issues),
                "WARN": sum(i.severity == "WARN" for i in self.issues),
            },
            "validation_issues": [asdict(i) for i in self.issues],
            "governance_gate": gate,
            "side_effects": {
                "network": False,
                "database": False,
                "external_writes": False,
                "local_report_only": True,
            },
        }


def run_fixture(fixture: Path) -> dict[str, Any]:
    demo = DigitalCoreEvidenceDemo(fixture)
    try:
        demo.stage()
        demo.normalize()
        demo.validate()
        return demo.report()
    finally:
        demo.close()
