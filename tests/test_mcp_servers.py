"""
test_mcp_servers.py - Unit tests for the 3 decoupled MCP servers:
1. code-auditor
2. device-bridge
3. voice-bridge
"""

import importlib.util
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

class TestCodeAuditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auditor_dir = os.path.join(REPO_ROOT, "tools", "mcp_servers", "code_auditor")
        sys.path.insert(0, auditor_dir)
        cls.auditor = load_module("code_auditor_mod", os.path.join(auditor_dir, "auditor.py"))

    def test_get_git_diff(self):
        res = self.auditor.get_git_diff(REPO_ROOT)
        self.assertEqual(res["status"], "success")
        self.assertIn("diff", res)

    def test_scan_code_contracts_clean(self):
        res = self.auditor.scan_code_contracts(diff_text="", repo_path=REPO_ROOT)
        self.assertEqual(res["status"], "success")
        self.assertIn("clean", res)
        self.assertIn("violations", res)

    def test_read_workspace_file(self):
        res = self.auditor.read_workspace_file("config/mcp_servers.json", start_line=1, max_lines=10)
        self.assertEqual(res["status"], "success")
        self.assertIn("code_auditor", res["content"])

class TestDeviceBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bridge_dir = os.path.join(REPO_ROOT, "tools", "mcp_servers", "device_bridge")
        sys.path.insert(0, bridge_dir)
        cls.bridge = load_module("device_bridge_mod", os.path.join(bridge_dir, "bridge.py"))

    def test_verify_file_deployment_local_missing(self):
        res = self.bridge.verify_file_deployment("non_existent_file.py")
        self.assertEqual(res["status"], "error")

    def test_verify_file_deployment_local_existing(self):
        res = self.bridge.verify_file_deployment("config/mcp_servers.json")
        self.assertEqual(res["status"], "success")
        self.assertIn("local_md5", res)

class TestVoiceBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        voice_dir = os.path.join(REPO_ROOT, "tools", "mcp_servers", "voice_bridge")
        sys.path.insert(0, voice_dir)
        cls.speech = load_module("voice_bridge_mod", os.path.join(voice_dir, "speech.py"))

    def test_empty_text_rejection(self):
        res = self.speech.speak_laura("   ")
        self.assertEqual(res["status"], "error")

if __name__ == "__main__":
    unittest.main()
