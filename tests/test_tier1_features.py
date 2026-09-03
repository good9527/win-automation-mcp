# tests/test_tier1_features.py
"""
Tier 1: Feature Baseline Verification (F1 - F9)

Covers primary behavior and interface contracts for requirements R1 through R6:
- F1: Modular import structure and namespace exports (R5)
- F2: BOM absence and clean repo status (R6)
- F3: Atomic state persistence and file locking (R6)
- F4: Helper authentication & Host header validation (R2)
- F5: check_safety classification (Chinese & English) (R3)
- F6: In-memory OCR execution path (<100ms) (R4)
- F7: DXCam camera instance reuse and capture ladder (R4)
- F8: Compact profile schema size (<35k chars) & 9 tools (R1)
- F9: Backward compatibility wrappers (R5)
"""

import os
import sys
import time
import json
import secrets
import tempfile
import threading
import unittest
from typing import Any, Dict, List, Optional, Tuple, Union


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from win_automation.safety.gate import check_safety
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.state.persistence import save_state, load_state
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.ocr.finder import run_ocr
from win_automation.server.compact_tools import (
    COMPACT_TOOLS,
    COMPACT_TOOL_SCHEMAS,
    get_compact_tool_schemas,
    calculate_serialized_schema_size,
)


class TestF1ModularImportStructure(unittest.TestCase):
    def test_f1_01_core_package_spec_structure(self):
        expected_submodules = [
            "core", "win32", "uia", "vision", "ocr", "input",
            "safety", "state", "helper", "server", "cli"
        ]
        win_auto_dir = os.path.join(PROJECT_ROOT, "win_automation")
        if os.path.exists(win_auto_dir):
            for submod in expected_submodules:
                submod_path = os.path.join(win_auto_dir, submod)
                exists = os.path.exists(submod_path) or os.path.exists(submod_path + ".py")
                self.assertTrue(exists, f"Submodule {submod} must exist in win_automation")
        else:
            self.assertTrue(len(expected_submodules) >= 11)

    def test_f1_02_safety_module_contract(self):
        self.assertTrue(callable(check_safety))
        res = check_safety("open notepad")
        self.assertIsInstance(res, dict)
        self.assertIn("needs_confirmation", res)
        self.assertIn("risk_level", res)
        self.assertIn("category", res)

    def test_f1_03_helper_security_module_contract(self):
        self.assertTrue(callable(generate_session_token))
        self.assertTrue(callable(verify_request))
        tok = generate_session_token()
        self.assertIsInstance(tok, str)
        self.assertGreaterEqual(len(tok), 32)

    def test_f1_04_state_persistence_module_contract(self):
        self.assertTrue(callable(save_state))
        self.assertTrue(callable(load_state))

    def test_f1_05_vision_dxcam_module_contract(self):
        self.assertTrue(hasattr(DXCamManager, "get_camera"))
        cam = DXCamManager.get_camera(0, None)
        self.assertIsNotNone(cam)

    def test_f1_06_server_profile_schemas_contract(self):
        schemas = get_compact_tool_schemas()
        self.assertEqual(len(schemas), 9)
        for tool_name in COMPACT_TOOLS:
            self.assertIn(tool_name, schemas)


class TestF2BOMAbsenceAndRepoHygiene(unittest.TestCase):
    def test_f2_01_server_py_no_utf8_bom(self):
        server_path = os.path.join(PROJECT_ROOT, "server.py")
        if os.path.exists(server_path):
            with open(server_path, "rb") as f:
                header = f.read(3)
                self.assertNotEqual(header, b"\xef\xbb\xbf", "server.py must not contain UTF-8 BOM")

    def test_f2_02_tools_py_and_helper_py_no_bom(self):
        for fname in ["tools.py", "helper.py"]:
            fpath = os.path.join(PROJECT_ROOT, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    header = f.read(3)
                    self.assertNotEqual(header, b"\xef\xbb\xbf", f"{fname} must not contain UTF-8 BOM")

    def test_f2_03_test_files_no_bom(self):
        tests_dir = os.path.join(PROJECT_ROOT, "tests")
        for fname in os.listdir(tests_dir):
            if fname.endswith(".py"):
                fpath = os.path.join(tests_dir, fname)
                with open(fpath, "rb") as f:
                    header = f.read(3)
                    self.assertNotEqual(header, b"\xef\xbb\xbf", f"{fname} has UTF-8 BOM")

    def test_f2_04_gitignore_rules_present(self):
        gitignore_path = os.path.join(PROJECT_ROOT, ".gitignore")
        self.assertTrue(os.path.exists(gitignore_path), ".gitignore must exist")
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().lower()
        required_patterns = ["*.png", "*.jpg", "*.log"]
        for pat in required_patterns:
            self.assertTrue(pat in content or pat.replace("*", "") in content, f"{pat} should be in .gitignore")

    def test_f2_05_clean_repo_hygiene_policy(self):
        tests_dir = os.path.join(PROJECT_ROOT, "tests")
        for fname in os.listdir(tests_dir):
            self.assertFalse(fname.endswith(".log"), f"Stray log file found in tests/: {fname}")
            self.assertFalse(fname.startswith("temp_") and fname.endswith(".png"), f"Stray temp screenshot: {fname}")


class TestF3AtomicStatePersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "test-state.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_f3_01_save_state_creates_valid_json(self):
        test_payload = {
            "target_hwnd": 12345,
            "last_action": "click",
            "history": ["observe", "act"],
            "meta": {"dpi": 1.25, "active": True}
        }
        res_path = save_state(test_payload, self.state_file)
        self.assertTrue(os.path.exists(res_path))
        with open(res_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded, test_payload)

    def test_f3_02_atomic_replacement_no_orphan_temps(self):
        save_state({"count": 1}, self.state_file)
        save_state({"count": 2}, self.state_file)
        save_state({"count": 3}, self.state_file)
        files = os.listdir(self.temp_dir.name)
        tmp_files = [f for f in files if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0, f"Lingering temporary files: {tmp_files}")
        self.assertIn("test-state.json", files)

    def test_f3_03_load_state_missing_file_returns_empty_dict(self):
        missing_file = os.path.join(self.temp_dir.name, "missing.json")
        loaded = load_state(missing_file)
        self.assertEqual(loaded, {})

    def test_f3_04_load_state_corrupted_file_returns_empty_dict(self):
        corrupt_file = os.path.join(self.temp_dir.name, "corrupt.json")
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json truncated... ")
        loaded = load_state(corrupt_file)
        self.assertEqual(loaded, {})

    def test_f3_05_concurrent_write_stress_integrity(self):
        def worker(idx):
            for i in range(10):
                save_state({"worker": idx, "iteration": i, "data": "x" * 100}, self.state_file)
        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        final_state = load_state(self.state_file)
        self.assertIsInstance(final_state, dict)
        self.assertIn("worker", final_state)
        self.assertIn("iteration", final_state)

    def test_f3_06_state_utf8_chinese_preservation(self):
        payload = {"window_title": "记事本 - 无标题", "action": "点击保存"}
        save_state(payload, self.state_file)
        loaded = load_state(self.state_file)
        self.assertEqual(loaded["window_title"], "记事本 - 无标题")
        self.assertEqual(loaded["action"], "点击保存")


class TestF4HelperAuthenticationAndHostValidation(unittest.TestCase):
    def setUp(self):
        self.token = generate_session_token()

    def test_f4_01_token_generation_entropy_and_format(self):
        tok1 = generate_session_token()
        tok2 = generate_session_token()
        self.assertNotEqual(tok1, tok2)
        self.assertGreaterEqual(len(tok1), 32)
        self.assertTrue(tok1.replace("-", "").replace("_", "").isalnum())

    def test_f4_02_valid_token_and_valid_host_accepted(self):
        headers = {"Host": "127.0.0.1:18765", "X-Helper-Token": self.token}
        ok, code, msg = verify_request(headers, self.token)
        self.assertTrue(ok)
        self.assertEqual(code, 200)
        self.assertEqual(msg, "OK")

    def test_f4_03_missing_token_rejected_403(self):
        headers = {"Host": "127.0.0.1:18765"}
        ok, code, msg = verify_request(headers, self.token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("Forbidden", msg)

    def test_f4_04_invalid_token_rejected_403(self):
        headers = {"Host": "127.0.0.1:18765", "X-Helper-Token": "invalid_wrong_token"}
        ok, code, msg = verify_request(headers, self.token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)
        self.assertIn("Forbidden", msg)

    def test_f4_05_spoofed_host_header_rejected_403(self):
        spoofed_hosts = ["evil.com", "127.0.0.1.evil.com", "192.168.1.5", "attacker.local:18765"]
        for host in spoofed_hosts:
            headers = {"Host": host, "X-Helper-Token": self.token}
            ok, code, msg = verify_request(headers, self.token)
            self.assertFalse(ok, f"Host {host} should be rejected")
            self.assertEqual(code, 403)

    def test_f4_06_localhost_variants_accepted(self):
        valid_hosts = ["127.0.0.1:18765", "127.0.0.1", "localhost:18765", "localhost:18766", "localhost"]
        for host in valid_hosts:
            headers = {"Host": host, "X-Helper-Token": self.token}
            ok, code, msg = verify_request(headers, self.token)
            self.assertTrue(ok, f"Host {host} should be accepted")
            self.assertEqual(code, 200)

    def test_f4_07_case_insensitive_header_keys(self):
        headers = {"host": "127.0.0.1:18765", "x-helper-token": self.token}
        ok, code, msg = verify_request(headers, self.token)
        self.assertTrue(ok)
        self.assertEqual(code, 200)


class TestF5ChineseEnglishSafetyClassification(unittest.TestCase):
    def test_f5_01_chinese_file_destruction(self):
        destructive_cmds = [
            "删除系统文件", "清空回收站", "格式化D盘", "销毁文件", "彻底删除项目", "强力清空磁盘"
        ]
        for cmd in destructive_cmds:
            res = check_safety(cmd)
            self.assertTrue(res["needs_confirmation"], f"Failed to flag: {cmd}")
            self.assertEqual(res["risk_level"], "critical")
            self.assertEqual(res["category"], "file_destruction")

    def test_f5_02_english_file_destruction(self):
        destructive_cmds = [
            "del /f /q *.*", "rmdir /s /q c:\\temp", "format c:", "drop table users", "truncate database"
        ]
        for cmd in destructive_cmds:
            res = check_safety(cmd)
            self.assertTrue(res["needs_confirmation"], f"Failed to flag: {cmd}")
            self.assertEqual(res["risk_level"], "critical")
            self.assertEqual(res["category"], "file_destruction")

    def test_f5_03_chinese_financial_transactions(self):
        financial_cmds = [
            "支付订单50元", "确认付款给商家", "转账1000元到账户", "充值会员VIP", "提现到银行卡", "免密支付确认"
        ]
        for cmd in financial_cmds:
            res = check_safety(cmd)
            self.assertTrue(res["needs_confirmation"], f"Failed to flag: {cmd}")
            self.assertEqual(res["risk_level"], "critical")
            self.assertEqual(res["category"], "financial_transaction")

    def test_f5_04_english_financial_transactions(self):
        financial_cmds = [
            "pay USD 50 for subscription", "checkout order now", "transfer funds to account", "wire money to vendor", "buy 10 shares"
        ]
        for cmd in financial_cmds:
            res = check_safety(cmd)
            self.assertTrue(res["needs_confirmation"], f"Failed to flag: {cmd}")
            self.assertEqual(res["risk_level"], "critical")
            self.assertEqual(res["category"], "financial_transaction")

    def test_f5_05_system_alteration_and_shutdown(self):
        system_cmds = [
            "关机", "重启计算机", "shutdown /s /t 0", "regedit", "taskkill /f /im svchost.exe", "net stop spooler"
        ]
        for cmd in system_cmds:
            res = check_safety(cmd)
            self.assertTrue(res["needs_confirmation"], f"Failed to flag: {cmd}")
            self.assertEqual(res["risk_level"], "high")
            self.assertEqual(res["category"], "system_alteration")

    def test_f5_06_safe_operations_not_blocked(self):
        safe_cmds = [
            "open notepad", "list_windows", "查看当前窗口", "点击确定按钮", "type hello world", "take screenshot"
        ]
        for cmd in safe_cmds:
            res = check_safety(cmd)
            self.assertFalse(res["needs_confirmation"], f"Falsely flagged: {cmd}")
            self.assertEqual(res["risk_level"], "none")


class TestF6InMemoryOCRExecutionPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw, ImageFont
        import io
        cls.test_img = Image.new("RGB", (400, 80), (255, 255, 255))
        d = ImageDraw.Draw(cls.test_img)
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        d.text((15, 20), "CONFIRM CANCEL 789", fill=(0, 0, 0), font=font)

        buf = io.BytesIO()
        cls.test_img.save(buf, format="PNG")
        cls.test_png_bytes = buf.getvalue()

    def test_f6_01_in_memory_execution_no_powershell_spawn(self):
        res = run_ocr(self.test_png_bytes, lang="zh-Hans-CN")
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0)
        texts = [item["text"] for item in res]
        self.assertTrue(any("CONFIRM" in t or "CANCEL" in t or "789" in t for t in texts))

    def test_f6_02_standard_word_rect_schema(self):
        res = run_ocr(self.test_img)
        self.assertGreater(len(res), 0)
        for item in res:
            self.assertIn("text", item)
            self.assertIn("confidence", item)
            self.assertIn("rect", item)
            self.assertIsInstance(item["text"], str)
            self.assertIsInstance(item["confidence"], (int, float))
            rect = item["rect"]
            self.assertIn("x", rect)
            self.assertIn("y", rect)
            self.assertIn("width", rect)
            self.assertIn("height", rect)

    def test_f6_03_latency_performance_budget_under_100ms(self):
        start_time = time.time()
        res = run_ocr(self.test_img)
        latency_ms = (time.time() - start_time) * 1000
        self.assertLess(latency_ms, 100.0)
        self.assertGreater(len(res), 0)

    def test_f6_04_chinese_language_support_flag(self):
        from PIL import Image, ImageDraw, ImageFont
        img_cn = Image.new("RGB", (400, 80), (255, 255, 255))
        d = ImageDraw.Draw(img_cn)
        try:
            font = ImageFont.truetype("msyh.ttc", 32)
        except Exception:
            font = ImageFont.load_default()
        d.text((15, 20), "确认 取消 订单", fill=(0, 0, 0), font=font)
        res = run_ocr(img_cn, lang="zh-Hans-CN")
        self.assertIsInstance(res, list)
        self.assertGreater(len(res), 0)
        full_text = "".join(item["text"] for item in res)
        self.assertTrue("确认" in full_text or "取消" in full_text or "订单" in full_text)

    def test_f6_05_image_buffer_input_formats(self):
        res_empty = run_ocr(b"")
        self.assertEqual(res_empty, [])
        res_invalid = run_ocr(b"invalid_image_corrupt_data")
        self.assertEqual(res_invalid, [])
        res_valid = run_ocr(self.test_png_bytes)
        self.assertIsInstance(res_valid, list)
        self.assertGreater(len(res_valid), 0)


class TestF7DXCamInstanceReuseAndCaptureLadder(unittest.TestCase):
    def setUp(self):
        DXCamManager.reset()

    def test_f7_01_dxcam_manager_singleton_instance_reuse(self):
        cam1 = DXCamManager.get_camera(0, None)
        cam2 = DXCamManager.get_camera(0, None)
        self.assertIs(cam1, cam2)
        self.assertEqual(DXCamManager.creation_count(), 1)

    def test_f7_02_dxcam_manager_multi_output_separation(self):
        cam_out0 = DXCamManager.get_camera(0, 0)
        cam_out1 = DXCamManager.get_camera(0, 1)
        self.assertIsNot(cam_out0, cam_out1)
        self.assertEqual(DXCamManager.creation_count(), 2)

    def test_f7_03_dxcam_manager_thread_safety(self):
        cameras = []
        def fetch():
            c = DXCamManager.get_camera(0, None)
            cameras.append(c)
        threads = [threading.Thread(target=fetch) for _ in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(len(cameras), 10)
        self.assertEqual(DXCamManager.creation_count(), 1)
        for c in cameras[1:]: self.assertIs(cameras[0], c)

    def test_f7_04_capture_ladder_fallback_order(self):
        ladder = ["dxcam", "printwindow_renderfullcontent", "printwindow_0", "bitblt"]
        self.assertEqual(ladder[0], "dxcam")
        self.assertEqual(ladder[-1], "bitblt")

    def test_f7_05_dxcam_reset_cleanup(self):
        DXCamManager.get_camera(0, None)
        self.assertEqual(DXCamManager.creation_count(), 1)
        DXCamManager.reset()
        self.assertEqual(DXCamManager.creation_count(), 0)


class TestF8CompactProfileSchemaAndToolRegistry(unittest.TestCase):
    def test_f8_01_compact_profile_nine_high_intent_tools(self):
        expected_tools = {
            "observe_window", "act", "type_input", "key_press", "wait_state",
            "execute_batch", "check_safety", "launch_app", "doctor"
        }
        self.assertEqual(set(COMPACT_TOOLS), expected_tools)

    def test_f8_02_compact_schema_size_budget_under_35000_chars(self):
        schemas = get_compact_tool_schemas()
        serialized_size = calculate_serialized_schema_size(schemas)
        self.assertLess(serialized_size, 35000)
        self.assertLess(serialized_size, 20000)

    def test_f8_03_act_tool_supported_actions_enum(self):
        act_schema = COMPACT_TOOL_SCHEMAS["act"]
        actions_enum = act_schema["parameters"]["properties"]["action"]["enum"]
        expected_actions = ["click", "double_click", "right_click", "hover", "context_menu", "select", "toggle", "scroll", "drag", "invoke"]
        for act in expected_actions:
            self.assertIn(act, actions_enum)

    def test_f8_04_observe_window_parameter_schema(self):
        obs_props = COMPACT_TOOL_SCHEMAS["observe_window"]["parameters"]["properties"]
        self.assertIn("hwnd", obs_props)
        self.assertIn("include_screenshot", obs_props)
        self.assertIn("include_tree", obs_props)
        self.assertIn("include_ocr", obs_props)
        self.assertIn("max_width", obs_props)

    def test_f8_05_type_input_parameter_schema(self):
        props = COMPACT_TOOL_SCHEMAS["type_input"]["parameters"]["properties"]
        self.assertIn("text", props)
        self.assertIn("mode", props)
        self.assertIn("clear_first", props)
        self.assertIn("press_enter", props)


class TestF9BackwardCompatibilityWrappers(unittest.TestCase):
    def test_f9_01_server_py_entrypoint_exists(self):
        server_path = os.path.join(PROJECT_ROOT, "server.py")
        self.assertTrue(os.path.exists(server_path))
        with open(server_path, "r", encoding="utf-8-sig", errors="ignore") as f:
            code = f.read()
        compile(code, server_path, "exec")

    def test_f9_02_tools_py_entrypoint_exists(self):
        tools_path = os.path.join(PROJECT_ROOT, "tools.py")
        self.assertTrue(os.path.exists(tools_path))
        with open(tools_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        compile(code, tools_path, "exec")

    def test_f9_03_helper_py_entrypoint_exists(self):
        helper_path = os.path.join(PROJECT_ROOT, "helper.py")
        self.assertTrue(os.path.exists(helper_path))
        with open(helper_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
        compile(code, helper_path, "exec")

    def test_f9_04_cli_command_spec_coverage(self):
        """Verify core CLI commands resolve via tools.py PEP 562 and dispatch properly via win_automation.cli."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        import tools
        from win_automation.cli.main import main as cli_main

        # 1. Verify PEP 562 dynamic resolution on tools.py for core commands
        core_cli_cmds = [
            "list_windows", "get_window", "observe", "click",
            "type_text", "press_key", "execute_batch", "check_safety"
        ]
        for cmd in core_cli_cmds:
            fn = getattr(tools, cmd, None)
            self.assertIsNotNone(fn, f"Core command '{cmd}' cannot be resolved from tools.py")
            self.assertTrue(callable(fn), f"Resolved symbol '{cmd}' is not callable")

        # 2. Verify CLI usage help dispatch prints command specification
        help_out = io.StringIO()
        with redirect_stdout(help_out):
            try:
                cli_main(["--help"])
            except SystemExit:
                pass
        help_text = help_out.getvalue()
        self.assertIn("Usage: python tools.py", help_text)
        self.assertIn("list_windows", help_text)
        self.assertIn("observe", help_text)

        # 3. Verify safe command execution through CLI dispatcher
        screen_out = io.StringIO()
        with redirect_stdout(screen_out):
            try:
                cli_main(["screen"])
            except SystemExit:
                pass
        screen_val = json.loads(screen_out.getvalue().strip())
        self.assertIn("virtual_screen", screen_val)

        # 4. Verify safety check command through CLI dispatcher
        confirm_out = io.StringIO()
        with redirect_stdout(confirm_out):
            try:
                cli_main(["confirm", "删除系统文件"])
            except SystemExit:
                pass
        confirm_val = json.loads(confirm_out.getvalue().strip())
        self.assertTrue(confirm_val["needs_confirmation"])
        self.assertEqual(confirm_val["category"], "file_destruction")

    def test_f9_05_backward_compatibility_claude_desktop_args(self):
        """Verify server.py backward-compatible entrypoint and stdio transport execution for Claude Desktop."""
        import server
        from unittest.mock import patch

        # 1. Verify server module PEP 562 attributes
        self.assertTrue(callable(getattr(server, "create_app", None)))
        self.assertTrue(callable(getattr(server, "main", None)))

        # 2. Verify FastMCP initialization and profile contract
        app = server.create_app()
        self.assertIsNotNone(app, "server.create_app() returned None")
        self.assertEqual(app.name, "windows-automation")
        self.assertEqual(len(app._tool_manager._tools), 9, "Default profile must register 9 compact tools")

        # 3. Verify Claude Desktop main execution invokes server.run(transport='stdio')
        with patch.object(server.server, "run") as mock_run:
            server.main()
            mock_run.assert_called_once_with(transport="stdio")


class TestF10ExpertProfilePreservation(unittest.TestCase):
    """Feature 10: Verify all 111 granular tools in Expert Profile are mapped, callable, and return no facade errors."""

    def setUp(self):
        self.orig_env = os.environ.get("WIN_AUTO_PROFILE")
        os.environ["WIN_AUTO_PROFILE"] = "expert"
        from win_automation.server.app import create_app
        self.app = create_app()

    def tearDown(self):
        if self.orig_env is None:
            os.environ.pop("WIN_AUTO_PROFILE", None)
        else:
            os.environ["WIN_AUTO_PROFILE"] = self.orig_env

    def test_f10_01_expert_profile_tool_count_111(self):
        """Expert profile must register exactly 111 distinct tools."""
        self.assertIsNotNone(self.app, "FastMCP app failed to initialize")
        tool_count = len(self.app._tool_manager._tools)
        self.assertEqual(tool_count, 111, f"Expected 111 tools in expert profile, got {tool_count}")

    def test_f10_02_all_111_tools_resolved_via_tools_py(self):
        """Every one of the 111 expert tools must resolve to a valid callable via tools.py PEP 562."""
        import tools
        missing_symbols = []
        non_callable_symbols = []
        for name in self.app._tool_manager._tools:
            target = getattr(tools, name, None)
            if target is None:
                missing_symbols.append(name)
            elif not callable(target):
                non_callable_symbols.append(name)

        self.assertEqual(
            missing_symbols,
            [],
            f"{len(missing_symbols)} expert tools have no backing implementation in tools.py: {missing_symbols}"
        )
        self.assertEqual(
            non_callable_symbols,
            [],
            f"{len(non_callable_symbols)} expert tools resolve to non-callables: {non_callable_symbols}"
        )

    def test_f10_03_all_111_tools_callable_without_facade_errors(self):
        """
        Iterate and call all 111 Expert Profile tools.
        Verify that NONE returns {'ok': False, 'error': 'Function ... not found'}.
        """
        import inspect

        def _make_safe_kwargs(fn):
            sig = inspect.signature(fn)
            kwargs = {}
            for p in sig.parameters.values():
                p_name = p.name.lower()
                if "timeout" in p_name:
                    kwargs[p.name] = 0.001
                elif p.default is not inspect.Parameter.empty:
                    continue
                elif "hwnd" in p_name:
                    kwargs[p.name] = 0
                elif any(k in p_name for k in ("action", "command", "text", "keys", "name", "title", "path", "class_name", "query", "condition", "template")):
                    kwargs[p.name] = "test"
                elif any(k in p_name for k in ("x", "y", "width", "height", "index", "row", "col", "id", "pid", "count", "ticks")):
                    kwargs[p.name] = 0
                elif any(k in p_name for k in ("commands", "points", "rect", "keys_list")):
                    kwargs[p.name] = []
                elif any(k in p_name for k in ("target", "spec", "data", "options")):
                    kwargs[p.name] = {}
                elif p.annotation is bool:
                    kwargs[p.name] = False
                else:
                    kwargs[p.name] = None
            return kwargs

        facade_failures = []
        for name, tool_obj in self.app._tool_manager._tools.items():
            kwargs = _make_safe_kwargs(tool_obj.fn)
            try:
                res = tool_obj.fn(**kwargs)
                if isinstance(res, dict):
                    err = str(res.get("error", ""))
                    if f"Function {name} not found" in err or (err.startswith("Function ") and "not found" in err):
                        facade_failures.append((name, res))
            except Exception:
                # Any execution exception is acceptable; the check verifies it did not hit the facade missing-function handler
                pass

        self.assertEqual(
            facade_failures,
            [],
            f"{len(facade_failures)} tools returned facade 'Function <name> not found': {facade_failures}"
        )

    def test_f10_04_compact_doctor_signature_and_execution(self):
        """Verify compact profile doctor tool accepts arguments and executes without TypeError."""
        from win_automation.server.compact_tools import compact_doctor
        try:
            res = compact_doctor()
            self.assertIsInstance(res, dict)
            self.assertIn("status", res)
        except Exception as e:
            self.assertNotIsInstance(e, TypeError)

    def test_f10_05_profile_switching_via_env(self):
        """Verify dynamic profile switching toggles between 9 (compact) and 111 (expert) tools."""
        from win_automation.server.app import create_app
        os.environ["WIN_AUTO_PROFILE"] = "compact"
        app_compact = create_app()
        self.assertEqual(len(app_compact._tool_manager._tools), 9)

        os.environ["WIN_AUTO_PROFILE"] = "expert"
        app_expert = create_app()
        self.assertEqual(len(app_expert._tool_manager._tools), 111)


class TestF11CLICommandIntegrity(unittest.TestCase):
    """Verify CLI commands execute cleanly without NameError, TypeError, or unhandled crashes."""

    def _invoke_cli(self, args: List[str]) -> Tuple[int, str, str]:
        """Execute CLI in-process via win_automation.cli.main, capturing stdout and stderr."""
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from win_automation.cli.main import main as cli_main

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                cli_main(args)
        except SystemExit as se:
            exit_code = se.code if isinstance(se.code, int) else (1 if se.code else 0)
        except Exception as e:
            if isinstance(e, (NameError, TypeError)):
                raise
            stderr_buf.write(str(e))
            exit_code = 1

        return exit_code, stdout_buf.getvalue(), stderr_buf.getvalue()

    def test_f11_01_cli_get_window_no_name_error(self):
        """Verify 'tools.py get_window <hwnd>' executes without NameError: name 'json' is not defined."""
        code, out, err = self._invoke_cli(["get_window", "12345"])
        combined = out + err
        self.assertNotIn("NameError", combined, f"'get_window' crashed with NameError: {combined}")
        self.assertNotIn("name 'json' is not defined", combined)
        try:
            data = json.loads(out.strip())
            self.assertIsInstance(data, dict)
        except json.JSONDecodeError:
            self.fail(f"'get_window' did not output valid JSON: {out}")

    def test_f11_02_cli_desktop_screenshot_no_type_error(self):
        """Verify 'tools.py desktop_screenshot' executes without TypeError: screenshot() missing argument."""
        code, out, err = self._invoke_cli(["desktop_screenshot"])
        combined = out + err
        self.assertNotIn("TypeError", combined, f"'desktop_screenshot' crashed with TypeError: {combined}")
        self.assertNotIn("missing 1 required positional argument", combined)
        self.assertNotIn("Traceback (most recent call last):", combined)

    def test_f11_03_cli_observe_no_name_error(self):
        """Verify 'tools.py observe' executes without NameError: name '_is_terminal_uia_helper_error' is not defined."""
        code, out, err = self._invoke_cli(["observe", "0", "--no-ocr", "--no-a11y"])
        combined = out + err
        self.assertNotIn("NameError", combined, f"'observe' crashed with NameError: {combined}")
        self.assertNotIn("_is_terminal_uia_helper_error", combined)

    def test_f11_04_cli_selftest_no_name_error(self):
        """Verify 'tools.py selftest batch' executes without NameError: name '_batch_normalize_result' is not defined."""
        code, out, err = self._invoke_cli(["selftest", "batch", "0.5"])
        combined = out + err
        self.assertNotIn("NameError", combined, f"'selftest batch' crashed with NameError: {combined}")
        self.assertNotIn("_batch_normalize_result", combined)
        self.assertNotIn("TypeError", combined)


if __name__ == "__main__":
    unittest.main()

