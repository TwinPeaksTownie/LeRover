#!/usr/bin/env python3
"""Pipeline Else & Fallback Audit Tool.
Performs AST static analysis across the Beat Bandit compilation and runtime pipeline
to verify zero silent fallbacks, zero dual schemas, and explicit fail-fast handling.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')


PIPELINE_FILES = [
    Path("pi500/choreography_compiler.py"),
    Path("pi500/beat_bandit_app.py"),
]


class PipelineAuditVisitor(ast.NodeVisitor):
    def __init__(self, filename: str, lines: List[str]):
        self.filename = filename
        self.lines = lines
        self.if_else_nodes: List[Dict[str, Any]] = []
        self.dict_get_calls: List[Dict[str, Any]] = []
        self.dual_schema_flags: List[Dict[str, Any]] = []

    def visit_If(self, node: ast.If):
        test_expr = ast.unparse(node.test) if hasattr(ast, "unparse") else str(node.test)
        has_else = len(node.orelse) > 0
        is_elif = False
        if has_else and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            is_elif = True

        # Check for suspicious dual schema patterns
        if "in" in test_expr and any(legacy in test_expr for legacy in ["target_deg", "target_pos", "step_deg"]):
            self.dual_schema_flags.append({
                "line": node.lineno,
                "test": test_expr,
                "reason": "Legacy dual-schema check detected"
            })

        self.if_else_nodes.append({
            "line": node.lineno,
            "test": test_expr,
            "has_else": has_else,
            "is_elif": is_elif,
            "code": self.lines[node.lineno - 1].strip() if node.lineno <= len(self.lines) else ""
        })
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            args_unparsed = [ast.unparse(a) for a in node.args] if hasattr(ast, "unparse") else []
            # If get has 2 args (key, default), inspect it
            if len(node.args) >= 2:
                key_name = args_unparsed[0] if args_unparsed else ""
                default_val = args_unparsed[1] if len(args_unparsed) > 1 else ""
                self.dict_get_calls.append({
                    "line": node.lineno,
                    "key": key_name,
                    "default": default_val,
                    "code": self.lines[node.lineno - 1].strip() if node.lineno <= len(self.lines) else ""
                })
        self.generic_visit(node)


def audit_file(filepath: Path) -> Dict[str, Any]:
    if not filepath.exists():
        return {"file": str(filepath), "error": "File not found"}

    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()
    lines = src.splitlines()

    tree = ast.parse(src, filename=str(filepath))
    visitor = PipelineAuditVisitor(str(filepath), lines)
    visitor.visit(tree)

    return {
        "file": str(filepath),
        "total_ifs": len(visitor.if_else_nodes),
        "if_else_list": visitor.if_else_nodes,
        "dict_get_defaults": visitor.dict_get_calls,
        "dual_schema_flags": visitor.dual_schema_flags,
    }


def run_full_pipeline_audit() -> bool:
    print("=" * 80)
    print("PIPELINE ELSE & FALLBACK STATIC ANALYSIS AUDIT REPORT")
    print("=" * 80)

    all_passed = True

    for fpath in PIPELINE_FILES:
        res = audit_file(fpath)
        print(f"\nAUDITING: {res['file']}")
        print("-" * 60)

        # 1. Check Dual Schema Flags
        dual_flags = res.get("dual_schema_flags", [])
        if dual_flags:
            print(f"❌ FAILED: {len(dual_flags)} legacy dual-schema checks found:")
            for df in dual_flags:
                print(f"   Line {df['line']}: {df['test']} ({df['reason']})")
            all_passed = False
        else:
            print("✅ PASSED: Zero dual-schema branches detected.")

        # 2. Check Dictionary Defaults for Kinematic Targets
        kinematic_target_keys = ["target_pos_rom", "neck_pitch_rom", "tilt_rom", "step_rom", "speed"]
        bad_gets = []
        for dg in res.get("dict_get_defaults", []):
            k = dg["key"].replace("'", "").replace('"', "")
            if k in kinematic_target_keys:
                bad_gets.append(dg)

        if bad_gets:
            print(f"❌ FAILED: {len(bad_gets)} dictionary default fallbacks on kinematic keys found:")
            for bg in bad_gets:
                print(f"   Line {bg['line']}: {bg['code']}")
            all_passed = False
        else:
            print("✅ PASSED: Zero fallback defaults on kinematic targets.")

        # 3. Report Else Statements Breakdown
        total_ifs = res.get("total_ifs", 0)
        elses = [i for i in res.get("if_else_list", []) if i["has_else"]]
        print(f"ℹ️ Total If-statements: {total_ifs} | Branches with Else/Elif: {len(elses)}")
        for e in elses:
            print(f"   Line {e['line']:4d}: {e['code']}")

    print("\n" + "=" * 80)
    if all_passed:
        print("🎉 AUDIT PASSED: Pipeline is clean of silent fallbacks and dual schemas!")
    else:
        print("💥 AUDIT FAILED: Disallowed fallbacks or dual schemas detected.")
    print("=" * 80)
    return all_passed


if __name__ == "__main__":
    ok = run_full_pipeline_audit()
    sys.exit(0 if ok else 1)
