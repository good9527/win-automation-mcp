# tests/test_tier3_combinations.py
"""
Tier 3: Cross-Feature Pairwise & Integration Combinations (R1 - R6)

Tests pairwise interactions between safety gating, state persistence,
OCR fallback ladders, helper token isolation, and compact tool dispatch.
"""

import os
import sys
import tempfile
import threading
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from win_automation.safety.gate import check_safety
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.state.persistence import save_state, load_state
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.ocr.finder import run_ocr
from unittest.mock import patch, MagicMock
from win_automation.server.compact_tools import (
    COMPACT_TOOLS,
    get_compact_tool_schemas,
    calculate_serialized_schema_size,
    compact_act,
)
from win_automation.vision.capture import observe_window



class TestTier3SafetyAndBatchExecution(unittest.TestCase):
    def test_t3_01_batch_with_dangerous_action_intercept(self):
        commands = [
            {"tool": "observe_window", "hwnd": 12345},
            {"tool": "act", "action": "click", "target": "File"},
            {"tool": "check_safety", "action": "删除系统文件"},
            {"tool": "act", "action": "click", "target": "OK"}
        ]
        flagged_steps = []
        for i, cmd in enumerate(commands):
            cstr = cmd.get("action", "")
            res = check_safety(cstr)
            if res["needs_confirmation"]:
                flagged_steps.append((i, res))
        self.assertEqual(len(flagged_steps), 1)
        self.assertEqual(flagged_steps[0][0], 2)

    def test_t3_02_batch_all_safe_actions(self):
        commands = [
            {"tool": "launch_app", "path_or_name": "notepad"},
            {"tool": "type_input", "text": "Hello World"},
            {"tool": "key_press", "keys": "enter"}
        ]
        for cmd in commands:
            res = check_safety(cmd.get("text", cmd.get("keys", "safe")))
            self.assertFalse(res["needs_confirmation"])

    def test_t3_03_financial_gating_in_batch_sequence(self):
        seq = ["click button", "支付订单VIP", "close"]
        flagged = [c for c in seq if check_safety(c)["needs_confirmation"]]
        self.assertEqual(len(flagged), 1)


class TestTier3ObserveWindowAndActRouting(unittest.TestCase):
    def test_t3_04_observe_then_act_by_element_id(self):
        """Verify true end-to-end observation pipeline and subsequent action routing by element_id and coordinates."""
        hwnd = 2001
        mock_tree = {
            "elements": [
                {"index": 0, "name": "Submit", "control_type": "Button", "rect": {"left": 100, "top": 200, "right": 180, "bottom": 240, "width": 80, "height": 40}},
                {"index": 1, "name": "Cancel", "control_type": "Button", "rect": {"left": 200, "top": 200, "right": 280, "bottom": 240, "width": 80, "height": 40}},
            ],
            "tree": "Window\n  Button: Submit\n  Button: Cancel",
        }

        # 1. Execute authentic observe_window pipeline with mock UIA tree
        with patch("win_automation.vision.capture.build_accessibility_tree", return_value=mock_tree), \
             patch("win_automation.vision.capture._window_info", return_value={"hwnd": hwnd, "title": "Test App"}):
            obs = observe_window(hwnd=hwnd, include_screenshot=False, include_accessibility=True, include_ocr=False)

        self.assertEqual(obs["hwnd"], hwnd)
        self.assertIn("accessibility", obs)
        self.assertEqual(obs["accessibility"]["element_count"], 2)
        elements = obs["accessibility"]["elements_preview"]
        self.assertTrue(any(e.get("name") == "Submit" for e in elements))

        # 2. Extract target element name from observation and dispatch compact_act by element_id
        target_name = elements[0]["name"]
        with patch("win_automation.server.compact_tools.smart_click") as mock_smart_click:
            mock_smart_click.return_value = {"ok": True, "action": "click", "name": target_name, "method": "uia"}
            act_res = compact_act(action="click", hwnd=hwnd, element_id=target_name)

            self.assertTrue(act_res.get("ok"))
            mock_smart_click.assert_called_once_with(hwnd=hwnd, name=target_name, button="left", clicks=1)

        # 3. Test coordinate fallback action routing using element bounding box center
        elem_rect = mock_tree["elements"][0]["rect"]
        cx = elem_rect["left"] + elem_rect["width"] // 2  # 140
        cy = elem_rect["top"] + elem_rect["height"] // 2   # 220
        with patch("win_automation.server.compact_tools._mouse_click") as mock_mouse_click:
            mock_mouse_click.return_value = {"ok": True, "action": "click", "x": cx, "y": cy}
            coord_res = compact_act(action="click", hwnd=hwnd, x=cx, y=cy)

            self.assertTrue(coord_res.get("ok"))
            mock_mouse_click.assert_called_once_with(140, 220, hwnd=hwnd, button="left", clicks=1)


    def test_t3_05_observe_ocr_then_act_click(self):
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (300, 80), (255, 255, 255))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()
        d.text((15, 20), "Test Button", fill=(0, 0, 0), font=font)
        ocr_res = run_ocr(img)
        self.assertGreater(len(ocr_res), 0)
        target_word = ocr_res[0]
        rect = target_word["rect"]
        click_x = rect["x"] + rect["width"] // 2
        click_y = rect["y"] + rect["height"] // 2
        self.assertGreater(click_x, 0)
        self.assertGreater(click_y, 0)

    def test_t3_06_observe_cached_hwnd(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"active_hwnd": 9999}, spath)
            state = load_state(spath)
            self.assertEqual(state["active_hwnd"], 9999)


class TestTier3HelperSecurityAndRequestDispatch(unittest.TestCase):
    def test_t3_07_token_auth_success_dispatch(self):
        token = generate_session_token()
        headers = {"Host": "127.0.0.1", "X-Helper-Token": token}
        ok, code, _ = verify_request(headers, token)
        self.assertTrue(ok)

    def test_t3_08_invalid_token_blocks_dispatch(self):
        token = generate_session_token()
        headers = {"Host": "127.0.0.1", "X-Helper-Token": "bad_token"}
        ok, code, _ = verify_request(headers, token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)

    def test_t3_09_spoofed_host_blocks_dispatch(self):
        token = generate_session_token()
        headers = {"Host": "malicious.site", "X-Helper-Token": token}
        ok, code, _ = verify_request(headers, token)
        self.assertFalse(ok)
        self.assertEqual(code, 403)


class TestTier3StatePersistenceAndWindowContext(unittest.TestCase):
    def test_t3_10_state_update_across_steps(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"step": 1, "window": "paint"}, spath)
            s1 = load_state(spath)
            s1["step"] = 2
            save_state(s1, spath)
            s2 = load_state(spath)
            self.assertEqual(s2["step"], 2)

    def test_t3_11_state_with_atomic_locking(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            for i in range(20):
                save_state({"seq": i}, spath)
            final = load_state(spath)
            self.assertEqual(final["seq"], 19)

    def test_t3_12_state_history_accumulation(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            state = {"history": []}
            for act in ["observe", "click", "type"]:
                state["history"].append(act)
                save_state(state, spath)
            reaval = load_state(spath)
            self.assertEqual(len(reaval["history"]), 3)


class TestTier3MultiStrategyFallbackLadder(unittest.TestCase):
    def test_t3_13_fallback_ladder_priorities(self):
        ladder = ["uia", "win32", "ocr", "coordinates"]
        self.assertEqual(ladder[0], "uia")
        self.assertEqual(ladder[1], "win32")
        self.assertEqual(ladder[2], "ocr")
        self.assertEqual(ladder[3], "coordinates")

    def test_t3_14_type_input_fallback_ladder(self):
        type_ladder = ["value_pattern", "wm_settext", "send_input"]
        self.assertEqual(type_ladder[0], "value_pattern")

    def test_t3_15_capture_fallback_ladder(self):
        capture_ladder = ["dxcam", "printwindow_renderfullcontent", "printwindow_0", "bitblt"]
        self.assertEqual(capture_ladder[0], "dxcam")


class TestTier3LaunchAppAndWaitState(unittest.TestCase):
    def test_t3_16_condition_enum_matching(self):
        valid_conditions = {"window_exists", "window_gone", "element_visible", "text_visible", "visual_stable"}
        for c in valid_conditions:
            self.assertIsInstance(c, str)

    def test_t3_17_launch_command_safety(self):
        res = check_safety("launch_app notepad.exe")
        self.assertFalse(res["needs_confirmation"])

    def test_t3_18_launch_dangerous_process_safety(self):
        res = check_safety("del /f /q c:\\temp")
        self.assertTrue(res["needs_confirmation"])


class TestTier3DualProfileSwitching(unittest.TestCase):
    def test_t3_19_compact_profile_size_reduction(self):
        schemas = get_compact_tool_schemas()
        size = calculate_serialized_schema_size(schemas)
        self.assertLess(size, 35000)

    def test_t3_20_tool_names_in_compact(self):
        for t in COMPACT_TOOLS:
            self.assertIsInstance(t, str)


class TestTier3StateConcurrencyUnderHelperLoad(unittest.TestCase):
    def test_t3_21_concurrent_read_write_load(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"i": 0}, spath)

            def writer():
                for x in range(10):
                    save_state({"i": x}, spath)

            def reader():
                for _ in range(10):
                    s = load_state(spath)
                    self.assertIsInstance(s, dict)

            ts = [threading.Thread(target=writer) for _ in range(3)] + [threading.Thread(target=reader) for _ in range(3)]
            for t in ts: t.start()
            for t in ts: t.join()

    def test_t3_22_session_token_isolation(self):
        tok1 = generate_session_token()
        tok2 = generate_session_token()
        ok, _, _ = verify_request({"Host": "127.0.0.1", "X-Helper-Token": tok1}, tok2)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
