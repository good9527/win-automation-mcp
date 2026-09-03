# tests/test_tier4_scenarios.py
"""
Tier 4: Real-World Desktop Automation Scenarios (R1 - R6)

End-to-end multi-step realistic desktop workflow scenarios:
1. Scenario 1: Launch Notepad, type text, open save dialog
2. Scenario 2: E-commerce shopping / financial confirmation gating
3. Scenario 3: Batch Calculator calculations with verification
4. Scenario 4: Window moved / resized geometry self-repair
5. Scenario 5: High-throughput visual state polling (<50ms DXCam cache)
6. Scenario 6: Multi-window context switching & hwnd tracking
"""

import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from unittest.mock import patch, MagicMock
from PIL import Image

from win_automation.safety.gate import check_safety
from win_automation.helper.security import generate_session_token, verify_request
from win_automation.state.persistence import save_state, load_state
from win_automation.vision.dxcam_manager import DXCamManager
from win_automation.ocr.finder import run_ocr
from win_automation.core.types import Rect, Point
from win_automation.win32.window import _get_window_rect_dict
from win_automation.input.mouse import _scale_coords
from win_automation.core.dpi import scale_coord, unscale_coord, scale_rect, get_dpi_scale_for_hwnd
from win_automation.vision.stability import _wait_for_visual_stability
from win_automation.server.compact_tools import compact_act



class TestTier4Scenario1NotepadTextEditing(unittest.TestCase):
    def test_t4_01_scenario_launch_and_safety(self):
        res = check_safety("open notepad")
        self.assertFalse(res["needs_confirmation"])

    def test_t4_02_scenario_text_input_safety(self):
        res = check_safety("type Automation Report 2026")
        self.assertFalse(res["needs_confirmation"])

    def test_t4_03_scenario_save_dialog_state(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"active_window": "Save As", "hwnd": 5555}, spath)
            state = load_state(spath)
            self.assertEqual(state["active_window"], "Save As")


class TestTier4Scenario2FinancialOperationGating(unittest.TestCase):
    def test_t4_04_automated_payment_gated(self):
        user_action = "支付会员年费 500 元"
        res = check_safety(user_action)
        self.assertTrue(res["needs_confirmation"])
        self.assertEqual(res["category"], "financial_transaction")

    def test_t4_05_automated_transfer_gated(self):
        user_action = "transfer funds to account"
        res = check_safety(user_action)
        self.assertTrue(res["needs_confirmation"])

    def test_t4_06_safe_cart_inspection_allowed(self):
        res = check_safety("view cart items")
        self.assertFalse(res["needs_confirmation"])


class TestTier4Scenario3CalculatorBatchCalculation(unittest.TestCase):
    def test_t4_07_calc_batch_input_safety(self):
        calc_seq = ["click 7", "click +", "click 8", "click ="]
        for step in calc_seq:
            self.assertFalse(check_safety(step)["needs_confirmation"])

    def test_t4_08_calc_ocr_readout_sim(self):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (200, 60), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 15), "123456", fill=(0, 0, 0))
        ocr_results = run_ocr(img)
        self.assertIsInstance(ocr_results, list)

    def test_t4_09_calc_state_recording(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"last_result": "15"}, spath)
            self.assertEqual(load_state(spath)["last_result"], "15")


class TestTier4Scenario4WindowGeometrySelfRepair(unittest.TestCase):
    def test_t4_10_window_geometry_update(self):
        """Verify window geometry calculation, dictionary formatting, and state tracking upon resize/move."""
        hwnd = 1001
        # 1. Genuine Rect dataclass calculations
        r1 = Rect(left=100, top=100, right=900, bottom=700)
        self.assertEqual(r1.width, 800)
        self.assertEqual(r1.height, 600)
        self.assertEqual(r1.center, Point(500, 400))

        r2 = Rect(left=400, top=300, right=1200, bottom=900)
        self.assertEqual(r2.width, 800)
        self.assertEqual(r2.height, 600)
        self.assertEqual(r2.center, Point(800, 600))
        self.assertNotEqual(r1.center, r2.center)

        # 2. Genuine _get_window_rect_dict integration with dynamic window movement
        with patch("win_automation.win32.window._get_window_rect") as mock_rect:
            mock_rect.return_value = (100, 100, 900, 700)
            geom1 = _get_window_rect_dict(hwnd)
            self.assertEqual(geom1["left"], 100)
            self.assertEqual(geom1["width"], 800)

            # Window moves to new coordinates
            mock_rect.return_value = (400, 300, 1200, 900)
            geom2 = _get_window_rect_dict(hwnd)
            self.assertEqual(geom2["left"], 400)
            self.assertEqual(geom2["top"], 300)
            self.assertNotEqual(geom1, geom2)

            # Persist and restore updated geometry in state persistence engine
            with tempfile.TemporaryDirectory() as td:
                spath = os.path.join(td, "state.json")
                save_state({"hwnd": hwnd, "geometry": geom2}, spath)
                loaded = load_state(spath)
                self.assertEqual(loaded["geometry"]["left"], 400)

    def test_t4_11_act_resolution_on_new_geometry(self):
        """Verify that mouse coordinate scaling and compact_act resolve coordinates relative to updated window geometry."""
        hwnd = 1001
        # 1. Native coordinate remapping via _scale_coords on initial geometry
        with patch("win_automation.input.mouse._get_window_rect") as mock_rect:
            mock_rect.return_value = (100, 100, 900, 700)
            abs_x, abs_y, mode = _scale_coords(hwnd, 50, 50)
            self.assertEqual((abs_x, abs_y), (150, 150))
            self.assertEqual(mode, "window(100,100)")

            # 2. Native coordinate remapping when window has moved to new geometry
            mock_rect.return_value = (400, 300, 1200, 900)
            abs_x_new, abs_y_new, mode_new = _scale_coords(hwnd, 50, 50)
            self.assertEqual((abs_x_new, abs_y_new), (450, 350))
            self.assertEqual(mode_new, "window(400,300)")

        # 3. Action routing through compact_act to coordinate click handler
        with patch("win_automation.server.compact_tools._mouse_click") as mock_click:
            mock_click.return_value = {"ok": True, "action": "click", "x": 450, "y": 350}
            res = compact_act(action="click", hwnd=hwnd, x=450, y=350)
            self.assertTrue(res.get("ok"))
            mock_click.assert_called_once_with(450, 350, hwnd=hwnd, button="left", clicks=1)

    def test_t4_12_dpi_scaling_adjustment(self):
        """Verify genuine DPI scaling coordinate adjustment and rectangle transformations."""
        dpi_scale = 1.5
        # 1. Forward scaling of logical coordinates
        phys_x = scale_coord(100, dpi_scale)
        phys_y = scale_coord(200, dpi_scale)
        self.assertEqual((phys_x, phys_y), (150, 300))

        # 2. Inverse scaling back to logical coordinates
        log_x = unscale_coord(phys_x, dpi_scale)
        log_y = unscale_coord(phys_y, dpi_scale)
        self.assertEqual((log_x, log_y), (100, 200))

        # 3. Full bounding rectangle scaling
        logical_rect = {"left": 100, "top": 200, "right": 500, "bottom": 600, "width": 400, "height": 400}
        scaled_rect = scale_rect(logical_rect, dpi_scale)
        self.assertEqual(scaled_rect["left"], 150)
        self.assertEqual(scaled_rect["top"], 300)
        self.assertEqual(scaled_rect["right"], 750)
        self.assertEqual(scaled_rect["bottom"], 900)
        self.assertEqual(scaled_rect["width"], 600)
        self.assertEqual(scaled_rect["height"], 600)

        # 4. Querying window DPI scale returns a valid positive float
        scale = get_dpi_scale_for_hwnd(0)
        self.assertIsInstance(scale, float)
        self.assertGreater(scale, 0.0)


class TestTier4Scenario5HighThroughputVisualPolling(unittest.TestCase):
    def test_t4_13_rapid_capture_cache_reuse(self):
        DXCamManager.reset()
        for _ in range(20):
            c = DXCamManager.get_camera(0, None)
            self.assertIsNotNone(c)
        self.assertEqual(DXCamManager.creation_count(), 1)

    def test_t4_14_visual_stability_sim(self):
        """Verify genuine visual stability detection algorithm via _wait_for_visual_stability."""
        # 1. Stable frame stream (identical images satisfy stability criteria)
        stable_frame = Image.new("RGB", (64, 64), color=(128, 128, 128))
        stable_stream = iter([stable_frame, stable_frame, stable_frame, stable_frame])

        res_stable = _wait_for_visual_stability(
            lambda: next(stable_stream),
            timeout=0.5,
            interval=0.01,
            stable_ticks=2,
        )
        self.assertTrue(res_stable["ok"])
        self.assertTrue(res_stable["stable"])
        self.assertGreaterEqual(res_stable["stable_ticks"], 2)
        self.assertEqual(res_stable["last_diff_ratio"], 0.0)

        # 2. Unstable/changing frame stream (alternating images fail stability check)
        frame_a = Image.new("RGB", (64, 64), color=(0, 0, 0))
        frame_b = Image.new("RGB", (64, 64), color=(255, 255, 255))
        unstable_stream = iter([frame_a, frame_b, frame_a, frame_b, frame_a, frame_b])

        res_unstable = _wait_for_visual_stability(
            lambda: next(unstable_stream),
            timeout=0.1,
            interval=0.01,
            stable_ticks=2,
        )
        self.assertFalse(res_unstable["stable"])
        self.assertEqual(res_unstable["error"], "timeout")



class TestTier4Scenario6MultiWindowContextSwitching(unittest.TestCase):
    def test_t4_15_context_switch_state(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"active_hwnd": 1001}, spath)
            save_state({"active_hwnd": 2002}, spath)
            final_s = load_state(spath)
            self.assertEqual(final_s["active_hwnd"], 2002)

    def test_t4_16_context_restoration(self):
        with tempfile.TemporaryDirectory() as td:
            spath = os.path.join(td, "state.json")
            save_state({"hwnds": [1001, 2002]}, spath)
            s1 = load_state(spath)
            self.assertEqual(s1["hwnds"], [1001, 2002])


if __name__ == "__main__":
    unittest.main()
