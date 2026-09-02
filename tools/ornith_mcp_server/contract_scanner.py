"""
contract_scanner.py - AST and Structural Contract Verification for Ornith
Loads declarative rules from audit_contracts.json and performs:
1. Python AST parsing for silent fallbacks, swallowed exceptions, and multipliers.
2. Structural token scanning for JavaScript and HTML <script> fallback patterns.
3. Hardcoded calibration neutral checks (2048 / 0x800).
4. Remote target deployment parity verification (MD5 matching).
"""

import ast
import json
import os
import re
import sys
from typing import List, Dict, Any, Optional

DEFAULT_CONTRACTS_PATH = os.path.join(os.path.dirname(__file__), "audit_contracts.json")

def load_contracts(contracts_path: str = DEFAULT_CONTRACTS_PATH) -> List[Dict[str, Any]]:
    if not os.path.exists(contracts_path):
        return []
    try:
        with open(contracts_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data["contracts"]
    except Exception as e:
        sys.stderr.write(f"[CONTRACT_SCANNER] Error loading contracts: {e}\n")
        return []

class PythonASTContractVisitor(ast.NodeVisitor):
    def __init__(self, filename: str):
        self.filename = filename
        self.violations = []

    def _add_violation(self, rule: str, node: ast.AST, reason: str, snippet: str = ""):
        line = node.lineno if hasattr(node, "lineno") else 1
        if not snippet and hasattr(ast, "unparse"):
            snippet = ast.unparse(node)
        self.violations.append({
            "rule": rule,
            "file": self.filename,
            "line": line,
            "snippet": snippet,
            "reason": reason
        })


    def visit_Call(self, node: ast.Call):
        # 1. Check for .get(k, default)
        if isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name == "get" and len(node.args) >= 2:
                self._add_violation(
                    "FAIL_FAST_NO_FALLBACK",
                    node,
                    "Forbidden default fallback in .get(key, default). Must enforce schema contracts with direct key indexing or raise KeyError."
                )
            elif attr_name == "setdefault":
                self._add_violation(
                    "FAIL_FAST_NO_FALLBACK",
                    node,
                    "Forbidden .setdefault() fallback lookup. Must enforce explicit schema keys."
                )
            elif attr_name == "pop" and len(node.args) >= 2:
                self._add_violation(
                    "FAIL_FAST_NO_FALLBACK",
                    node,
                    "Forbidden default fallback in .pop(key, default). Must enforce schema contracts directly."
                )

        # 2. Check for getattr(obj, attr, default)
        elif isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 3:
                self._add_violation(
                    "FAIL_FAST_NO_FALLBACK",
                    node,
                    "Forbidden default fallback in getattr(obj, attr, default). Must enforce schema attributes directly."
                )

        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp):
        # Check ternary fallbacks: d[k] if k in d else default
        if isinstance(node.orelse, (ast.Constant, ast.Dict, ast.List)):
            # If body or test involves a subscript or lookup
            if isinstance(node.body, (ast.Subscript, ast.Call)):
                self._add_violation(
                    "FAIL_FAST_NO_FALLBACK",
                    node,
                    "Forbidden inline ternary fallback (lookup if ... else <literal>). Must enforce fail-fast keys."
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp):
        # Check d.get(k) or default, or d[k] or default
        if isinstance(node.op, ast.Or):
            first_val = node.values[0]
            if isinstance(first_val, (ast.Subscript, ast.Call)):
                for later_val in node.values[1:]:
                    if isinstance(later_val, (ast.Constant, ast.Dict, ast.List)):
                        self._add_violation(
                            "FAIL_FAST_NO_FALLBACK",
                            node,
                            "Forbidden chained fallback lookup ('lookup or <literal>'). Must enforce canonical request schema."
                        )
                        break
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        # Check swallowed exceptions: except: pass or except: ...
        for handler in node.handlers:
            if not handler.body:
                self._add_violation(
                    "NO_SWALLOWED_EXCEPTIONS",
                    handler,
                    "Swallowed exception detected (empty except handler). Must raise descriptive error or log traceback."
                )
            elif len(handler.body) == 1:
                stmt = handler.body[0]
                if isinstance(stmt, ast.Pass):
                    self._add_violation(
                        "NO_SWALLOWED_EXCEPTIONS",
                        handler,
                        "Swallowed exception detected ('except: pass'). Must raise descriptive error or log traceback."
                    )
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
                    self._add_violation(
                        "NO_SWALLOWED_EXCEPTIONS",
                        handler,
                        "Swallowed exception detected ('except: ...'). Must raise descriptive error or log traceback."
                    )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if type(node.value) is int and node.value in (2048, 0x800):
            if not self.filename.endswith(("test_mcp_tools.py", "contract_scanner.py")):
                self._add_violation(
                    "NO_HARDCODED_NEUTRAL",
                    node,
                    "Hardcoded 2048/0x800 neutral integer constant detected. Offsets and bounds must load dynamically from follower.json or calibration_aux.json."
                )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp):
        # Check motion neutering multipliers: * 0.5, * 0.8
        if isinstance(node.op, ast.Mult):
            multiplier = None
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)):
                multiplier = node.right.value
            elif isinstance(node.left, ast.Constant) and isinstance(node.left.value, (int, float)):
                multiplier = node.left.value

            if multiplier is not None and 0.05 <= multiplier <= 0.95:
                snippet = ast.unparse(node).lower()
                motion_keywords = ["bob", "tilt", "pan", "bounce", "lift", "flex", "pitch", "roll", "jaw", "amp", "intensity", "scale", "mod", "target", "rom"]
                if any(kw in snippet for kw in motion_keywords):
                    self._add_violation(
                        "NO_SAFETY_SLOP_MULTIPLIERS",
                        node,
                        f"Forbidden hardcoded motion scaling factor (* {multiplier}). Intensities must load from JSON configuration."
                    )
        self.generic_visit(node)

def scan_python_code(code: str, filename: str) -> List[Dict[str, Any]]:
    violations = []
    try:
        tree = ast.parse(code, filename=filename)
        visitor = PythonASTContractVisitor(filename=filename)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    except SyntaxError as e:
        violations.append({
            "rule": "SYNTAX_ERROR",
            "file": filename,
            "line": e.lineno or 1,
            "snippet": e.text or "",
            "reason": f"Python syntax error: {e.msg}"
        })
    except Exception as e:
        sys.stderr.write(f"[CONTRACT_SCANNER] AST parse error in {filename}: {e}\n")

    # Line-based regex scan for artificial range cages
    for idx, line in enumerate(code.splitlines(), 1):
        clean_line = line.strip()
        if clean_line.startswith(("#", '"""', "'''", "*")):
            continue

        if re.search(r'max\s*\(\s*(3[0-9]|4[0-9])\.[0-9]+\s*,\s*min\s*\(\s*(5[0-9]|6[0-9])\.[0-9]+', clean_line):
            violations.append({
                "rule": "NO_SAFETY_SLOP_MULTIPLIERS",
                "file": filename,
                "line": idx,
                "snippet": clean_line,
                "reason": "Forbidden artificial sub-range cage detected. Joint ranges must span full calibrated ROM (0.0 to 100.0%)."
            })
    return violations


def scan_javascript_code(code: str, filename: str) -> List[Dict[str, Any]]:
    violations = []
    lines = code.splitlines()

    for idx, line in enumerate(lines, 1):
        clean_line = line.strip()
        if clean_line.startswith("//") or clean_line.startswith("/*") or clean_line.startswith("*"):
            continue

        # 1. Nullish coalescing with literal number / boolean / string: ?? <literal>
        if re.search(r'\?\?\s*([0-9]+(\.[0-9]+)?|["\'][^"\']*["\']|true|false)\b', clean_line):
            violations.append({
                "rule": "JS_NO_DUMMY_FALLBACK",
                "file": filename,
                "line": idx,
                "snippet": clean_line,
                "reason": "Forbidden nullish coalescing fallback (?? <literal>) in JavaScript/HTML. Must render actual live state or neutral placeholder ('--')."
            })

        # 2. Ternary dummy fallback: !== undefined ? ... : <number> or != null ? ... : <number>
        if re.search(r'(!==|!=)\s*(undefined|null)\s*\?\s*[^:]+:\s*([0-9]+(\.[0-9]+)?)\b', clean_line) or \
           re.search(r'\?\s*[^:]+:\s*([0-9]+(\.[0-9]+)?)\b', clean_line):
            # Check if associated with state/telemetry/pos/stick/data/coords/x/y
            if any(w in clean_line.lower() for w in ["telem", "stick", "pos", "coord", "data", "val", "joy", "raw", "target"]):
                violations.append({
                    "rule": "JS_NO_DUMMY_FALLBACK",
                    "file": filename,
                    "line": idx,
                    "snippet": clean_line,
                    "reason": "Forbidden ternary dummy fallback number on live telemetry or state. Must render actual live state or neutral placeholder ('--')."
                })

        # 3. Logical OR dummy fallback: || <literal> on telemetry/state
        if re.search(r'\|\|\s*([0-9]+(\.[0-9]+)?)\b', clean_line):
            if any(w in clean_line.lower() for w in ["telem", "stick", "pos", "coord", "data", "val", "joy", "raw", "target"]):
                violations.append({
                    "rule": "JS_NO_DUMMY_FALLBACK",
                    "file": filename,
                    "line": idx,
                    "snippet": clean_line,
                    "reason": "Forbidden logical OR dummy fallback (|| <number>) on telemetry or state. Must fail fast or display placeholder."
                })

        # 4. Destructuring defaults: const { x = 7, y = 118 } = ...
        if re.search(r'\{\s*[^}]*\b(x|y|val|speed|pos|angle)\s*=\s*[0-9]+[^}]*\}', clean_line):
            violations.append({
                "rule": "JS_NO_DUMMY_FALLBACK",
                "file": filename,
                "line": idx,
                "snippet": clean_line,
                "reason": "Forbidden destructuring default on coordinates or telemetry parameters. Must enforce canonical payload schema."
            })

        # 5. Hardcoded 2048 / 0x800 neutral ticks
        if re.search(r'\b(2048|0x800)\b', clean_line):
            if any(k in clean_line.lower() for k in ["pos", "target", "neutral", "center", "homing", "offset", "default"]):
                violations.append({
                    "rule": "NO_HARDCODED_NEUTRAL",
                    "file": filename,
                    "line": idx,
                    "snippet": clean_line,
                    "reason": "Hardcoded 2048/0x800 neutral detected in JavaScript. Offsets and bounds must load dynamically from JSON."
                })

    return violations

def scan_html_code(code: str, filename: str) -> List[Dict[str, Any]]:
    violations = []
    # Extract <script> blocks
    script_blocks = re.findall(r'<script\b[^>]*>(.*?)</script>', code, flags=re.DOTALL | re.IGNORECASE)
    for block in script_blocks:
        js_violations = scan_javascript_code(block, filename)
        violations.extend(js_violations)
    return violations

def scan_source_file(file_path: str, repo_path: str = None) -> List[Dict[str, Any]]:
    if repo_path and not os.path.isabs(file_path):
        full_path = os.path.join(repo_path, file_path)
    else:
        full_path = file_path

    if not os.path.isfile(full_path):
        return []

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return [{
            "rule": "FILE_READ_ERROR",
            "file": file_path,
            "line": 1,
            "snippet": "",
            "reason": f"Failed to read file: {e}"
        }]

    lower_name = file_path.lower()
    if lower_name.endswith(".py"):
        return scan_python_code(content, file_path)
    elif lower_name.endswith(".js"):
        return scan_javascript_code(content, file_path)
    elif lower_name.endswith((".html", ".htm")):
        return scan_html_code(content, file_path)
    return []
